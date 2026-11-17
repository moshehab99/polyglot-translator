"""Tests for evals.dialect: runner, reports and CLI. No network, no real sleeping."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.config import Settings
from app.languages import Language, get_language
from app.providers.base import (
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderRateLimitError,
    TranslationProvider,
    TranslationResult,
)
from app.services.translation_service import TranslationService
from evals import dialect
from evals.dataset import EvalItem
from tests.conftest import make_settings

SECRET = "UPSTREAM-SECRET-DETAIL"


def _item(item_id: str, text: str, label: str, *tags: str) -> EvalItem:
    return EvalItem(id=item_id, text=text, label=label, tags=tags)


ITEMS = [
    _item("d001", "مش عارف", "arz", "clear"),  # fake -> arz: correct
    _item("d002", "أنا لا أعرف", "ar", "clear"),  # fake -> ar: correct
    _item("d003", "رايح الشغل", "arz", "no_markers"),  # fake -> ar: wrong
    _item("d004", "ERR نص", "ar", "short"),  # fake raises: error
    _item("d005", "hello there", "ar", "code_switch"),  # fake -> en: wrong (other)
]


class ScriptedProvider(TranslationProvider):
    """Detection depends on the text.

    - ``always``: raise this exception on every call.
    - ``script[text]``: exceptions raised (in order) on the first calls for ``text``.
    - ``overrides[text]``: detected code to return for ``text``.
    - Otherwise: "ERR" in text -> ProviderBadOutputError; Latin letters -> en;
      contains مش -> arz; else ar.
    """

    name = "fake"

    def __init__(
        self,
        *,
        always: Exception | None = None,
        script: dict[str, list[Exception]] | None = None,
        overrides: dict[str, str] | None = None,
    ) -> None:
        self.always = always
        self.script = {text: list(errors) for text, errors in (script or {}).items()}
        self.overrides = overrides or {}
        self.calls: list[str] = []

    async def translate(
        self, text: str, source: Language | None, target: Language
    ) -> TranslationResult:
        assert source is None, "the eval must use auto-detection"
        self.calls.append(text)
        if self.always is not None:
            raise self.always
        queue = self.script.get(text)
        if queue:
            raise queue.pop(0)
        if text in self.overrides:
            code = self.overrides[text]
        elif "ERR" in text:
            raise ProviderBadOutputError(SECRET, provider=self.name)
        elif any("a" <= ch.lower() <= "z" for ch in text):
            code = "en"
        elif "مش" in text:
            code = "arz"
        else:
            code = "ar"
        return TranslationResult(translation=f"EN({text})", detected_source=get_language(code))


class SleepSpy:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def _clock() -> Any:
    ticks = itertools.count(0.0, 0.25)
    return lambda: next(ticks)


def _service(provider: TranslationProvider) -> TranslationService:
    return TranslationService(provider, max_chars=5000)


async def _run(provider: ScriptedProvider, items: list[EvalItem] = ITEMS, **kwargs: Any) -> dialect.RunResult:
    sleep = kwargs.pop("sleep", SleepSpy())
    return await dialect.run_eval(
        _service(provider), items, "en", sleep=sleep, clock=_clock(), **kwargs
    )


# --- run_eval ----------------------------------------------------------------------


async def test_outcomes_correct_wrong_error() -> None:
    run = await _run(ScriptedProvider())
    assert not run.partial
    assert run.not_run == 0
    by_id = {r.id: r for r in run.items}
    assert [r.outcome for r in run.items] == ["correct", "correct", "wrong", "error", "wrong"]
    assert by_id["d003"].predicted == "ar"
    assert by_id["d005"].predicted == "en"
    assert by_id["d001"].translation == "EN(مش عارف)"
    assert by_id["d001"].latency_ms == 250.0

    error = by_id["d004"]
    assert error.predicted is None
    assert error.error_type == "ProviderBadOutputError"
    assert error.translation is None
    assert error.latency_ms is None
    assert SECRET not in json.dumps([r.model_dump() for r in run.items], ensure_ascii=False)


async def test_delay_only_between_items() -> None:
    sleep = SleepSpy()
    await _run(ScriptedProvider(), delay=4.0, sleep=sleep)
    assert sleep.calls == [4.0] * (len(ITEMS) - 1)


async def test_auth_error_aborts_without_detail() -> None:
    with pytest.raises(dialect.EvalAborted) as excinfo:
        await _run(ScriptedProvider(always=ProviderAuthError(SECRET)))
    assert SECRET not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


async def test_rate_limit_then_success_retries_same_item() -> None:
    provider = ScriptedProvider(
        script={"أنا لا أعرف": [ProviderRateLimitError("429"), ProviderRateLimitError("429")]}
    )
    sleep = SleepSpy()
    run = await _run(provider, ITEMS[:2], delay=4.0, retry_wait=60.0, sleep=sleep)
    assert [r.outcome for r in run.items] == ["correct", "correct"]
    assert not run.partial
    assert provider.calls == ["مش عارف"] + ["أنا لا أعرف"] * 3
    assert sleep.calls == [4.0, 60.0, 60.0]


async def test_rate_limit_forever_stops_partial() -> None:
    provider = ScriptedProvider(script={"أنا لا أعرف": [ProviderRateLimitError("429")] * 10})
    sleep = SleepSpy()
    run = await _run(provider, delay=4.0, retry_wait=60.0, sleep=sleep)
    assert run.partial
    assert run.stop_reason == "rate_limit"
    assert [r.id for r in run.items] == ["d001"]
    assert run.not_run == len(ITEMS) - 1
    assert provider.calls.count("أنا لا أعرف") == 1 + dialect.MAX_RETRIES
    assert sleep.calls == [4.0, 60.0, 60.0]


async def test_unexpected_exception_propagates() -> None:
    provider = ScriptedProvider(always=RuntimeError("boom"))
    with pytest.raises(RuntimeError, match="boom"):
        await _run(provider)


def test_select_items_tag_then_limit() -> None:
    assert [i.id for i in dialect.select_items(ITEMS, None, None)] == [i.id for i in ITEMS]
    assert [i.id for i in dialect.select_items(ITEMS, None, 2)] == ["d001", "d002"]
    assert [i.id for i in dialect.select_items(ITEMS, "clear", None)] == ["d001", "d002"]
    assert [i.id for i in dialect.select_items(ITEMS, "clear", 1)] == ["d001"]
    assert dialect.select_items(ITEMS, "polite", None) == []


# --- metadata helpers ----------------------------------------------------------------


def test_prompt_fingerprint_is_stable_and_target_specific() -> None:
    first = dialect.prompt_fingerprint("en")
    assert first == dialect.prompt_fingerprint("en")
    assert len(first) == 12
    int(first, 16)
    assert dialect.prompt_fingerprint("fr") != first


def test_report_basename_is_file_name_safe() -> None:
    created = datetime(2026, 11, 18, 9, 5, 7, tzinfo=UTC)
    name = dialect.report_basename(created, "gemini", "models/gemini-3.5:flash lite")
    assert name == "dialect_20261118-090507_gemini_models-gemini-3.5-flash-lite"


def test_write_reports_never_overwrites(tmp_path: Path) -> None:
    first = dialect.write_reports({"a": "١"}, "# one\n", tmp_path, "dialect_x")
    second = dialect.write_reports({"a": "٢"}, "# two\n", tmp_path, "dialect_x")
    assert [p.name for p in first] == ["dialect_x.json", "dialect_x.md"]
    assert [p.name for p in second] == ["dialect_x-2.json", "dialect_x-2.md"]
    with open(first[0], encoding="utf-8") as fh:
        assert json.load(fh) == {"a": "١"}


def test_diff_baseline() -> None:
    def report(outcomes: dict[str, str], sha: str, fp: str = "fp") -> dict[str, Any]:
        return {
            "meta": {"dataset": {"sha256": sha}, "prompt_fingerprint": fp},
            "summary": {"accuracy": 0.5, "attempted": len(outcomes)},
            "items": [{"id": i, "outcome": o} for i, o in outcomes.items()],
        }

    base = report({"d1": "wrong", "d2": "correct", "d3": "error", "d4": "correct"}, "h1")
    cur = report({"d1": "correct", "d2": "wrong", "d3": "error", "d5": "correct"}, "h1", "fp2")
    diff = dialect.diff_baseline(cur, base, "old.json")
    assert diff["fixed"] == ["d1"]
    assert diff["broken"] == ["d2"]
    assert diff["only_in_current"] == ["d5"]
    assert diff["only_in_baseline"] == ["d4"]
    assert diff["dataset_hash_changed"] is False
    assert diff["prompt_changed"] is True
    assert dialect.diff_baseline(report({}, "h2"), base)["dataset_hash_changed"] is True


# --- CLI (main) --------------------------------------------------------------------


def _write_dataset(path: Path, items: list[EvalItem]) -> Path:
    with open(path, "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.model_dump(exclude_none=True), ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Wire main() to fakes: Settings without .env, a scripted provider, fixed git hash."""
    state: dict[str, Any] = {"provider": ScriptedProvider(), "settings": []}

    def fake_build_provider(settings: Settings) -> TranslationProvider:
        state["settings"].append(settings)
        return state["provider"]

    monkeypatch.setattr(dialect, "Settings", lambda: make_settings())
    monkeypatch.setattr(dialect, "build_provider", fake_build_provider)
    monkeypatch.setattr(dialect, "git_commit", lambda: "abc1234")
    state["dataset"] = _write_dataset(tmp_path / "ds.jsonl", ITEMS)
    state["out"] = tmp_path / "results"
    return state


