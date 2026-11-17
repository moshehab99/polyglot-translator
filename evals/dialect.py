"""Dialect-detection eval: MSA (ar) vs Egyptian Arabic (arz).

Sends every dataset item through the real app path
(``Settings -> build_provider -> TranslationService.translate(text, "auto", target)``)
and writes a JSON + Markdown report. Run with::

    uv run python -m evals.dialect --help

Only ``main`` builds the real provider; ``run_eval`` takes the service as a parameter
so tests inject a fake. Console output is ASCII only; Arabic goes in the report files.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import itertools
import json
import re
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.languages import AUTO, LANGUAGE_CODES, get_language
from app.providers.base import (
    ProviderAuthError,
    ProviderError,
    ProviderRateLimitError,
    TranslationResult,
)
from app.providers.factory import build_provider
from app.providers.prompts import build_system_prompt, build_user_message
from app.providers.schemas import translation_json_schema
from app.services.translation_service import TranslationService
from evals import metrics
from evals.dataset import DEFAULT_DATASET, TAGS, DatasetError, EvalItem, dataset_hash, load_dataset

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT_DIR = Path(__file__).parent / "results"
ARABIC_CODES = frozenset({"ar", "arz"})
TARGET_CHOICES = tuple(code for code in LANGUAGE_CODES if code not in ARABIC_CODES)
CONFIRM_THRESHOLD = 10
MAX_RETRIES = 2
QUOTA_MESSAGE = (
    "Stopped: rate limit persisted after {retries} retries. The free-tier daily quota "
    "probably ran out; it resets at midnight Pacific time."
)

Outcome = Literal["correct", "wrong", "error"]
Sleep = Callable[[float], Awaitable[None]]


class Translator(Protocol):
    async def translate(
        self, text: str, source_code: str, target_code: str
    ) -> TranslationResult: ...


class EvalAborted(Exception):
    """The run cannot continue (e.g. authentication failed). Message is console-safe."""


class ItemResult(BaseModel):
    id: str
    text: str
    label: str
    predicted: str | None
    outcome: Outcome
    tags: list[str]
    translation: str | None = None
    error_type: str | None = None
    latency_ms: float | None = None


class RunResult(BaseModel):
    items: list[ItemResult]
    partial: bool = False
    stop_reason: str | None = None
    not_run: int = 0


# --- running -------------------------------------------------------------------------


def select_items(items: Sequence[EvalItem], tag: str | None, limit: int | None) -> list[EvalItem]:
    """Filter by ``tag`` first, then keep the first ``limit`` items in file order."""
    selected = [item for item in items if tag is None or tag in item.tags]
    return selected if limit is None else selected[:limit]


async def run_eval(
    service: Translator,
    items: Sequence[EvalItem],
    target: str,
    *,
    delay: float = 4.0,
    retry_wait: float = 60.0,
    max_retries: int = MAX_RETRIES,
    sleep: Sleep = asyncio.sleep,
    clock: Callable[[], float] = time.perf_counter,
    on_item: Callable[[int, ItemResult], None] | None = None,
) -> RunResult:
    """Translate items one by one from ``auto`` and record the detected source.

    - ``ProviderRateLimitError``: wait ``retry_wait`` and retry the same item, at most
      ``max_retries`` times; then stop and return a partial result.
    - ``ProviderAuthError``: raise ``EvalAborted``.
    - Other ``ProviderError``: record an ``error`` outcome (type name only) and go on.
    - Anything else propagates.
    """
    results: list[ItemResult] = []
    for index, item in enumerate(items):
        if index:
            await sleep(delay)
        retries = 0
        while True:
            start = clock()
            try:
                response = await service.translate(item.text, AUTO, target)
            except ProviderRateLimitError:
                if retries >= max_retries:
                    return RunResult(
                        items=results,
                        partial=True,
                        stop_reason="rate_limit",
                        not_run=len(items) - index,
                    )
                retries += 1
                await sleep(retry_wait)
                continue
            except ProviderAuthError:
                raise EvalAborted(
                    "Authentication with the provider failed. Check the API key for the "
                    "active provider in .env."
                ) from None
            except ProviderError as exc:
                result = ItemResult(
                    id=item.id,
                    text=item.text,
                    label=item.label,
                    predicted=None,
                    outcome="error",
                    tags=list(item.tags),
                    error_type=type(exc).__name__,
                )
                break
            latency_ms = round((clock() - start) * 1000, 1)
            predicted = response.detected_source.code
            result = ItemResult(
                id=item.id,
                text=item.text,
                label=item.label,
                predicted=predicted,
                outcome="correct" if predicted == item.label else "wrong",
                tags=list(item.tags),
                translation=response.translation,
                latency_ms=latency_ms,
            )
            break
        results.append(result)
        if on_item is not None:
            on_item(index, result)
    return RunResult(items=results)


# --- run metadata -------------------------------------------------------------------


def prompt_fingerprint(target: str) -> str:
    """Short sha256 of the auto-detect system prompt, user template and JSON schema."""
    lang = get_language(target)
    parts = (
        build_system_prompt(None, lang),
        build_user_message("{text}", None, lang),
        json.dumps(translation_json_schema(), sort_keys=True, ensure_ascii=False),
    )
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()[:12]


def git_commit() -> str | None:
    """Short HEAD hash, with ``-dirty`` if tracked files changed; None without git."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{head}-dirty" if status else head


