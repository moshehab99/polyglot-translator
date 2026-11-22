"""Franco-Arabic (Arabizi) eval: Egyptian Arabic typed in Latin script.

The dataset is JSON Lines, one object per line::

    {"id": "f001", "text": "ana msh fahem enta 3ayez eh", "label": "arz",
     "arabic": "أنا مش فاهم إنت عايز إيه", "meaning": "I don't understand what you want",
     "tags": ["clear", "numerals"], "split": "dev", "note": "optional"}

Every item goes through the real app path
(``Settings -> build_provider -> TranslationService``):

1. Detection: ``translate(text, "auto", "en")`` (``"fr"`` for items labelled ``en``).
2. Arabization, chosen with ``--arabize``:
   - ``script`` (default): ``to_arabic_script(text)`` for every item. ar/arz outputs are
     scored with chrF against the ``arabic`` reference plus a Latin-leak check; controls
     must come back unchanged.
   - ``translate`` (the baseline path): ``translate(text, "auto", item.label)`` for ar/arz
     items only, scored the same way.

Run with ``uv run python -m evals.franco --help``. Only ``main`` builds the real
provider; ``run_franco`` takes the service as a parameter so tests inject a fake.
Console output is ASCII only; Arabic goes in the report files. See ``evals/README.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import Settings
from app.languages import AUTO
from app.providers.base import TranslationResult
from app.providers.factory import build_provider
from app.providers.prompts import build_script_system_prompt, build_script_user_message
from app.providers.schemas import ScriptOutput, json_schema_for
from app.services.translation_service import TranslationService
from evals import metrics
from evals.dataset import DatasetError, check_text, load_dataset
from evals.dialect import (
    CONFIRM_THRESHOLD,
    DEFAULT_OUT_DIR,
    MAX_RETRIES,
    QUOTA_MESSAGE,
    Attempt,
    EvalAborted,
    RateLimitExhausted,
    Sleep,
    _cell,
    _confirm,
    _ids,
    _non_negative_float,
    _pct,
    _positive_int,
    diff_baseline,
    display_path,
    git_commit,
    load_baseline,
    prompt_fingerprint,
    report_basename,
    retry_request,
    say,
    select_items,
    write_reports,
)

DEFAULT_FRANCO_DATASET = Path(__file__).parent / "data" / "franco.jsonl"

FRANCO_LABELS: tuple[str, ...] = ("arz", "ar", "en", "fr", "it", "de", "es")
ARABIC_LABELS = frozenset({"ar", "arz"})
CM_COLUMNS: tuple[str, ...] = (*FRANCO_LABELS, "other", "error")
FINGERPRINT_TARGETS: tuple[str, ...] = ("en", "fr", "ar", "arz")
SPLITS: tuple[str, ...] = ("dev", "test")

ArabizeMode = Literal["script", "translate"]
ARABIZE_MODES: tuple[str, ...] = ("script", "translate")
SCRIPT_TARGET = "script"  # arabize_target recorded for the script-conversion pass
ARABIZE_DESCRIPTIONS = {
    "script": "script conversion: to_arabic_script(text), every item",
    "translate": "translation: translate(text, auto, item label), ar/arz items only",
}

# Fixed tag vocabulary. An unknown tag is a loading error.
FRANCO_TAGS: frozenset[str] = frozenset(
    {
        "clear",  # clear, typical example
        "short",  # 1-3 words
        "numerals",  # uses 2 3 5 7 8 9 for letters (ء ع خ ح غ ق)
        "no_numerals",  # letters only (a for ع, kh, gh, ...)
        "code_switch",  # English words inside
        "chat",  # abbreviations, dropped vowels, elongation
        "ambiguous",  # contains words that are also real English/French words
        "shared",  # religious / greeting phrase used by both varieties (always ar)
        "long",  # 2-3 sentences
        "control",  # not Franco: real en/fr/it/de/es text, label = its language
    }
)

_ARABIC_LETTER = re.compile(r"[ء-ي]")

Outcome = Literal["correct", "wrong", "error"]


# --- dataset -------------------------------------------------------------------------


class FrancoItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^f\d{3,}$")
    text: str
    label: Literal["arz", "ar", "en", "fr", "it", "de", "es"]
    arabic: str | None = None
    meaning: str | None = None
    tags: tuple[str, ...]
    split: Literal["dev", "test"]
    note: str | None = None

    @field_validator("text")
    @classmethod
    def _check_text(cls, value: str) -> str:
        return check_text(value)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("at least one tag is required")
        unknown = sorted(set(value) - FRANCO_TAGS)
        if unknown:
            raise ValueError(f"unknown tag(s): {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("duplicate tags")
        return value

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        tags = set(self.tags)
        if self.label in ARABIC_LABELS:
            if self.arabic is None or not self.arabic.strip():
                raise ValueError(f"arabic is required for label {self.label}")
            if self.meaning is None or not self.meaning.strip():
                raise ValueError(f"meaning is required for label {self.label}")
            check_text(self.arabic)
            if not _ARABIC_LETTER.search(self.arabic):
                raise ValueError("arabic must contain Arabic letters")
            invented = sorted(set(metrics.latin_words(self.arabic)) - set(metrics.latin_words(self.text)))
            if invented:
                raise ValueError(f"arabic has Latin word(s) not in text: {', '.join(invented)}")
            if "control" in tags:
                raise ValueError("control tag is only for non-Arabic labels")
            if len(tags & {"numerals", "no_numerals"}) != 1:
                raise ValueError("ar/arz items need exactly one of numerals, no_numerals")
        else:
            if self.arabic is not None:
                raise ValueError("arabic must be absent for controls")
            if self.meaning is not None:
                raise ValueError("meaning must be absent for controls")
            if "control" not in tags:
                raise ValueError(f"label {self.label} needs the control tag")
            if tags & {"numerals", "no_numerals"}:
                raise ValueError("controls must not carry numerals or no_numerals")
        if "shared" in tags and self.label != "ar":
            raise ValueError("shared items must be labelled ar")
        return self


def load_franco(path: str | Path = DEFAULT_FRANCO_DATASET) -> list[FrancoItem]:
    """Load the Franco dataset with the shared loader (BOM, duplicates, file:line errors)."""
    return load_dataset(path, model=FrancoItem)


def franco_hash(items: Sequence[FrancoItem]) -> str:
    """sha256 of the parsed items as canonical JSON (notes excluded)."""
    payload = [item.model_dump(mode="json", exclude={"note"}) for item in items]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def detection_target(label: str) -> str:
    """Target for the detection pass: English, or French when the text is English."""
    return "fr" if label == "en" else "en"


def request_count(items: Iterable[FrancoItem], arabize: ArabizeMode = "script") -> int:
    """Real requests a run sends.

    ``script``: 2 per item (detect + script conversion, controls included).
    ``translate``: 2 per ar/arz item (detect + arabize), 1 per control.
    """
    if arabize == "script":
        return 2 * sum(1 for _ in items)
    return sum(2 if item.label in ARABIC_LABELS else 1 for item in items)


def script_prompt_fingerprint() -> str:
    """Short sha256 of the script system prompt, user template and JSON schema."""
    parts = (
        build_script_system_prompt(),
        build_script_user_message("{text}"),
        json.dumps(json_schema_for(ScriptOutput), sort_keys=True, ensure_ascii=False),
    )
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:12]


def same_text(output: str, text: str) -> bool:
    """True if ``output`` equals ``text`` after whitespace normalisation."""
    return " ".join(output.split()) == " ".join(text.split())


def select_franco(
    items: Sequence[FrancoItem], tag: str | None, split: str | None, limit: int | None
) -> list[FrancoItem]:
    """Filter by ``split`` and ``tag``, then keep the first ``limit`` items in file order."""
    in_split = [item for item in items if split is None or item.split == split]
    return select_items(in_split, tag, limit)  # type: ignore[arg-type]


# --- running -------------------------------------------------------------------------


class FrancoItemResult(BaseModel):
    """One item's raw outputs and scores. Raw outputs are kept so runs can be re-scored."""

    id: str
    text: str
    label: str
    tags: list[str]
    split: str
    arabic: str | None = None
    meaning: str | None = None
    # detection pass
    detect_target: str
    predicted: str | None
    outcome: Outcome
    translation: str | None = None
    detect_error_type: str | None = None
    detect_latency_ms: float | None = None
    # arabization pass (ar/arz items only)
    arabize_target: str | None = None
    arabic_output: str | None = None
    arabic_detected: str | None = None
    arabize_error_type: str | None = None
    arabize_latency_ms: float | None = None
    chrf: float | None = None
    latin_leak: bool | None = None
    # script pass on controls: output == input after whitespace normalisation
    control_unchanged: bool | None = None


