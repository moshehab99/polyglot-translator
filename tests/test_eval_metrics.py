"""Tests for evals.metrics (pure functions, hand-computed expectations)."""

from __future__ import annotations

import pytest

from evals.metrics import (
    accuracy,
    column_for,
    char_ngrams,
    chrf,
    confusion_matrix,
    latin_leak,
    latin_words,
    mean,
    normalize_arabic,
    median_latency,
    per_label_prf,
    per_tag_accuracy,
    summarize,
    wilson_interval,
)

# 10 items. ar row: 3 ar, 1 arz, 1 en (other), 1 error. arz row: 2 ar, 2 arz.
PAIRS: list[tuple[str, str | None]] = [
    ("ar", "ar"), ("ar", "ar"), ("ar", "ar"), ("ar", "arz"), ("ar", "en"), ("ar", None),
    ("arz", "arz"), ("arz", "arz"), ("arz", "ar"), ("arz", "ar"),
]


def test_column_for() -> None:
    assert column_for("ar") == "ar"
    assert column_for("arz") == "arz"
    assert column_for("fr") == "other"
    assert column_for(None) == "error"


def test_confusion_matrix_hand_computed() -> None:
    assert confusion_matrix(PAIRS) == {
        "ar": {"ar": 3, "arz": 1, "other": 1, "error": 1},
        "arz": {"ar": 2, "arz": 2, "other": 0, "error": 0},
    }


def test_confusion_matrix_rejects_unknown_label() -> None:
    with pytest.raises(ValueError, match="unknown gold label"):
        confusion_matrix([("en", "en")])


def test_accuracy() -> None:
    assert accuracy(5, 10) == 0.5
    assert accuracy(0, 0) == 0.0


def test_per_label_prf_hand_computed() -> None:
    prf = per_label_prf(confusion_matrix(PAIRS))
    # ar: tp=3, predicted as ar = 3+2 = 5, support = 6
    assert prf["ar"]["precision"] == pytest.approx(0.6)
    assert prf["ar"]["recall"] == pytest.approx(0.5)
    assert prf["ar"]["f1"] == pytest.approx(2 * 0.6 * 0.5 / 1.1)
    assert prf["ar"]["support"] == 6
    # arz: tp=2, predicted as arz = 1+2 = 3, support = 4
    assert prf["arz"]["precision"] == pytest.approx(2 / 3)
    assert prf["arz"]["recall"] == pytest.approx(0.5)
    assert prf["arz"]["f1"] == pytest.approx(4 / 7)
    assert prf["arz"]["support"] == 4


def test_per_label_prf_zero_division() -> None:
    # arz is never predicted and never correct -> all zeros, no exception.
    prf = per_label_prf(confusion_matrix([("ar", "ar"), ("arz", "ar"), ("arz", None)]))
    assert prf["arz"] == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 2}
    assert prf["ar"]["precision"] == pytest.approx(0.5)
    assert prf["ar"]["recall"] == 1.0

    empty = per_label_prf(confusion_matrix([]))
    for label in ("ar", "arz"):
        assert empty[label] == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "support": 0}


def test_wilson_interval() -> None:
    lo, hi = wilson_interval(8, 10)
    assert lo == pytest.approx(0.4902, abs=1e-4)
    assert hi == pytest.approx(0.9433, abs=1e-4)

    lo, hi = wilson_interval(10, 10)
    assert lo == pytest.approx(0.7225, abs=1e-4)
    assert hi == pytest.approx(1.0)

    lo, hi = wilson_interval(0, 10)
    assert lo == pytest.approx(0.0)
    assert hi == pytest.approx(0.2775, abs=1e-4)

    assert wilson_interval(0, 0) == (0.0, 0.0)