def sanitize(value: str) -> str:
    """Make ``value`` safe for a file name on every OS (no ':' or path separators)."""
    return re.sub(r"[^A-Za-z0-9._-]", "-", value).strip(".-") or "unknown"


def report_basename(created: datetime, provider: str, model: str) -> str:
    stamp = created.astimezone(UTC).strftime("%Y%m%d-%H%M%S")
    return f"dialect_{stamp}_{sanitize(provider)}_{sanitize(model)}"


def display_path(path: Path) -> str:
    """Path relative to the repo root when possible, always with forward slashes."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


# --- reports ----------------------------------------------------------------------


def build_report(run: RunResult, meta: Mapping[str, Any]) -> dict[str, Any]:
    rows = [item.model_dump() for item in run.items]
    summary = metrics.summarize(rows)
    summary["not_run"] = run.not_run
    full_meta = {
        **meta,
        "partial": run.partial,
        "stop_reason": run.stop_reason,
        "not_run": run.not_run,
    }
    return {"meta": full_meta, "summary": summary, "items": rows}


def load_baseline(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise EvalAborted(f"Cannot read baseline {display_path(path)}: {type(exc).__name__}") from None
    if not isinstance(data, dict) or not {"meta", "summary", "items"} <= data.keys():
        raise EvalAborted(f"Baseline {display_path(path)} is not a dialect result JSON.")
    return data


def diff_baseline(
    report: Mapping[str, Any], baseline: Mapping[str, Any], baseline_path: str = ""
) -> dict[str, Any]:
    """Compare per-item correctness by id with an earlier result."""
    current = {i["id"]: i["outcome"] == "correct" for i in report["items"]}
    previous = {i["id"]: i["outcome"] == "correct" for i in baseline["items"]}
    common = current.keys() & previous.keys()
    return {
        "path": baseline_path,
        "baseline_accuracy": baseline["summary"].get("accuracy"),
        "baseline_attempted": baseline["summary"].get("attempted"),
        "fixed": sorted(i for i in common if current[i] and not previous[i]),
        "broken": sorted(i for i in common if previous[i] and not current[i]),
        "only_in_current": sorted(current.keys() - previous.keys()),
        "only_in_baseline": sorted(previous.keys() - current.keys()),
        "dataset_hash_changed": (
            report["meta"]["dataset"]["sha256"] != baseline["meta"]["dataset"]["sha256"]
        ),
        "prompt_changed": (
            report["meta"]["prompt_fingerprint"] != baseline["meta"].get("prompt_fingerprint")
        ),
    }


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _ids(ids: Sequence[str]) -> str:
    return ", ".join(ids) if ids else "none"


def render_markdown(report: Mapping[str, Any]) -> str:
    meta, summary = report["meta"], report["summary"]
    lo, hi = summary["accuracy_ci95"]
    filters = meta["filters"]
    latency = summary["median_latency_ms"]
    lines = [f"# Dialect detection eval ({meta['created_utc']})", ""]
    if meta["partial"]:
        lines += [
            f"> **Partial run** (stop reason: `{meta['stop_reason']}`): "
            f"{meta['not_run']} item(s) were not sent.",
            "",
        ]
    lines += [
        "## Run",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Provider | {meta['provider']} |",
        f"| Model | `{meta['model']}` |",
        f"| Target | {meta['target']} |",
        f"| Prompt fingerprint | `{meta['prompt_fingerprint']}` |",
        f"| Git commit | `{meta['git_commit']}` |",
        f"| Dataset | `{meta['dataset']['path']}` ({meta['dataset']['size']} items) |",
        f"| Dataset sha256 | `{meta['dataset']['sha256'][:16]}` |",
        f"| Filters | tag={filters['tag'] or '-'}, limit={filters['limit'] or '-'} |",
        f"| Attempted / not run | {summary['attempted']} / {summary['not_run']} |",
        f"| Median latency | {'n/a' if latency is None else f'{latency:.0f} ms'} |",
        "",
        "## Accuracy",
        "",
        f"**{_pct(summary['accuracy'])}** ({summary['correct']}/{summary['attempted']}), "
        f"95% Wilson CI {_pct(lo)} to {_pct(hi)}. "
        f"Wrong: {summary['wrong']}, errors: {summary['errors']}.",
        "",
        "## Confusion matrix",
        "",
        "| label \\ predicted | " + " | ".join(metrics.COLUMNS) + " |",
        "|---|" + "---:|" * len(metrics.COLUMNS),
    ]
    for label, row in summary["confusion_matrix"].items():
        lines.append(f"| **{label}** | " + " | ".join(str(row[c]) for c in metrics.COLUMNS) + " |")
    lines += [
        "",
        "## Per label",
        "",
        "| Label | Precision | Recall | F1 | Support |",
        "|---|---:|---:|---:|---:|",
    ]
    for label, prf in summary["per_label"].items():
        lines.append(
            f"| {label} | {_pct(prf['precision'])} | {_pct(prf['recall'])} | "
            f"{_pct(prf['f1'])} | {prf['support']} |"
        )
    lines += ["", "## Per tag", "", "| Tag | n | Correct | Accuracy |", "|---|---:|---:|---:|"]
    for tag, stats in summary["per_tag"].items():
        lines.append(f"| {tag} | {stats['n']} | {stats['correct']} | {_pct(stats['accuracy'])} |")

    misses = [i for i in report["items"] if i["outcome"] != "correct"]
    lines += ["", f"## Wrong and error items ({len(misses)})", ""]
    if misses:
        lines += ["| id | label -> predicted | text |", "|---|---|---|"]
        for item in misses:
            predicted = item["predicted"] or f"error ({item['error_type']})"
            lines.append(f"| {item['id']} | {item['label']} -> {predicted} | {_cell(item['text'])} |")
    else:
        lines.append("None.")

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
            f"- Accuracy: {_pct(diff['baseline_accuracy'])} "
            f"({diff['baseline_attempted']} attempted) -> {_pct(summary['accuracy'])} "
            f"({summary['attempted']} attempted)",
            f"- Prompt changed: {'yes' if diff['prompt_changed'] else 'no'}",
            f"- Fixed ({len(diff['fixed'])}): {_ids(diff['fixed'])}",
            f"- Broken ({len(diff['broken'])}): {_ids(diff['broken'])}",
            f"- Only in this run: {_ids(diff['only_in_current'])}",
            f"- Only in baseline: {_ids(diff['only_in_baseline'])}",
        ]
    return "\n".join(lines) + "\n"


def write_reports(report: Mapping[str, Any], markdown: str, out_dir: Path, basename: str) -> tuple[Path, Path]:
    """Write ``<basename>.json`` and ``.md``; never overwrite an earlier run (adds -2, -3...)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = basename
    for n in itertools.count(2):
        json_path = out_dir / f"{stem}.json"
        md_path = out_dir / f"{stem}.md"
        if not json_path.exists() and not md_path.exists():
            break
        stem = f"{basename}-{n}"
    with open(json_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    with open(md_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(markdown)
    return json_path, md_path


# --- console ----------------------------------------------------------------------


def _ascii(text: object) -> str:
    return str(text).encode("ascii", "replace").decode("ascii")


def say(text: object = "") -> None:
    print(_ascii(text), flush=True)


def console_summary(report: Mapping[str, Any]) -> list[str]:
    summary = report["summary"]
    lo, hi = summary["accuracy_ci95"]
    cm = summary["confusion_matrix"]
    latency = summary["median_latency_ms"]
    lines = [
        f"Accuracy: {summary['correct']}/{summary['attempted']} = {_pct(summary['accuracy'])} "
        f"(95% CI {_pct(lo)} - {_pct(hi)})",
        "        " + "".join(f"{c:>7}" for c in metrics.COLUMNS),
    ]
    for label in metrics.LABELS:
        lines.append(f"  {label:<6}" + "".join(f"{cm[label][c]:>7}" for c in metrics.COLUMNS))
    lines.append(
        f"Errors: {summary['errors']} | not run: {summary['not_run']} | median latency: "
        f"{'n/a' if latency is None else f'{latency:.0f} ms'}"
    )
    diff = report.get("baseline")
    if diff is not None:
        warning = " (WARNING: dataset hash differs)" if diff["dataset_hash_changed"] else ""
        lines.append(
            f"Baseline: {len(diff['fixed'])} fixed, {len(diff['broken'])} broken{warning}"
        )
    return lines


# --- CLI --------------------------------------------------------------------------


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return number


def _non_negative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals.dialect",
        description="Measure MSA (ar) vs Egyptian Arabic (arz) auto-detection via the real app path.",
    )
    parser.add_argument("--target", default="en", choices=TARGET_CHOICES,
                        help="target language (default: en; ar/arz not allowed)")
    parser.add_argument("--limit", type=_positive_int, help="only the first N items (after --tag)")
    parser.add_argument("--tag", choices=sorted(TAGS), help="only items with this tag")
    parser.add_argument("--model", help="override the active provider's model")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="dataset JSONL path")
    parser.add_argument("--baseline", type=Path, help="earlier result JSON to compare against")
    parser.add_argument("--delay", type=_non_negative_float, default=4.0,
                        help="seconds between requests (default: 4)")
    parser.add_argument("--retry-wait", type=_non_negative_float, default=60.0,
                        help="seconds to wait after a rate limit before retrying (default: 60)")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR,
                        help="report directory (default: evals/results)")
    parser.add_argument("--yes", action="store_true",
                        help=f"skip the confirmation for more than {CONFIRM_THRESHOLD} requests")
    return parser