class FrancoService(Protocol):
    async def translate(
        self, text: str, source_code: str, target_code: str
    ) -> TranslationResult: ...

    async def to_arabic_script(self, text: str) -> str: ...


class FrancoRunResult(BaseModel):
    items: list[FrancoItemResult]
    partial: bool = False
    stop_reason: str | None = None
    not_run: int = 0


def score_arabization(output: str, reference: str) -> tuple[float, bool]:
    """chrF on normalised text, and whether the output leaks Latin words."""
    chrf = metrics.chrf(metrics.normalize_arabic(output), metrics.normalize_arabic(reference))
    return round(chrf, 2), metrics.latin_leak(output, reference)


def build_item_result(
    item: FrancoItem,
    detect_target: str,
    detect: Attempt,
    arabize: Attempt | None,
    *,
    mode: ArabizeMode = "script",
) -> FrancoItemResult:
    """Score one item. ``arabize`` is the second pass (script or translate, per ``mode``).

    ar/arz outputs get chrF + Latin leak; a control's script output gets
    ``control_unchanged``. A failed pass keeps only its error type.
    """
    predicted = detect.response.detected_source.code if detect.response else None
    if detect.response is None:
        outcome: Outcome = "error"
    else:
        outcome = "correct" if predicted == item.label else "wrong"
    result = FrancoItemResult(
        id=item.id,
        text=item.text,
        label=item.label,
        tags=list(item.tags),
        split=item.split,
        arabic=item.arabic,
        meaning=item.meaning,
        detect_target=detect_target,
        predicted=predicted,
        outcome=outcome,
        translation=detect.response.translation if detect.response else None,
        detect_error_type=detect.error_type,
        detect_latency_ms=detect.latency_ms,
    )
    if arabize is None:
        return result
    update: dict[str, Any] = {
        "arabize_target": SCRIPT_TARGET if mode == "script" else item.label,
        "arabize_error_type": arabize.error_type,
        "arabize_latency_ms": arabize.latency_ms,
    }
    response = arabize.response
    if response is None:
        return result.model_copy(update=update)
    if isinstance(response, str):
        output, detected = response, None
    else:
        output, detected = response.translation, response.detected_source.code
    update |= {"arabic_output": output, "arabic_detected": detected}
    if item.arabic is not None:
        chrf, leak = score_arabization(output, item.arabic)
        update |= {"chrf": chrf, "latin_leak": leak}
    else:
        update["control_unchanged"] = same_text(output, item.text)
    return result.model_copy(update=update)


