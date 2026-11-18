"""Tests for evals.franco: runner, summary, reports and CLI. No network, no real sleeping."""

from __future__ import annotations

import itertools
import json
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
from evals import dialect, franco
from evals.franco import FrancoItem
from tests.conftest import make_settings

SECRET = "UPSTREAM-SECRET-DETAIL"


def _arz(item_id: str, text: str, arabic: str, *tags: str, split: str = "dev") -> FrancoItem:
    return FrancoItem(
        id=item_id, text=text, label="arz", arabic=arabic, meaning="gloss",
        tags=tags, split=split,
    )


ITEMS = [
    _arz("f001", "ana msh fahem", "أنا مش فاهم", "short", "no_numerals"),
    FrancoItem(
        id="f002", text="inshallah", label="ar", arabic="إن شاء الله", meaning="God willing",
        tags=("shared", "short", "no_numerals"), split="test",
    ),
    FrancoItem(id="f003", text="see you later", label="en", tags=("control",), split="dev"),
    FrancoItem(id="f004", text="à plus tard", label="fr", tags=("control",), split="test"),
    _arz("f005", "el meeting et2agel", "الـ meeting اتأجل", "code_switch", "numerals", split="test"),
]

# What the fake model "detects" for each text, and its Arabic-target outputs.
DETECT = {
    "ana msh fahem": "arz",  # correct
    "inshallah": "ar",  # correct
    "see you later": "en",  # correct
    "à plus tard": "arz",  # control false positive
    "el meeting et2agel": "ar",  # wrong
}
ARABIC_OUT = {
    "ana msh fahem": "أنا مش فاهم",  # chrF 100
    "inshallah": "إن شاء الله",  # chrF 100
    "el meeting et2agel": "الـ meeting اتأجل bokra",  # Latin leak
}


class ScriptedProvider(TranslationProvider):
    """Deterministic fake.

    - ``always``: raise this exception on every call.
    - ``script[(text, target)]``: exceptions raised (in order) on the first such calls.
    - ``detect`` / ``arabic_out``: detection per text and the output for ar/arz targets.
      Other targets return ``"<target>(<text>)"``.
    """

    name = "fake"

    def __init__(
        self,
        *,
        always: Exception | None = None,
        script: dict[tuple[str, str], list[Exception]] | None = None,
        detect: dict[str, str] | None = None,
        arabic_out: dict[str, str] | None = None,
    ) -> None:
        self.always = always
        self.script = {key: list(errors) for key, errors in (script or {}).items()}
        self.detect = {**DETECT, **(detect or {})}
        self.arabic_out = {**ARABIC_OUT, **(arabic_out or {})}
        self.calls: list[tuple[str, str]] = []

    async def translate(
        self, text: str, source: Language | None, target: Language
    ) -> TranslationResult:
        assert source is None, "the eval must use auto-detection"
        self.calls.append((text, target.code))
        if self.always is not None:
            raise self.always
        queue = self.script.get((text, target.code))
        if queue:
            raise queue.pop(0)
        if target.code in {"ar", "arz"}:
            translation = self.arabic_out.get(text, "نص")
        else:
            translation = f"{target.code}({text})"
        code = self.detect.get(text, "en")
        return TranslationResult(translation=translation, detected_source=get_language(code))

    async def to_arabic_script(self, text: str) -> str:
        raise AssertionError("this eval never calls script conversion")


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


async def _run(
    provider: ScriptedProvider, items: list[FrancoItem] = ITEMS, **kwargs: Any
) -> franco.FrancoRunResult:
    sleep = kwargs.pop("sleep", SleepSpy())
    return await franco.run_franco(_service(provider), items, sleep=sleep, clock=_clock(), **kwargs)


# --- run_franco -------------------------------------------------------------------------


async def test_passes_and_targets() -> None:
    provider = ScriptedProvider()
    await _run(provider)
    assert provider.calls == [
        ("ana msh fahem", "en"), ("ana msh fahem", "arz"),
        ("inshallah", "en"), ("inshallah", "ar"),
        ("see you later", "fr"),
        ("à plus tard", "en"),
        ("el meeting et2agel", "en"), ("el meeting et2agel", "arz"),
    ]


async def test_ar_item_is_arabized_to_ar() -> None:
    provider = ScriptedProvider()
    run = await _run(provider, [ITEMS[1]])
    assert provider.calls == [("inshallah", "en"), ("inshallah", "ar")]
    assert run.items[0].arabize_target == "ar"
    assert run.items[0].arabic_detected == "ar"