def _main(cli: dict[str, Any], *extra: str, out: Path | None = None, **kwargs: Any) -> int:
    argv = ["--dataset", str(cli["dataset"]), "--out-dir", str(out or cli["out"]), *extra]
    kwargs.setdefault("sleep", SleepSpy())
    return dialect.main(argv, **kwargs)


def _only_report(out: Path) -> tuple[dict[str, Any], str, Path]:
    [json_path] = list(out.glob("*.json"))
    [md_path] = list(out.glob("*.md"))
    assert json_path.stem == md_path.stem
    with open(json_path, encoding="utf-8") as fh:
        report = json.load(fh)
    with open(md_path, encoding="utf-8") as fh:
        markdown = fh.read()
    return report, markdown, json_path


def test_main_writes_reports(cli: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(cli) == 0
    report, markdown, json_path = _only_report(cli["out"])

    assert set(report) == {"meta", "summary", "items"}
    meta = report["meta"]
    assert {
        "created_utc", "dataset", "provider", "model", "target", "prompt_fingerprint",
        "git_commit", "filters", "selected", "partial", "stop_reason", "not_run",
    } <= set(meta)
    assert meta["dataset"]["size"] == len(ITEMS)
    assert len(meta["dataset"]["sha256"]) == 64
    assert meta["provider"] == "gemini"
    assert meta["model"] == "gemini-3.5-flash-lite"
    assert meta["target"] == "en"
    assert meta["prompt_fingerprint"] == dialect.prompt_fingerprint("en")
    assert meta["git_commit"] == "abc1234"
    assert meta["partial"] is False
    assert meta["filters"] == {"tag": None, "limit": None}

    summary = report["summary"]
    assert summary["attempted"] == 5
    assert summary["correct"] == 2
    assert summary["accuracy"] == pytest.approx(0.4)

    item = report["items"][0]
    assert set(item) == {
        "id", "text", "label", "predicted", "outcome", "tags", "translation",
        "error_type", "latency_ms",
    }
    assert item["text"] == "مش عارف"  # Arabic stays readable (ensure_ascii=False)

    assert ":" not in json_path.name
    assert json_path.name.startswith("dialect_") and "_gemini_gemini-3.5-flash-lite" in json_path.name

    assert "## Confusion matrix" in markdown
    assert "## Per tag" in markdown
    assert "| d003 | arz -> ar | رايح الشغل |" in markdown
    assert "| d004 | ar -> error (ProviderBadOutputError) | ERR نص |" in markdown
    assert SECRET not in markdown and SECRET not in json.dumps(report, ensure_ascii=False)

    out = capsys.readouterr().out
    assert out.isascii()
    assert "Accuracy: 2/5 = 40.0%" in out
    assert "JSON: " in out and "MD:   " in out


def test_main_limit_and_tag_filters(cli: dict[str, Any]) -> None:
    assert _main(cli, "--tag", "clear", "--limit", "1") == 0
    report, _, _ = _only_report(cli["out"])
    assert [i["id"] for i in report["items"]] == ["d001"]
    assert report["meta"]["filters"] == {"tag": "clear", "limit": 1}
    assert report["meta"]["dataset"]["size"] == len(ITEMS)


def test_main_model_override(cli: dict[str, Any]) -> None:
    assert _main(cli, "--model", "models/gemini-x:preview") == 0
    assert cli["settings"][0].gemini_model == "models/gemini-x:preview"
    report, _, json_path = _only_report(cli["out"])
    assert report["meta"]["model"] == "models/gemini-x:preview"
    assert ":" not in json_path.name and "models-gemini-x-preview" in json_path.name


def test_main_rate_limit_forever_writes_partial_report(
    cli: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    cli["provider"] = ScriptedProvider(always=ProviderRateLimitError(SECRET))
    assert _main(cli) == 2
    report, markdown, _ = _only_report(cli["out"])
    assert report["meta"]["partial"] is True
    assert report["meta"]["stop_reason"] == "rate_limit"
    assert report["meta"]["not_run"] == len(ITEMS)
    assert report["summary"]["attempted"] == 0
    assert "Partial run" in markdown
    out = capsys.readouterr().out
    assert "midnight Pacific time" in out
    assert SECRET not in out


def test_main_auth_error_aborts(cli: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    cli["provider"] = ScriptedProvider(always=ProviderAuthError(SECRET))
    assert _main(cli) == 1
    assert not cli["out"].exists()
    out = capsys.readouterr().out
    assert "Authentication" in out
    assert SECRET not in out


def test_main_config_error_is_reported(
    cli: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(dialect, "Settings", lambda: make_settings(gemini_api_key=""))
    assert _main(cli) == 1
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().out
    assert cli["provider"].calls == []


@pytest.mark.parametrize("answer", ["n", "", EOFError])
def test_main_confirmation_declined_sends_nothing(
    cli: dict[str, Any], tmp_path: Path, answer: object
) -> None:
    many = [_item(f"d{n:03d}", f"نص رقم {n}", "ar", "clear") for n in range(1, 12)]
    cli["dataset"] = _write_dataset(tmp_path / "many.jsonl", many)

    def input_fn(prompt: str) -> str:
        if answer is EOFError:
            raise EOFError
        return str(answer)

    assert _main(cli, input_fn=input_fn) == 1
    assert cli["provider"].calls == []
    assert not cli["out"].exists()


def test_main_confirmation_accepted_or_skipped(cli: dict[str, Any], tmp_path: Path) -> None:
    many = [_item(f"d{n:03d}", f"نص رقم {n}", "ar", "clear") for n in range(1, 12)]
    cli["dataset"] = _write_dataset(tmp_path / "many.jsonl", many)
    prompts: list[str] = []

    def input_fn(prompt: str) -> str:
        prompts.append(prompt)
        return "y"

    assert _main(cli, input_fn=input_fn, out=tmp_path / "a") == 0
    assert len(prompts) == 1
    assert _main(cli, "--yes", input_fn=input_fn, out=tmp_path / "b") == 0
    assert len(prompts) == 1  # --yes skipped the prompt
    assert len(cli["provider"].calls) == 22


def test_main_small_run_needs_no_confirmation(cli: dict[str, Any]) -> None:
    def input_fn(prompt: str) -> str:
        raise AssertionError("must not ask for <= 10 requests")

    assert _main(cli, input_fn=input_fn) == 0


@pytest.mark.parametrize("target", ["ar", "arz", "xx"])
def test_main_rejects_arabic_or_unknown_target(cli: dict[str, Any], target: str) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _main(cli, "--target", target)
    assert excinfo.value.code == 2
    assert cli["provider"].calls == []


def test_main_baseline_diff(cli: dict[str, Any], tmp_path: Path) -> None:
    assert _main(cli, out=tmp_path / "base") == 0
    _, _, base_json = _only_report(tmp_path / "base")

    # New prompt behaviour: d003 now right (fixed), d002 now wrong (broken).
    cli["provider"] = ScriptedProvider(overrides={"رايح الشغل": "arz", "أنا لا أعرف": "arz"})
    assert _main(cli, "--baseline", str(base_json), out=tmp_path / "new") == 0
    report, markdown, _ = _only_report(tmp_path / "new")
    diff = report["baseline"]
    assert diff["fixed"] == ["d003"]
    assert diff["broken"] == ["d002"]
    assert diff["dataset_hash_changed"] is False
    assert "## Baseline comparison" in markdown
    assert "Fixed (1): d003" in markdown
    assert "Broken (1): d002" in markdown
    assert "Warning" not in markdown


def test_main_baseline_warns_on_dataset_change(
    cli: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert _main(cli, out=tmp_path / "base") == 0
    _, _, base_json = _only_report(tmp_path / "base")

    extra = [*ITEMS, _item("d006", "الجو حلو", "arz", "clear")]
    cli["dataset"] = _write_dataset(tmp_path / "ds2.jsonl", extra)
    assert _main(cli, "--baseline", str(base_json), out=tmp_path / "new") == 0
    report, markdown, _ = _only_report(tmp_path / "new")
    assert report["baseline"]["dataset_hash_changed"] is True
    assert report["baseline"]["only_in_current"] == ["d006"]
    assert "**Warning:** the dataset hash differs" in markdown
    assert "WARNING: dataset hash differs" in capsys.readouterr().out


def test_main_bad_baseline_aborts_before_requests(cli: dict[str, Any], tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    assert _main(cli, "--baseline", str(bad)) == 1
    assert cli["provider"].calls == []


def test_main_runs_on_real_dataset_with_limit(cli: dict[str, Any], tmp_path: Path) -> None:
    argv = ["--limit", "3", "--out-dir", str(tmp_path / "real")]
    assert dialect.main(argv, sleep=SleepSpy()) == 0
    report, _, _ = _only_report(tmp_path / "real")
    assert [i["id"] for i in report["items"]] == ["d001", "d002", "d003"]
    assert report["meta"]["dataset"]["path"] == "evals/data/dialect.jsonl"
    assert len(cli["provider"].calls) == 3