async def run_franco(
    service: FrancoService,
    items: Sequence[FrancoItem],
    *,
    arabize: ArabizeMode = "script",
    delay: float = 4.0,
    retry_wait: float = 60.0,
    max_retries: int = MAX_RETRIES,
    sleep: Sleep = asyncio.sleep,
    clock: Callable[[], float] = time.perf_counter,
    on_item: Callable[[int, FrancoItemResult], None] | None = None,
) -> FrancoRunResult:
    """Run the detection pass and the arabization pass item by item.

    ``arabize="script"`` sends ``to_arabic_script`` for every item (controls included);
    ``arabize="translate"`` sends ``translate(text, auto, label)`` for ar/arz items only.

    ``delay`` is slept before every request except the first. Rate limits are retried
    by ``retry_request``. If they persist, the run stops: the unfinished item is
    dropped and counted in ``not_run`` with the rest. An auth error raises
    ``EvalAborted``. Other provider errors are recorded per pass (type name only).
    """
    results: list[FrancoItemResult] = []
    sent_any = False

    async def call(request: Callable[[], Any]) -> Attempt:
        nonlocal sent_any
        if sent_any:
            await sleep(delay)
        sent_any = True
        return await retry_request(
            request, retry_wait=retry_wait, max_retries=max_retries, sleep=sleep, clock=clock
        )

    # Each lambda is awaited (and retried) before the loop moves on, so closing over the
    # loop variables is safe.
    for index, item in enumerate(items):
        target = detection_target(item.label)
        try:
            detect = await call(lambda: service.translate(item.text, AUTO, target))
            second: Attempt | None = None
            if arabize == "script":
                second = await call(lambda: service.to_arabic_script(item.text))
            elif item.label in ARABIC_LABELS:
                second = await call(lambda: service.translate(item.text, AUTO, item.label))
        except RateLimitExhausted:
            return FrancoRunResult(
                items=results, partial=True, stop_reason="rate_limit", not_run=len(items) - index
            )
        result = build_item_result(item, target, detect, second, mode=arabize)
        results.append(result)
        if on_item is not None:
            on_item(index, result)
    return FrancoRunResult(items=results)


# --- summary ---------------------------------------------------------------------------


def _rate(k: int, n: int) -> float | None:
    return k / n if n else None