def _confirm(count: int, delay: float, input_fn: Callable[[str], str]) -> bool:
    minutes = count * delay / 60
    say(f"About to send {count} real requests (~{minutes:.1f} min at {delay:g} s delay).")
    try:
        answer = input_fn("Continue? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def main(
    argv: Sequence[str] | None = None,
    *,
    sleep: Sleep = asyncio.sleep,
    input_fn: Callable[[str], str] = input,
) -> int:
    """CLI entry point. Exit codes: 0 complete, 1 aborted, 2 partial (rate limit)."""
    args = build_parser().parse_args(argv)

    try:
        all_items = load_dataset(args.dataset)
        baseline = load_baseline(args.baseline) if args.baseline else None
    except (DatasetError, EvalAborted, OSError) as exc:
        say(f"Error: {exc}")
        return 1

    selected = select_items(all_items, args.tag, args.limit)
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

    if len(selected) > CONFIRM_THRESHOLD and not args.yes:
        if not _confirm(len(selected), args.delay, input_fn):
            say("Aborted: nothing was sent.")
            return 1

    service = TranslationService(build_provider(settings), settings.max_chars)
    created = datetime.now(UTC)
    total = len(selected)

    def progress(index: int, result: ItemResult) -> None:
        shown = result.predicted or f"error:{result.error_type}"
        say(f"[{index + 1}/{total}] {result.id} {result.label} -> {shown} {result.outcome.upper()}")

    say(f"Running {total} item(s) on {settings.provider}/{settings.active_model}, target {args.target}")
    try:
        run = asyncio.run(
            run_eval(
                service, selected, args.target,
                delay=args.delay, retry_wait=args.retry_wait, sleep=sleep, on_item=progress,
            )
        )
    except EvalAborted as exc:
        say(f"Aborted: {exc}")
        return 1

    meta = {
        "created_utc": created.isoformat(timespec="seconds"),
        "dataset": {
            "path": display_path(args.dataset),
            "sha256": dataset_hash(all_items),
            "size": len(all_items),
        },
        "provider": settings.provider,
        "model": settings.active_model,
        "target": args.target,
        "prompt_fingerprint": prompt_fingerprint(args.target),
        "git_commit": git_commit(),
        "filters": {"tag": args.tag, "limit": args.limit},
        "selected": total,
    }
    report = build_report(run, meta)
    if baseline is not None:
        report["baseline"] = diff_baseline(report, baseline, display_path(args.baseline))
    basename = report_basename(created, settings.provider, settings.active_model)
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