def test_per_tag_accuracy_counts_each_tag() -> None:
    rows = [(("short", "shared"), True), (("short",), False), (("long",), True), ((), False)]
    assert per_tag_accuracy(rows) == {
        "long": {"n": 1, "correct": 1, "accuracy": 1.0},
        "shared": {"n": 1, "correct": 1, "accuracy": 1.0},
        "short": {"n": 2, "correct": 1, "accuracy": 0.5},
    }


def test_median_latency() -> None:
    assert median_latency([300.0, None, 100.0, 200.0]) == 200.0
    assert median_latency([100.0, 200.0]) == 150.0
    assert median_latency([None, None]) is None
    assert median_latency([]) is None


def test_summarize() -> None:
    rows = [
        {"label": "ar", "predicted": "ar", "outcome": "correct", "tags": ["clear"], "latency_ms": 100.0},
        {"label": "arz", "predicted": "ar", "outcome": "wrong", "tags": ["short"], "latency_ms": 300.0},
        {"label": "arz", "predicted": None, "outcome": "error", "tags": ["short"], "latency_ms": None},
        {"label": "ar", "predicted": "en", "outcome": "wrong", "tags": ["clear"], "latency_ms": 200.0},
    ]
    summary = summarize(rows)
    assert summary["attempted"] == 4
    assert summary["correct"] == 1
    assert summary["wrong"] == 2
    assert summary["errors"] == 1
    assert summary["accuracy"] == 0.25  # errors stay in the denominator
    assert summary["accuracy_ci95"] == list(wilson_interval(1, 4))
    assert summary["confusion_matrix"]["arz"] == {"ar": 1, "arz": 0, "other": 0, "error": 1}
    assert summary["confusion_matrix"]["ar"]["other"] == 1
    assert summary["per_tag"]["short"] == {"n": 2, "correct": 0, "accuracy": 0.0}
    assert summary["median_latency_ms"] == 200.0
    assert set(summary["per_label"]) == {"ar", "arz"}


def test_summarize_empty() -> None:
    summary = summarize([])
    assert summary["attempted"] == 0
    assert summary["accuracy"] == 0.0
    assert summary["accuracy_ci95"] == [0.0, 0.0]
    assert summary["median_latency_ms"] is None
    assert summary["per_tag"] == {}


def test_latin_words() -> None:
    assert latin_words("الـ Meeting اتأجل, 3ayez upload!") == ["meeting", "3ayez", "upload"]
    assert latin_words("أنا 25 سنة") == []
    assert latin_words("") == []


def test_confusion_matrix_custom_labels_and_columns() -> None:
    columns = ("arz", "ar", "en", "fr", "other", "error")
    cm = confusion_matrix(
        [("arz", "arz"), ("arz", "en"), ("en", "en"), ("en", "arz"), ("fr", None), ("fr", "de")],
        labels=("arz", "en", "fr"),
        columns=columns,
    )
    assert cm["arz"] == {"arz": 1, "ar": 0, "en": 1, "fr": 0, "other": 0, "error": 0}
    assert cm["en"] == {"arz": 1, "ar": 0, "en": 1, "fr": 0, "other": 0, "error": 0}
    assert cm["fr"] == {"arz": 0, "ar": 0, "en": 0, "fr": 0, "other": 1, "error": 1}
    with pytest.raises(ValueError, match="unknown gold label"):
        confusion_matrix([("es", "es")], labels=("arz",), columns=columns)


def test_mean() -> None:
    assert mean([100.0, None, 50.0]) == pytest.approx(75.0)
    assert mean([None]) is None
    assert mean([]) is None


# --- Franco arabization ------------------------------------------------------------


