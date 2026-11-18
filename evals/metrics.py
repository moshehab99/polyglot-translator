"""Detection metrics. Pure functions: no I/O, no clock, no randomness.

Conventions:
- Rows of the confusion matrix are the gold labels ``ar`` and ``arz``.
- Columns are ``ar``, ``arz``, ``other`` (any non-Arabic prediction) and ``error``
  (no prediction, ``predicted is None``).
- Accuracy is ``correct / attempted``; errors and non-Arabic predictions count as wrong.
"""

from __future__ import annotations

import math
import re
import statistics
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

LABELS: tuple[str, ...] = ("ar", "arz")
COLUMNS: tuple[str, ...] = ("ar", "arz", "other", "error")

ConfusionMatrix = dict[str, dict[str, int]]


def column_for(predicted: str | None) -> str:
    """Map a prediction to its confusion-matrix column."""
    if predicted is None:
        return "error"
    return predicted if predicted in LABELS else "other"


def confusion_matrix(pairs: Iterable[tuple[str, str | None]]) -> ConfusionMatrix:
    """``pairs`` are ``(label, predicted)``; ``predicted`` is None for errors."""
    cm: ConfusionMatrix = {label: dict.fromkeys(COLUMNS, 0) for label in LABELS}
    for label, predicted in pairs:
        if label not in cm:
            raise ValueError(f"unknown gold label: {label!r}")
        cm[label][column_for(predicted)] += 1
    return cm


def accuracy(correct: int, attempted: int) -> float:
    return correct / attempted if attempted else 0.0


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for ``k`` successes out of ``n`` (95% for z=1.96)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


def per_label_prf(cm: ConfusionMatrix) -> dict[str, dict[str, float | int]]:
    """Precision, recall and F1 per gold label; 0.0 wherever a denominator is 0.

    Recall uses the whole row (``other`` and ``error`` included), so it equals the
    per-label accuracy.
    """
    out: dict[str, dict[str, float | int]] = {}
    for label in LABELS:
        tp = cm[label][label]
        predicted_as = sum(cm[row][label] for row in LABELS)
        support = sum(cm[label].values())
        precision = _safe_div(tp, predicted_as)
        recall = _safe_div(tp, support)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        out[label] = {"precision": precision, "recall": recall, "f1": f1, "support": support}
    return out


def per_tag_accuracy(
    rows: Iterable[tuple[Sequence[str], bool]],
) -> dict[str, dict[str, float | int]]:
    """``rows`` are ``(tags, correct)``. An item counts once for each of its tags."""
    counts: dict[str, list[int]] = {}
    for tags, correct in rows:
        for tag in tags:
            n_correct = counts.setdefault(tag, [0, 0])
            n_correct[0] += 1
            n_correct[1] += int(correct)
    return {
        tag: {"n": n, "correct": c, "accuracy": accuracy(c, n)}
        for tag, (n, c) in sorted(counts.items())
    }


def median_latency(values: Iterable[float | None]) -> float | None:
    """Median of the non-None values, or None if there are none."""
    present = [v for v in values if v is not None]
    return statistics.median(present) if present else None


_LATIN_WORD = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")


def latin_words(text: str) -> list[str]:
    """Casefolded tokens with at least one ASCII letter; digits allowed (``3ayez``)."""
    return [word.casefold() for word in _LATIN_WORD.findall(text)]


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """All metrics for item rows with keys label, predicted, outcome, tags, latency_ms."""
    attempted = len(rows)
    correct = sum(1 for r in rows if r["outcome"] == "correct")
    errors = sum(1 for r in rows if r["outcome"] == "error")
    lo, hi = wilson_interval(correct, attempted)
    cm = confusion_matrix((r["label"], r["predicted"]) for r in rows)
    return {
        "attempted": attempted,
        "correct": correct,
        "wrong": attempted - correct - errors,
        "errors": errors,
        "accuracy": accuracy(correct, attempted),
        "accuracy_ci95": [lo, hi],
        "confusion_matrix": cm,
        "per_label": per_label_prf(cm),
        "per_tag": per_tag_accuracy((r["tags"], r["outcome"] == "correct") for r in rows),
        "median_latency_ms": median_latency(r["latency_ms"] for r in rows),
    }