async def test_item_results_keep_raw_outputs_and_scores() -> None:
    run = await _run(ScriptedProvider())
    by_id = {r.id: r for r in run.items}
    assert [r.outcome for r in run.items] == ["correct", "correct", "correct", "wrong", "wrong"]

    first = by_id["f001"]
    assert first.detect_target == "en"
    assert first.translation == "en(ana msh fahem)"
    assert first.arabic_output == "أنا مش فاهم"
    assert first.chrf == pytest.approx(100.0)
    assert first.latin_leak is False
    assert first.detect_latency_ms == 250.0
    assert first.arabize_latency_ms == 250.0
    assert first.meaning == "gloss" and first.split == "dev"

    leak = by_id["f005"]
    assert leak.predicted == "ar"
    assert leak.latin_leak is True
    assert 0 < leak.chrf < 100

    control = by_id["f003"]
    assert control.detect_target == "fr"
    assert control.arabize_target is None
    assert control.arabic_output is None and control.chrf is None and control.latin_leak is None


async def test_delay_before_every_request_but_the_first() -> None:
    sleep = SleepSpy()
    await _run(ScriptedProvider(), delay=4.0, sleep=sleep)
    assert sleep.calls == [4.0] * (franco.request_count(ITEMS) - 1)


async def test_errors_are_recorded_per_pass() -> None:
    provider = ScriptedProvider(
        script={
            ("el meeting et2agel", "arz"): [ProviderBadOutputError(SECRET)],
            ("see you later", "fr"): [ProviderBadOutputError(SECRET)],
        }
    )
    run = await _run(provider)
    by_id = {r.id: r for r in run.items}

    arabize_error = by_id["f005"]
    assert arabize_error.outcome == "wrong"  # detection still ran
    assert arabize_error.arabize_error_type == "ProviderBadOutputError"
    assert arabize_error.arabic_output is None
    assert arabize_error.chrf is None and arabize_error.latin_leak is None

    detect_error = by_id["f003"]
    assert detect_error.outcome == "error"
    assert detect_error.predicted is None
    assert detect_error.detect_error_type == "ProviderBadOutputError"
    assert SECRET not in json.dumps([r.model_dump() for r in run.items], ensure_ascii=False)

    summary = franco.summarize_franco([r.model_dump() for r in run.items])
    arb = summary["arabization"]
    # Errors are excluded, never scored as chrF 0: two 100s remain.
    assert arb == {
        "n": 3, "scored": 2, "errors": 1, "mean_chrf": pytest.approx(100.0),
        "latin_leaks": 0, "latin_leak_rate": 0.0,
    }
    assert summary["errors"] == 1


async def test_auth_error_aborts_without_detail() -> None:
    with pytest.raises(dialect.EvalAborted) as excinfo:
        await _run(ScriptedProvider(always=ProviderAuthError(SECRET)))
    assert SECRET not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


async def test_rate_limit_then_success_retries_same_request() -> None:
    provider = ScriptedProvider(
        script={("inshallah", "ar"): [ProviderRateLimitError("429"), ProviderRateLimitError("429")]}
    )
    sleep = SleepSpy()
    run = await _run(provider, ITEMS[:2], delay=4.0, retry_wait=60.0, sleep=sleep)
    assert not run.partial
    assert [r.arabic_output for r in run.items] == ["أنا مش فاهم", "إن شاء الله"]
    assert provider.calls.count(("inshallah", "ar")) == 3
    assert sleep.calls == [4.0, 4.0, 4.0, 60.0, 60.0]


async def test_rate_limit_forever_stops_partial_and_drops_unfinished_item() -> None:
    provider = ScriptedProvider(script={("inshallah", "ar"): [ProviderRateLimitError("429")] * 10})
    run = await _run(provider)
    assert run.partial
    assert run.stop_reason == "rate_limit"
    assert [r.id for r in run.items] == ["f001"]  # f002's detection result is dropped
    assert run.not_run == len(ITEMS) - 1
    assert provider.calls.count(("inshallah", "ar")) == 1 + dialect.MAX_RETRIES


async def test_unexpected_exception_propagates() -> None:
    with pytest.raises(RuntimeError, match="boom"):
        await _run(ScriptedProvider(always=RuntimeError("boom")))


def test_request_count_and_select() -> None:
    assert franco.request_count(ITEMS) == 8  # 3 Arabic items x 2 + 2 controls
    assert [i.id for i in franco.select_franco(ITEMS, None, "test", None)] == ["f002", "f004", "f005"]
    assert [i.id for i in franco.select_franco(ITEMS, "short", None, None)] == ["f001", "f002"]
    assert [i.id for i in franco.select_franco(ITEMS, "control", "test", 1)] == ["f004"]
    assert franco.select_franco(ITEMS, "long", None, None) == []