def test_normalize_arabic() -> None:
    # tashkeel and tatweel removed
    assert normalize_arabic("مُحَمَّدٌ") == "محمد"
    assert normalize_arabic("جـــدا") == "جدا"
    # alef forms, taa marbuta, alef maqsura
    assert normalize_arabic("أنا إنت آه ٱلله") == "انا انت اه الله"
    assert normalize_arabic("حاجة حلوة") == "حاجه حلوه"
    assert normalize_arabic("على إمتى") == "علي امتي"
    # punctuation dropped (Arabic and Latin), spaces collapsed, Latin casefolded
    assert normalize_arabic("إنت فين؟  أنا، هنا!") == "انت فين انا هنا"
    assert normalize_arabic("الـ Meeting (T-shirt)؛") == "ال meeting tshirt"
    # emoji are not punctuation and stay
    assert normalize_arabic("حر 🥵") == "حر 🥵"
    # Arabic-Indic and Persian digits become ASCII
    assert normalize_arabic("٠١٢٣٤٥٦٧٨٩") == "0123456789"
    assert normalize_arabic("۰۱۲۳۴۵۶۷۸۹") == "0123456789"
    assert normalize_arabic("في ١٠ دقايق") == normalize_arabic("في 10 دقايق") == "في 10 دقايق"


def test_chrf_same_for_arabic_indic_and_ascii_digits() -> None:
    reference = normalize_arabic("هعملك call في 10 دقايق")
    assert chrf(normalize_arabic("هعملك call في ١٠ دقايق"), reference) == pytest.approx(100.0)
    assert chrf(normalize_arabic("هعملك call في ۱۰ دقايق"), reference) == pytest.approx(100.0)


def test_char_ngrams_ignore_whitespace() -> None:
    assert char_ngrams("ab c", 2) == {"ab": 1, "bc": 1}
    assert char_ngrams("ab", 3) == {}


def test_chrf_identical_is_100() -> None:
    assert chrf("أنا مش فاهم", "أنا مش فاهم") == pytest.approx(100.0)
    assert chrf("abc", "a b c") == pytest.approx(100.0)  # whitespace is ignored


def test_chrf_nothing_shared_is_0() -> None:
    assert chrf("abc", "xyz") == 0.0
    assert chrf("ana msh fahem", "أنا مش فاهم") == 0.0


def test_chrf_hand_computed_equal_p_and_r() -> None:
    """hyp "abcd", ref "abce" (beta 2, orders 1..6).

    n=1: 3 of 4 match -> P = R = 3/4
    n=2: ab, bc match of 3 -> P = R = 2/3
    n=3: abc matches of 2 -> P = R = 1/2
    n=4: abcd vs abce -> P = R = 0
    n=5, 6: no n-grams on either side, skipped (effective order 4)
    P = R = (3/4 + 2/3 + 1/2 + 0) / 4 = 23/48, so F = 23/48 = 47.9167
    """
    assert chrf("abcd", "abce") == pytest.approx(100 * 23 / 48)


def test_chrf_hand_computed_beta_weights_recall() -> None:
    """hyp "ab", ref "abc" (beta 2).

    n=1: P = 2/2, R = 2/3; n=2: P = 1/1, R = 1/2; n>=3: hyp has none, skipped.
    P = 1, R = (2/3 + 1/2) / 2 = 7/12
    F = (1 + 4) * 1 * 7/12 / (4 * 1 + 7/12) = (35/12) / (55/12) = 7/11 = 63.6364
    """
    assert chrf("ab", "abc") == pytest.approx(100 * 7 / 11)


def test_chrf_empty_inputs() -> None:
    assert chrf("", "") == 100.0
    assert chrf("", "abc") == 0.0
    assert chrf("abc", "  ") == 0.0


def test_latin_leak() -> None:
    reference = "الـ meeting اتأجل لبكرة"
    assert latin_leak("الـ meeting اتأجل لبكرة", reference) is False
    assert latin_leak("الـ Meeting اتأجل", reference) is False  # case-insensitive
    assert latin_leak("الميتنج اتأجل", reference) is False  # dropping a Latin word is fine
    assert latin_leak("الـ meeting et2agel لبكرة", reference) is True
    assert latin_leak("أنا 3ayez", "أنا عايز") is True
    assert latin_leak("عندي 25 سنة", "عندي ٢٥ سنة") is False  # digits alone are not words
