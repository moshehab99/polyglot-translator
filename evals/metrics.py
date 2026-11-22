"""Eval metrics. Pure functions: no I/O, no clock, no randomness.

Detection (dialect and Franco) plus Franco arabization (normalisation, chrF, Latin leak).

Detection conventions (defaults, used by the dialect eval):
- Rows of the confusion matrix are the gold labels ``ar`` and ``arz``.
- Columns are ``ar``, ``arz``, ``other`` (any non-Arabic prediction) and ``error``
  (no prediction, ``predicted is None``).
- Accuracy is ``correct / attempted``; errors and non-Arabic predictions count as wrong.
"""

from __future__ import annotations

import math
import re
import statistics
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

LABELS: tuple[str, ...] = ("ar", "arz")
COLUMNS: tuple[str, ...] = ("ar", "arz", "other", "error")

ConfusionMatrix = dict[str, dict[str, int]]


def column_for(predicted: str | None, known: Iterable[str] = LABELS) -> str:
    """Map a prediction to its confusion-matrix column (``known`` codes keep their own)."""
    if predicted is None:
        return "error"
    return predicted if predicted in known else "other"


def confusion_matrix(
    pairs: Iterable[tuple[str, str | None]],
    labels: Sequence[str] = LABELS,
    columns: Sequence[str] = COLUMNS,
) -> ConfusionMatrix:
    """``pairs`` are ``(label, predicted)``; ``predicted`` is None for errors.

    Rows are ``labels``; ``columns`` must include ``other`` and ``error``.
    """
    known = [c for c in columns if c not in ("other", "error")]
    cm: ConfusionMatrix = {label: dict.fromkeys(columns, 0) for label in labels}
    for label, predicted in pairs:
        if label not in cm:
            raise ValueError(f"unknown gold label: {label!r}")
        cm[label][column_for(predicted, known)] += 1
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


def mean(values: Iterable[float | None]) -> float | None:
    """Arithmetic mean of the non-None values, or None if there are none."""
    present = [v for v in values if v is not None]
    return statistics.fmean(present) if present else None


# --- Franco arabization -----------------------------------------------------------

_LATIN_WORD = re.compile(r"[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*")
_TASHKEEL = re.compile("[ً-ٰٟ]")
_LETTER_MAP = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ـ": None,
        # Arabic-Indic (U+0660-0669) and Persian (U+06F0-06F9) digits -> ASCII 0-9
        **{chr(0x0660 + d): str(d) for d in range(10)},
        **{chr(0x06F0 + d): str(d) for d in range(10)},
    }
)


def latin_words(text: str) -> list[str]:
    """Casefolded tokens with at least one ASCII letter; digits allowed (``3ayez``)."""
    return [word.casefold() for word in _LATIN_WORD.findall(text)]


def latin_leak(output: str, reference: str) -> bool:
    """True if ``output`` has a Latin-script word that the reference does not have."""
    return bool(set(latin_words(output)) - set(latin_words(reference)))


def normalize_arabic(text: str) -> str:
    """Normalise for chrF.

    Steps:
    - Remove tashkeel and tatweel.
    - Map أ/إ/آ/ٱ -> ا, ة -> ه and ى -> ي.
    - Map Arabic-Indic (٠-٩) and Persian (۰-۹) digits to ASCII 0-9.
    - Drop every Unicode punctuation character (``P*``, including ، ؟ ؛ and hyphens).
    - Collapse whitespace and casefold Latin letters.
    """
    text = _TASHKEEL.sub("", text).translate(_LETTER_MAP)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("P"))
    return " ".join(text.split()).casefold()


def char_ngrams(text: str, n: int) -> Counter[str]:
    """Character n-grams of ``text`` with all whitespace removed."""
    compact = "".join(text.split())
    return Counter(compact[i : i + n] for i in range(len(compact) - n + 1))


def chrf(hypothesis: str, reference: str, max_n: int = 6, beta: float = 2.0) -> float:
    """Sentence chrF (Popovic 2015), 0-100, as in sacrebleu's default.

    Whitespace is ignored. For each order n = 1..max_n where both sides have n-grams,
    precision and recall come from clipped n-gram matches. They are averaged over those
    orders, then F_beta = (1 + b^2) P R / (b^2 P + R). Both empty -> 100, one empty -> 0.
    """
    hyp_len = len("".join(hypothesis.split()))
    ref_len = len("".join(reference.split()))
    if hyp_len == 0 and ref_len == 0:
        return 100.0
    if hyp_len == 0 or ref_len == 0:
        return 0.0
    precisions: list[float] = []
    recalls: list[float] = []
    for n in range(1, max_n + 1):
        hyp, ref = char_ngrams(hypothesis, n), char_ngrams(reference, n)
        if not hyp or not ref:
            continue
        matches = sum((hyp & ref).values())
        precisions.append(matches / hyp.total())
        recalls.append(matches / ref.total())
    p, r = statistics.fmean(precisions), statistics.fmean(recalls)
    b2 = beta * beta
    denom = b2 * p + r
    return 100.0 * (1 + b2) * p * r / denom if denom else 0.0


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