# --- summary --------------------------------------------------------------------------


async def test_summary_detection_controls_and_groups() -> None:
    run = await _run(ScriptedProvider())
    summary = franco.summarize_franco([r.model_dump() for r in run.items])

    assert summary["attempted"] == 5
    assert summary["correct"] == 3
    assert summary["accuracy"] == pytest.approx(0.6)
    cm = summary["confusion_matrix"]
    assert list(cm) == ["arz", "ar", "en", "fr"]
    assert cm["fr"]["arz"] == 1
    assert cm["arz"]["ar"] == 1 and cm["arz"]["arz"] == 1

    fp = summary["control_false_positives"]
    assert (fp["n"], fp["false_positives"], fp["rate"]) == (2, 1, 0.5)

    arb = summary["arabization"]
    assert (arb["n"], arb["scored"], arb["errors"], arb["latin_leaks"]) == (3, 3, 0, 1)
    assert arb["latin_leak_rate"] == pytest.approx(1 / 3)
    f005_chrf = next(r.chrf for r in run.items if r.id == "f005")
    assert arb["mean_chrf"] == pytest.approx((100 + 100 + f005_chrf) / 3)

    assert list(summary["per_split"]) == ["dev", "test"]
    assert summary["per_split"]["dev"]["n"] == 2
    assert summary["per_split"]["test"]["accuracy"] == pytest.approx(1 / 3)
    assert summary["per_tag"]["control"]["arabize_n"] == 0
    assert summary["per_tag"]["control"]["mean_chrf"] is None
    assert summary["per_tag"]["code_switch"]["latin_leak_rate"] == 1.0
    assert summary["median_latency_ms"] == {"detect": 250.0, "arabize": 250.0}


# --- CLI (main) -------------------------------------------------------------------------