def group_stats(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Detection and arabization numbers for a group of item rows.

    The arabization numbers (mean chrF, leak rate) cover successful outputs only.
    Errors are counted separately and are never scored as chrF 0.
    """
    correct = sum(1 for r in rows if r["outcome"] == "correct")
    arabic_rows = [r for r in rows if r["label"] in ARABIC_LABELS]
    scored = [r for r in arabic_rows if r["arabic_output"] is not None]
    leaks = sum(1 for r in scored if r["latin_leak"])
    return {
        "n": len(rows),
        "correct": correct,
        "accuracy": metrics.accuracy(correct, len(rows)),
        "arabize_n": len(arabic_rows),
        "arabize_scored": len(scored),
        "arabize_errors": len(arabic_rows) - len(scored),
        "mean_chrf": metrics.mean(r["chrf"] for r in scored),
        "latin_leaks": leaks,
        "latin_leak_rate": _rate(leaks, len(scored)),
    }


def summarize_franco(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """All metrics, recomputed from item rows only (so saved runs can be re-summarised)."""
    attempted = len(rows)
    correct = sum(1 for r in rows if r["outcome"] == "correct")
    errors = sum(1 for r in rows if r["outcome"] == "error")
    lo, hi = metrics.wilson_interval(correct, attempted)
    present = {r["label"] for r in rows}
    labels = [label for label in FRANCO_LABELS if label in present]
    cm = metrics.confusion_matrix(((r["label"], r["predicted"]) for r in rows), labels, CM_COLUMNS)

    controls = [r for r in rows if r["label"] not in ARABIC_LABELS]
    false_pos = sum(1 for r in controls if r["predicted"] in ARABIC_LABELS)
    fp_lo, fp_hi = metrics.wilson_interval(false_pos, len(controls))
    # Script pass on controls (absent in translate runs and in older reports).
    script_controls = [r for r in controls if r.get("arabize_target") == SCRIPT_TARGET]
    converted = [r for r in script_controls if r["arabic_output"] is not None]
    unchanged = sum(1 for r in converted if r.get("control_unchanged"))

    arabize = group_stats(rows)
    per_tag = {
        tag: group_stats([r for r in rows if tag in r["tags"]])
        for tag in sorted({t for r in rows for t in r["tags"]})
    }
    per_split = {
        split: group_stats([r for r in rows if r["split"] == split])
        for split in SPLITS
        if any(r["split"] == split for r in rows)
    }
    return {
        "attempted": attempted,
        "correct": correct,
        "wrong": attempted - correct - errors,
        "errors": errors,
        "accuracy": metrics.accuracy(correct, attempted),
        "accuracy_ci95": [lo, hi],
        "confusion_matrix": cm,
        "control_false_positives": {
            "n": len(controls),
            "false_positives": false_pos,
            "rate": _rate(false_pos, len(controls)),
            "rate_ci95": [fp_lo, fp_hi],
        },
        "controls_unchanged": {
            "n": len(script_controls),
            "scored": len(converted),
            "errors": len(script_controls) - len(converted),
            "unchanged": unchanged,
            "rate": _rate(unchanged, len(converted)),
        },
        "arabization": {
            "n": arabize["arabize_n"],
            "scored": arabize["arabize_scored"],
            "errors": arabize["arabize_errors"],
            "mean_chrf": arabize["mean_chrf"],
            "latin_leaks": arabize["latin_leaks"],
            "latin_leak_rate": arabize["latin_leak_rate"],
        },
        "per_tag": per_tag,
        "per_split": per_split,
        "median_latency_ms": {
            "detect": metrics.median_latency(r["detect_latency_ms"] for r in rows),
            "arabize": metrics.median_latency(r["arabize_latency_ms"] for r in rows),
        },
    }


# --- reports ---------------------------------------------------------------------------


def build_report(run: FrancoRunResult, meta: Mapping[str, Any]) -> dict[str, Any]:
    rows = [item.model_dump() for item in run.items]
    summary = summarize_franco(rows)
    summary["not_run"] = run.not_run
    full_meta = {**meta, "partial": run.partial, "stop_reason": run.stop_reason, "not_run": run.not_run}
    return {"meta": full_meta, "summary": summary, "items": rows}


def load_franco_baseline(path: Path) -> dict[str, Any]:
    data = load_baseline(path)
    if data["meta"].get("eval") != "franco":
        raise EvalAborted(f"Baseline {display_path(path)} is not a franco result JSON.")
    return data


def diff_franco_baseline(
    report: Mapping[str, Any], baseline: Mapping[str, Any], baseline_path: str = ""
) -> dict[str, Any]:
    """Detection fixed/broken (via the dialect diff) plus arabization changes.

    Arabization: path, mean chrF and leaks before -> after, overall and per split/tag,
    ids with new or fixed leaks, and whether the script prompt is new or changed.
    """
    diff = diff_baseline(report, baseline, baseline_path)
    current = {i["id"]: i["latin_leak"] for i in report["items"] if i["latin_leak"] is not None}
    previous = {i["id"]: i["latin_leak"] for i in baseline["items"] if i.get("latin_leak") is not None}
    common = current.keys() & previous.keys()
    before = baseline["summary"].get("arabization", {})
    meta, base_meta = report["meta"], baseline["meta"]
    diff |= {
        "baseline_arabize": base_meta.get("arabize", "translate"),
        "baseline_mean_chrf": before.get("mean_chrf"),
        "baseline_latin_leak_rate": before.get("latin_leak_rate"),
        "baseline_latin_leaks": before.get("latin_leaks"),
        "baseline_arabize_scored": before.get("scored"),
        "new_leaks": sorted(i for i in common if current[i] and not previous[i]),
        "fixed_leaks": sorted(i for i in common if previous[i] and not current[i]),
        "script_prompt": _script_prompt_status(
            meta.get("script_prompt_fingerprint"), base_meta.get("script_prompt_fingerprint")
        ),
        "groups": {
            "split": _group_changes(report["summary"]["per_split"], baseline["summary"].get("per_split", {})),
            "tag": _group_changes(report["summary"]["per_tag"], baseline["summary"].get("per_tag", {})),
        },
    }
    return diff


def _script_prompt_status(current: str | None, previous: str | None) -> str:
    if current is None:
        return "n/a"
    if previous is None:
        return "new"
    return "same" if current == previous else "changed"


def _group_changes(
    now: Mapping[str, Mapping[str, Any]], then: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Mean chrF and leak counts before -> after for groups with ar/arz items on either side."""
    changes = {}
    for name in sorted(now.keys() | then.keys()):
        after, before = now.get(name, {}), then.get(name, {})
        if not after.get("arabize_n") and not before.get("arabize_n"):
            continue
        changes[name] = {
            "chrf_before": before.get("mean_chrf"),
            "chrf_after": after.get("mean_chrf"),
            "leaks_before": before.get("latin_leaks"),
            "leaks_after": after.get("latin_leaks"),
            "scored_before": before.get("arabize_scored"),
            "scored_after": after.get("arabize_scored"),
        }
    return changes


def _num(value: float | None, fmt: str = ".1f") -> str:
    return "n/a" if value is None else format(value, fmt)


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.0f} ms"