def _write_dataset(path: Path, items: list[FrancoItem]) -> Path:
    with open(path, "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.model_dump(mode="json", exclude_none=True), ensure_ascii=False) + "\n")
    return path


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    """Wire main() to fakes: Settings without .env, a scripted provider, fixed git hash."""
    state: dict[str, Any] = {"provider": ScriptedProvider(), "settings": []}

    def fake_build_provider(settings: Settings) -> TranslationProvider:
        state["settings"].append(settings)
        return state["provider"]

    monkeypatch.setattr(franco, "Settings", lambda: make_settings())
    monkeypatch.setattr(franco, "build_provider", fake_build_provider)
    monkeypatch.setattr(franco, "git_commit", lambda: "abc1234")
    state["dataset"] = _write_dataset(tmp_path / "ds.jsonl", ITEMS)
    state["out"] = tmp_path / "results"
    return state


def _main(cli: dict[str, Any], *extra: str, out: Path | None = None, **kwargs: Any) -> int:
    argv = ["--dataset", str(cli["dataset"]), "--out-dir", str(out or cli["out"]), *extra]
    kwargs.setdefault("sleep", SleepSpy())
    return franco.main(argv, **kwargs)


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
    assert meta["eval"] == "franco"
    assert meta["dataset"]["size"] == len(ITEMS)
    assert meta["dataset"]["sha256"] == franco.franco_hash(ITEMS)
    assert meta["model"] == "gemini-3.5-flash-lite"
    assert meta["prompt_fingerprint"] == {
        t: dialect.prompt_fingerprint(t) for t in ("en", "fr", "ar", "arz")
    }
    assert len(set(meta["prompt_fingerprint"].values())) == 4
    assert meta["git_commit"] == "abc1234"
    assert meta["filters"] == {"tag": None, "split": None, "limit": None}
    assert meta["requests_planned"] == 8
    assert meta["partial"] is False

    item = report["items"][0]
    assert item["text"] == "ana msh fahem"
    assert item["arabic_output"] == "أنا مش فاهم"  # Arabic stays readable (ensure_ascii=False)
    assert item["translation"] == "en(ana msh fahem)"

    # Re-scoring from the saved rows gives the same summary (no API calls needed).
    rescored = franco.summarize_franco(report["items"])
    rescored["not_run"] = report["summary"]["not_run"]
    assert json.loads(json.dumps(rescored)) == report["summary"]

    assert json_path.name.startswith("franco_") and ":" not in json_path.name
    assert "_gemini_gemini-3.5-flash-lite" in json_path.name

    assert "## Confusion matrix" in markdown
    assert "Control false positives (control detected as ar/arz): 1/2 = 50.0%" in markdown
    assert "## Per split" in markdown and "## Per tag" in markdown
    assert "| id | text | arabic ref | arz output | chrF | en output | meaning |" in markdown
    assert "| f001 | ana msh fahem | أنا مش فاهم | أنا مش فاهم | 100.0 | en(ana msh fahem) | gloss |" in markdown
    assert "| f005 | test | arz -> ar | el meeting et2agel |" in markdown
    assert "| f004 | à plus tard | fr -> arz | en(à plus tard) |" in markdown
    assert " *" in markdown  # f005 leak marker

    out = capsys.readouterr().out
    assert out.isascii()
    assert "Detection: 3/5 = 60.0%" in out
    assert "Control false positives: 1/2 = 50.0%" in out
    assert "[1/5] f001 arz -> arz CORRECT | to:arz chrF 100.0 leak=no" in out
    assert "[2/5] f002 ar -> ar CORRECT | to:ar chrF 100.0 leak=no" in out
    assert "[3/5] f003 en -> en CORRECT\n" in out
    assert "JSON: " in out and "MD:   " in out


def test_main_split_tag_limit_filters(cli: dict[str, Any], tmp_path: Path) -> None:
    assert _main(cli, "--split", "test", out=tmp_path / "a") == 0
    report, _, _ = _only_report(tmp_path / "a")
    assert [i["id"] for i in report["items"]] == ["f002", "f004", "f005"]
    assert report["meta"]["filters"] == {"tag": None, "split": "test", "limit": None}
    assert report["meta"]["requests_planned"] == 5

    assert _main(cli, "--tag", "short", "--limit", "1", out=tmp_path / "b") == 0
    report, _, _ = _only_report(tmp_path / "b")
    assert [i["id"] for i in report["items"]] == ["f001"]
    assert report["meta"]["dataset"]["size"] == len(ITEMS)


def test_main_model_override(cli: dict[str, Any]) -> None:
    assert _main(cli, "--model", "models/gemini-x:preview") == 0
    assert cli["settings"][0].gemini_model == "models/gemini-x:preview"
    _, _, json_path = _only_report(cli["out"])
    assert ":" not in json_path.name and "models-gemini-x-preview" in json_path.name


def test_main_arabize_error_progress_line(cli: dict[str, Any], capsys: pytest.CaptureFixture[str]) -> None:
    cli["provider"] = ScriptedProvider(
        script={("ana msh fahem", "arz"): [ProviderBadOutputError(SECRET)]}
    )
    assert _main(cli) == 0
    out = capsys.readouterr().out
    assert "f001 arz -> arz CORRECT | to:arz error:ProviderBadOutputError" in out
    assert SECRET not in out


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
    monkeypatch.setattr(franco, "Settings", lambda: make_settings(gemini_api_key=""))
    assert _main(cli) == 1
    assert "GEMINI_API_KEY is not set" in capsys.readouterr().out
    assert cli["provider"].calls == []


def _many(n_arz: int, n_controls: int) -> list[FrancoItem]:
    arz = [_arz(f"f{n:03d}", f"ana msh fahem {n}", "أنا مش فاهم", "no_numerals") for n in range(n_arz)]
    controls = [
        FrancoItem(id=f"f{100 + n:03d}", text=f"see you at {n}", label="en", tags=("control",), split="dev")
        for n in range(n_controls)
    ]
    return arz + controls


def test_confirmation_counts_requests_not_items(
    cli: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # 6 items but 5 x 2 + 1 = 11 requests: above the threshold, so it asks.
    cli["dataset"] = _write_dataset(tmp_path / "eleven.jsonl", _many(5, 1))
    prompts: list[str] = []

    def decline(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    assert _main(cli, input_fn=decline) == 1
    assert len(prompts) == 1
    assert "About to send 11 real requests" in capsys.readouterr().out
    assert cli["provider"].calls == []
    assert not cli["out"].exists()


def test_confirmation_not_needed_at_ten_requests(cli: dict[str, Any], tmp_path: Path) -> None:
    # 3 x 2 + 4 = 10 requests: at the threshold, no prompt.
    cli["dataset"] = _write_dataset(tmp_path / "ten.jsonl", _many(3, 4))

    def input_fn(prompt: str) -> str:
        raise AssertionError("must not ask for <= 10 requests")

    assert _main(cli, input_fn=input_fn) == 0
    assert len(cli["provider"].calls) == 10


@pytest.mark.parametrize("answer", ["", EOFError])
def test_confirmation_declined_sends_nothing(cli: dict[str, Any], tmp_path: Path, answer: object) -> None:
    cli["dataset"] = _write_dataset(tmp_path / "many.jsonl", _many(6, 5))

    def input_fn(prompt: str) -> str:
        if answer is EOFError:
            raise EOFError
        return str(answer)

    assert _main(cli, input_fn=input_fn) == 1
    assert cli["provider"].calls == []


def test_confirmation_accepted_or_skipped(
    cli: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cli["dataset"] = _write_dataset(tmp_path / "many.jsonl", _many(6, 5))
    prompts: list[str] = []

    def accept(prompt: str) -> str:
        prompts.append(prompt)
        return "y"

    assert _main(cli, input_fn=accept, out=tmp_path / "a") == 0
    assert "About to send 17 real requests" in capsys.readouterr().out
    assert _main(cli, "--yes", input_fn=accept, out=tmp_path / "b") == 0
    assert len(prompts) == 1  # --yes skipped the prompt
    assert len(cli["provider"].calls) == 34


def test_main_baseline_diff(cli: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _main(cli, out=tmp_path / "base") == 0
    _, _, base_json = _only_report(tmp_path / "base")

    # f005 now detected right (fixed) and without a leak; f001 now wrong (broken) and leaking.
    cli["provider"] = ScriptedProvider(
        detect={"el meeting et2agel": "arz", "ana msh fahem": "en"},
        arabic_out={"el meeting et2agel": "الـ meeting اتأجل", "ana msh fahem": "ana مش فاهم"},
    )
    assert _main(cli, "--baseline", str(base_json), out=tmp_path / "new") == 0
    report, markdown, _ = _only_report(tmp_path / "new")
    diff = report["baseline"]
    assert diff["fixed"] == ["f005"]
    assert diff["broken"] == ["f001"]
    assert diff["new_leaks"] == ["f001"]
    assert diff["fixed_leaks"] == ["f005"]
    assert diff["dataset_hash_changed"] is False
    assert diff["prompt_changed"] is False
    assert diff["baseline_mean_chrf"] is not None
    assert "## Baseline comparison" in markdown
    assert "Detection fixed (1): f005" in markdown
    assert "New Latin leaks (1): f001" in markdown
    assert "Warning" not in markdown
    assert "Baseline: 1 fixed, 1 broken" in capsys.readouterr().out


def test_main_baseline_warns_on_dataset_change(cli: dict[str, Any], tmp_path: Path) -> None:
    assert _main(cli, out=tmp_path / "base") == 0
    _, _, base_json = _only_report(tmp_path / "base")
    extra = [*ITEMS, _arz("f006", "yalla bina", "يلا بينا", "short", "no_numerals")]
    cli["dataset"] = _write_dataset(tmp_path / "ds2.jsonl", extra)
    assert _main(cli, "--baseline", str(base_json), out=tmp_path / "new") == 0
    report, markdown, _ = _only_report(tmp_path / "new")
    assert report["baseline"]["dataset_hash_changed"] is True
    assert report["baseline"]["only_in_current"] == ["f006"]
    assert "**Warning:** the dataset hash differs" in markdown


def test_main_rejects_dialect_baseline(cli: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    dialect_like = tmp_path / "dialect.json"
    dialect_like.write_text(
        json.dumps({"meta": {"dataset": {}}, "summary": {}, "items": []}), encoding="utf-8"
    )
    assert _main(cli, "--baseline", str(dialect_like)) == 1
    assert "not a franco result JSON" in capsys.readouterr().out
    assert cli["provider"].calls == []


def test_main_rejects_unknown_split(cli: dict[str, Any]) -> None:
    with pytest.raises(SystemExit) as excinfo:
        _main(cli, "--split", "train")
    assert excinfo.value.code == 2
    assert cli["provider"].calls == []


def test_main_runs_on_real_dataset_with_limit(cli: dict[str, Any], tmp_path: Path) -> None:
    argv = ["--limit", "3", "--out-dir", str(tmp_path / "real")]
    assert franco.main(argv, sleep=SleepSpy()) == 0
    report, _, _ = _only_report(tmp_path / "real")
    assert [i["id"] for i in report["items"]] == ["f001", "f002", "f003"]
    assert report["meta"]["dataset"]["path"] == "evals/data/franco.jsonl"
    assert len(cli["provider"].calls) == 5  # 2 + 2 + 1 (f003 is a control)