def _group_table(title: str, groups: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
        "| Group | n | Detection | Arabized (ok / errors) | Mean chrF | Latin leak |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, g in groups.items():
        lines.append(
            f"| {name} | {g['n']} | {_pct(g['accuracy'])} ({g['correct']}/{g['n']}) | "
            f"{g['arabize_scored']} / {g['arabize_errors']} | {_num(g['mean_chrf'])} | "
            f"{_pct(g['latin_leak_rate'])} |"
        )
    return lines


def render_markdown(report: Mapping[str, Any]) -> str:
    meta, summary = report["meta"], report["summary"]
    lo, hi = summary["accuracy_ci95"]
    filters = meta["filters"]
    latency = summary["median_latency_ms"]
    fp = summary["control_false_positives"]
    arb = summary["arabization"]
    unchanged = summary["controls_unchanged"]
    mode = meta.get("arabize", "translate")
    script_mode = mode == "script"
    fingerprints = ", ".join(f"{k} `{v}`" for k, v in meta["prompt_fingerprint"].items())
    if meta.get("script_prompt_fingerprint"):
        fingerprints += f", script `{meta['script_prompt_fingerprint']}`"
    lines = [f"# Franco-Arabic eval ({meta['created_utc']})", ""]
    if meta["partial"]:
        lines += [
            f"> **Partial run** (stop reason: `{meta['stop_reason']}`): "
            f"{meta['not_run']} item(s) were not finished.",
            "",
        ]
    lines += [
        "## Run",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Provider | {meta['provider']} |",
        f"| Model | `{meta['model']}` |",
        "| Detection target | en (fr for en items) |",
        f"| Arabization path | `{mode}`: {ARABIZE_DESCRIPTIONS[mode]} |",
        f"| Prompt fingerprints | {fingerprints} |",
        f"| Git commit | `{meta['git_commit']}` |",
        f"| Dataset | `{meta['dataset']['path']}` ({meta['dataset']['size']} items) |",
        f"| Dataset sha256 | `{meta['dataset']['sha256'][:16]}` |",
        f"| Filters | tag={filters['tag'] or '-'}, split={filters['split'] or '-'}, "
        f"limit={filters['limit'] or '-'} |",
        f"| Items attempted / not run | {summary['attempted']} / {summary['not_run']} |",
        f"| Requests planned | {meta['requests_planned']} |",
        f"| Median latency | detect {_ms(latency['detect'])}, arabize {_ms(latency['arabize'])} |",
        "",
        "## Detection",
        "",
        f"**{_pct(summary['accuracy'])}** ({summary['correct']}/{summary['attempted']}), "
        f"95% Wilson CI {_pct(lo)} to {_pct(hi)}. "
        f"Wrong: {summary['wrong']}, errors: {summary['errors']}.",
        "",
        f"Control false positives (control detected as ar/arz): {fp['false_positives']}/{fp['n']}"
        f" = {_pct(fp['rate'])}, 95% Wilson CI {_pct(fp['rate_ci95'][0])} to "
        f"{_pct(fp['rate_ci95'][1])}.",
        "",
        "## Confusion matrix",
        "",
        "| label \\ predicted | " + " | ".join(CM_COLUMNS) + " |",
        "|---|" + "---:|" * len(CM_COLUMNS),
    ]
    for label, row in summary["confusion_matrix"].items():
        lines.append(f"| **{label}** | " + " | ".join(str(row[c]) for c in CM_COLUMNS) + " |")
    lines += [
        "",
        "## Arabization",
        "",
        f"Mean chrF **{_num(arb['mean_chrf'])}** over {arb['scored']} successful output(s); "
        f"Latin leak {arb['latin_leaks']}/{arb['scored']} = {_pct(arb['latin_leak_rate'])}. "
        f"Errors (not scored): {arb['errors']}.",
    ]
    if unchanged["n"]:
        lines += [
            "",
            "Controls unchanged (script output == input after whitespace normalisation): "
            f"**{unchanged['unchanged']}/{unchanged['scored']}** = {_pct(unchanged['rate'])}. "
            f"Errors: {unchanged['errors']}.",
        ]
    lines += _group_table("Per split", summary["per_split"])
    lines += _group_table("Per tag", summary["per_tag"])

    misses = [i for i in report["items"] if i["outcome"] != "correct"]
    lines += ["", f"## Wrong and error detections ({len(misses)})", ""]
    if misses:
        lines += ["| id | split | label -> predicted | text |", "|---|---|---|---|"]
        for item in misses:
            predicted = item["predicted"] or f"error ({item['detect_error_type']})"
            lines.append(
                f"| {item['id']} | {item['split']} | {item['label']} -> {predicted} | "
                f"{_cell(item['text'])} |"
            )
    else:
        lines.append("None.")

    arabic_items = [i for i in report["items"] if i["label"] in ARABIC_LABELS]
    lines += [
        "",
        f"## Review: ar/arz items ({len(arabic_items)})",
        "",
        (
            "`arabized output` is the `to_arabic_script` output. "
            if script_mode
            else "`arabized output` is the `auto -> label` output (ar items go to ar). "
        )
        + "A `*` after chrF marks a Latin leak.",
        "",
        "| id | text | arabic ref | arabized output | chrF | en output | meaning |",
        "|---|---|---|---|---:|---|---|",
    ]
    for item in arabic_items:
        if item["arabic_output"] is not None:
            output = _cell(item["arabic_output"])
            score = _num(item["chrf"]) + (" *" if item["latin_leak"] else "")
        else:
            output = f"error ({item['arabize_error_type']})"
            score = "n/a"
        en_output = (
            _cell(item["translation"]) if item["translation"] is not None
            else f"error ({item['detect_error_type']})"
        )
        lines.append(
            f"| {item['id']} | {_cell(item['text'])} | {_cell(item['arabic'] or '')} | "
            f"{output} | {score} | {en_output} | {_cell(item['meaning'] or '')} |"
        )

    controls = [i for i in report["items"] if i["label"] not in ARABIC_LABELS]
    lines += [
        "",
        f"## Review: controls ({len(controls)})",
        "",
        "| id | text | label -> predicted | output |"
        + (" script output | unchanged |" if script_mode else ""),
        "|---|---|---|---|" + ("---|---|" if script_mode else ""),
    ]
    for item in controls:
        predicted = item["predicted"] or f"error ({item['detect_error_type']})"
        row = (
            f"| {item['id']} | {_cell(item['text'])} | {item['label']} -> {predicted} | "
            f"{_cell(item['translation'] or '')} |"
        )
        if script_mode:
            if item["arabic_output"] is None:
                row += f" error ({item['arabize_error_type']}) | n/a |"
            else:
                same = "yes" if item.get("control_unchanged") else "**no**"
                row += f" {_cell(item['arabic_output'])} | {same} |"
        lines.append(row)

    diff = report.get("baseline")
    if diff is not None:
        lines += ["", "## Baseline comparison", "", f"Baseline: `{diff['path']}`", ""]
        if diff["dataset_hash_changed"]:
            lines += [
                "> **Warning:** the dataset hash differs from the baseline's; the numbers "
                "are not directly comparable.",
                "",
            ]
        lines += [
            f"- Detection accuracy: {_pct(diff['baseline_accuracy'])} "
            f"({diff['baseline_attempted']} attempted) -> {_pct(summary['accuracy'])} "
            f"({summary['attempted']} attempted)",
            f"- Arabization path: {diff['baseline_arabize']} -> {mode}",
            f"- Mean chrF: {_num(diff['baseline_mean_chrf'])} -> {_num(arb['mean_chrf'])}",
            "- Latin leaks: "
            f"{_count(diff['baseline_latin_leaks'], diff['baseline_arabize_scored'])}"
            f" ({_pct(diff['baseline_latin_leak_rate'])}) -> "
            f"{arb['latin_leaks']}/{arb['scored']} ({_pct(arb['latin_leak_rate'])})",
            f"- Translation prompts changed: {'yes' if diff['prompt_changed'] else 'no'}",
            f"- Script prompt: {diff['script_prompt']}",
            f"- Detection fixed ({len(diff['fixed'])}): {_ids(diff['fixed'])}",
            f"- Detection broken ({len(diff['broken'])}): {_ids(diff['broken'])}",
            f"- New Latin leaks ({len(diff['new_leaks'])}): {_ids(diff['new_leaks'])}",
            f"- Fixed Latin leaks ({len(diff['fixed_leaks'])}): {_ids(diff['fixed_leaks'])}",
            f"- Only in this run: {_ids(diff['only_in_current'])}",
            f"- Only in baseline: {_ids(diff['only_in_baseline'])}",
        ]
        lines += _change_table("Mean chrF and Latin leaks by split", diff["groups"]["split"])
        lines += _change_table("Mean chrF and Latin leaks by tag", diff["groups"]["tag"])
    return "\n".join(lines) + "\n"


def _count(k: int | None, n: int | None) -> str:
    return "n/a" if k is None or n is None else f"{k}/{n}"


def _delta(before: float | None, after: float | None) -> str:
    return "n/a" if before is None or after is None else f"{after - before:+.1f}"


def _change_table(title: str, changes: Mapping[str, Mapping[str, Any]]) -> list[str]:
    lines = [
        "",
        f"### {title}",
        "",
        "| Group | chrF before | chrF after | change | leaks before | leaks after |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, c in changes.items():
        lines.append(
            f"| {name} | {_num(c['chrf_before'])} | {_num(c['chrf_after'])} | "
            f"{_delta(c['chrf_before'], c['chrf_after'])} | "
            f"{_count(c['leaks_before'], c['scored_before'])} | "
            f"{_count(c['leaks_after'], c['scored_after'])} |"
        )
    return lines


# --- console ---------------------------------------------------------------------------


def progress_line(index: int, total: int, result: FrancoItemResult) -> str:
    shown = result.predicted or f"error:{result.detect_error_type}"
    line = f"[{index + 1}/{total}] {result.id} {result.label} -> {shown} {result.outcome.upper()}"
    if result.arabize_target is not None:
        if result.arabic_output is None:
            line += f" | to:{result.arabize_target} error:{result.arabize_error_type}"
        elif result.chrf is None:  # control, script pass
            same = "yes" if result.control_unchanged else "no"
            line += f" | to:{result.arabize_target} unchanged={same}"
        else:
            leak = "yes" if result.latin_leak else "no"
            line += f" | to:{result.arabize_target} chrF {result.chrf:.1f} leak={leak}"
    return line


def console_summary(report: Mapping[str, Any]) -> list[str]:
    summary = report["summary"]
    lo, hi = summary["accuracy_ci95"]
    fp = summary["control_false_positives"]
    arb = summary["arabization"]
    latency = summary["median_latency_ms"]
    lines = [
        f"Detection: {summary['correct']}/{summary['attempted']} = {_pct(summary['accuracy'])} "
        f"(95% CI {_pct(lo)} - {_pct(hi)}), errors: {summary['errors']}",
        f"Control false positives: {fp['false_positives']}/{fp['n']} = {_pct(fp['rate'])}",
        f"Arabization ({report['meta'].get('arabize', 'translate')}): "
        f"mean chrF {_num(arb['mean_chrf'])} over {arb['scored']} | "
        f"Latin leak {arb['latin_leaks']}/{arb['scored']} = {_pct(arb['latin_leak_rate'])} | "
        f"errors: {arb['errors']}",
    ]
    unchanged = summary["controls_unchanged"]
    if unchanged["n"]:
        lines.append(
            f"Controls unchanged: {unchanged['unchanged']}/{unchanged['scored']} = "
            f"{_pct(unchanged['rate'])} | errors: {unchanged['errors']}"
        )
    for split, g in summary["per_split"].items():
        lines.append(
            f"  {split:<5} n={g['n']:<3} detection {_pct(g['accuracy'])} | "
            f"chrF {_num(g['mean_chrf'])} | leak {_pct(g['latin_leak_rate'])}"
        )
    lines.append(
        f"Not run: {summary['not_run']} | median latency: detect {_ms(latency['detect'])}, "
        f"arabize {_ms(latency['arabize'])}"
    )
    diff = report.get("baseline")
    if diff is not None:
        warning = " (WARNING: dataset hash differs)" if diff["dataset_hash_changed"] else ""
        splits = ", ".join(
            f"{name} {_num(c['chrf_before'])} -> {_num(c['chrf_after'])}"
            for name, c in diff["groups"]["split"].items()
        )
        lines.append(
            f"Baseline ({diff['baseline_arabize']} -> {report['meta'].get('arabize', 'translate')}): "
            f"{len(diff['fixed'])} fixed, {len(diff['broken'])} broken, "
            f"chrF {_num(diff['baseline_mean_chrf'])} -> {_num(arb['mean_chrf'])}"
            + (f" ({splits})" if splits else "")
            + f", leaks {_count(diff['baseline_latin_leaks'], diff['baseline_arabize_scored'])}"
            f" -> {arb['latin_leaks']}/{arb['scored']}, "
            f"{len(diff['new_leaks'])} new leak(s){warning}"
        )
    return lines


# --- CLI -------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.franco",
        description=(
            "Measure Franco-Arabic (Arabizi) detection and arabization via the real app path."
        ),
    )
    parser.add_argument("--limit", type=_positive_int,
                        help="only the first N items (after --tag and --split)")
    parser.add_argument("--tag", choices=sorted(FRANCO_TAGS), help="only items with this tag")
    parser.add_argument("--split", choices=SPLITS, help="only items in this split")
    parser.add_argument("--model", help="override the active provider's model")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_FRANCO_DATASET,
                        help="dataset JSONL path")
    parser.add_argument("--baseline", type=Path, help="earlier franco result JSON to compare against")
    parser.add_argument("--delay", type=_non_negative_float, default=4.0,
                        help="seconds between requests (default: 4)")
    parser.add_argument("--retry-wait", type=_non_negative_float, default=60.0,
                        help="seconds to wait after a rate limit before retrying (default: 60)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="report directory (default: evals/results)")
    parser.add_argument("--arabize", choices=ARABIZE_MODES, default="script",
                        help="arabization path: script (to_arabic_script, every item; default) "
                        "or translate (the baseline path: auto -> item label, ar/arz only)")
    parser.add_argument("--yes", action="store_true",
                        help=f"skip the confirmation for more than {CONFIRM_THRESHOLD} requests")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    sleep: Sleep = asyncio.sleep,
    input_fn: Callable[[str], str] = input,
) -> int:
    """CLI entry point. Exit codes: 0 complete, 1 aborted, 2 partial (rate limit)."""
    args = build_parser().parse_args(argv)

    try:
        all_items = load_franco(args.dataset)
        baseline = load_franco_baseline(args.baseline) if args.baseline else None
    except (DatasetError, EvalAborted, OSError) as exc:
        say(f"Error: {exc}")
        return 1

    selected = select_franco(all_items, args.tag, args.split, args.limit)
    if not selected:
        say("No dataset items match the given filters.")
        return 1

    try:
        settings = Settings()
    except ValidationError as exc:
        messages = "; ".join(err["msg"] for err in exc.errors(include_input=False))
        say(f"Configuration error: {messages}")
        return 1
    if args.model:
        settings = settings.model_copy(update={f"{settings.provider}_model": args.model})

    requests = request_count(selected, args.arabize)
    if requests > CONFIRM_THRESHOLD and not args.yes:
        if not _confirm(requests, args.delay, input_fn):
            say("Aborted: nothing was sent.")
            return 1

    service = TranslationService(build_provider(settings), settings.max_chars)
    created = datetime.now(UTC)
    total = len(selected)

    say(
        f"Running {total} item(s), {requests} request(s) on "
        f"{settings.provider}/{settings.active_model} (arabize: {args.arabize})"
    )
    try:
        run = asyncio.run(
            run_franco(
                service, selected,
                arabize=args.arabize, delay=args.delay, retry_wait=args.retry_wait, sleep=sleep,
                on_item=lambda index, result: say(progress_line(index, total, result)),
            )
        )
    except EvalAborted as exc:
        say(f"Aborted: {exc}")
        return 1

    meta = {
        "eval": "franco",
        "created_utc": created.isoformat(timespec="seconds"),
        "dataset": {
            "path": display_path(args.dataset),
            "sha256": franco_hash(all_items),
            "size": len(all_items),
        },
        "provider": settings.provider,
        "model": settings.active_model,
        "arabize": args.arabize,
        "targets": {"detect": "en (fr for en items)", "arabize": ARABIZE_DESCRIPTIONS[args.arabize]},
        "prompt_fingerprint": {t: prompt_fingerprint(t) for t in FINGERPRINT_TARGETS},
        "script_prompt_fingerprint": (
            script_prompt_fingerprint() if args.arabize == "script" else None
        ),
        "git_commit": git_commit(),
        "filters": {"tag": args.tag, "split": args.split, "limit": args.limit},
        "selected": total,
        "requests_planned": requests,
    }
    report = build_report(run, meta)
    if baseline is not None:
        report["baseline"] = diff_franco_baseline(report, baseline, display_path(args.baseline))
    basename = report_basename(created, settings.provider, settings.active_model, prefix="franco")
    json_path, md_path = write_reports(report, render_markdown(report), args.out_dir, basename)

    say()
    for line in console_summary(report):
        say(line)
    if run.partial:
        say(QUOTA_MESSAGE.format(retries=MAX_RETRIES))
    say(f"JSON: {display_path(json_path)}")
    say(f"MD:   {display_path(md_path)}")
    return 2 if run.partial else 0


if __name__ == "__main__":
    sys.exit(main())
