"""Tests for the dialect evaluation dataset and its loader."""

from __future__ import annotations

import unicodedata
from collections import Counter
from pathlib import Path

import pytest

from evals.dataset import (
    DEFAULT_DATASET,
    LABELS,
    TAGS,
    DatasetError,
    EvalItem,
    dataset_hash,
    load_dataset,
)

# Marker words listed in app/providers/prompts.py, with common spelling variants
# (with/without hamza, feminine forms, final ى).
MARKER_WORDS = frozenset(
    {
        "مش",
        "إنت", "انت", "إنتي", "انتي", "إنتى", "انتى",
        "إحنا", "احنا",
        "هم",
        "إيه", "ايه",
        "ليه",
        "إزاي", "ازاي", "إزاى", "ازاى",
        "فين",
        "إمتى", "امتى", "إمتي", "امتي",
        "عايز", "عايزة", "عاوز", "عاوزة",
        "كده",
        "دلوقتي", "دلوقتى",
        "خالص",
        "أوي", "اوي", "أوى", "اوى",
        "كويس", "كويسة",
        "إزيك", "ازيك", "إزيكي", "ازيكي",
    }
)


def _tokens(text: str) -> list[str]:
    """Whitespace tokens with punctuation stripped from both ends."""
    out = []
    for raw in text.split():
        start, end = 0, len(raw)
        while start < end and unicodedata.category(raw[start]).startswith("P"):
            start += 1
        while end > start and unicodedata.category(raw[end - 1]).startswith("P"):
            end -= 1
        if start < end:
            out.append(raw[start:end])
    return out


def _marker_hits(text: str) -> list[str]:
    """Marker tokens in ``text``, also catching a leading و or ف (ومش, فإيه)."""
    hits = []
    for token in _tokens(text):
        if token in MARKER_WORDS:
            hits.append(token)
        elif token[0] in "وف" and token[1:] in MARKER_WORDS:
            hits.append(token)
    return hits


@pytest.fixture(scope="module")
def items() -> list[EvalItem]:
    return load_dataset(DEFAULT_DATASET)


# --- the real dataset -------------------------------------------------------------


def test_real_dataset_loads(items: list[EvalItem]) -> None:
    assert len(items) >= 60


def test_ids_and_texts_unique(items: list[EvalItem]) -> None:
    ids = [item.id for item in items]
    texts = [" ".join(item.text.split()) for item in items]
    assert len(set(ids)) == len(ids)
    assert len(set(texts)) == len(texts)


def test_labels_and_tags_valid(items: list[EvalItem]) -> None:
    for item in items:
        assert item.label in LABELS
        assert set(item.tags) <= TAGS
        assert item.tags, f"{item.id} has no tags"


def test_each_label_has_at_least_30_items(items: list[EvalItem]) -> None:
    counts = Counter(item.label for item in items)
    for label in LABELS:
        assert counts[label] >= 30, counts


def test_shared_phrases_are_msa(items: list[EvalItem]) -> None:
    for item in items:
        if "shared" in item.tags:
            assert item.label == "ar", item.id


def test_short_items_have_at_most_three_words(items: list[EvalItem]) -> None:
    for item in items:
        if "short" in item.tags:
            assert len(item.text.split()) <= 3, item.id


def test_no_markers_items_avoid_prompt_marker_words(items: list[EvalItem]) -> None:
    tagged = [item for item in items if "no_markers" in item.tags]
    assert tagged
    for item in tagged:
        assert item.label == "arz", item.id
        assert _marker_hits(item.text) == [], f"{item.id}: {_marker_hits(item.text)}"


def test_marker_matching_uses_whole_tokens() -> None:
    # Substrings must not match: مهم / فهمت contain هم, مشكلة / مشي contain مش.
    assert _marker_hits("الموضوع مهم وفهمت المشكلة ومشي") == []
    # Whole tokens, punctuation and a leading و / ف do match.
    assert _marker_hits("ومش عارف، فإيه؟") == ["ومش", "فإيه"]
    assert _marker_hits("(كده)") == ["كده"]


# --- loader errors ----------------------------------------------------------------

VALID = '{"id": "d001", "text": "صباح الخير", "label": "ar", "tags": ["short"]}'


def _write(tmp_path: Path, *lines: str, newline: str = "\n") -> Path:
    path = tmp_path / "data.jsonl"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(newline.join(lines) + newline)
    return path


@pytest.mark.parametrize(
    ("bad_line", "fragment"),
    [
        ("{not json", "invalid JSON"),
        ('{"id": "d002", "text": "x", "label": "ar", "tags": ["nope"]}', "unknown tag"),
        ('{"id": "d002", "text": "x", "label": "apc", "tags": []}', "label"),
        ('{"id": "d002", "label": "ar", "tags": []}', "text"),
        ('{"id": "x2", "text": "x", "label": "ar", "tags": []}', "id"),
        ('{"id": "d002", "text": "x", "label": "ar", "tags": [], "extra": 1}', "extra"),
        ('{"id": "d001", "text": "y", "label": "ar", "tags": []}', "duplicate id"),
        ('{"id": "d002", "text": "صباح  الخير", "label": "ar", "tags": []}', "duplicate text"),
        ("[1, 2]", "JSON object"),
    ],
)
def test_malformed_line_names_file_and_line(
    tmp_path: Path, bad_line: str, fragment: str
) -> None:
    path = _write(tmp_path, VALID, "", bad_line)
    with pytest.raises(DatasetError) as excinfo:
        load_dataset(path)
    message = str(excinfo.value)
    assert f"{path}:3" in message
    assert fragment in message


def test_bom_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bom.jsonl"
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(VALID + "\n")
    with pytest.raises(DatasetError, match="BOM"):
        load_dataset(path)


def test_hash_ignores_line_endings_and_notes(tmp_path: Path) -> None:
    second = '{"id": "d002", "text": "إزيك؟", "label": "arz", "tags": ["short"]}'
    lf = tmp_path / "lf"
    crlf = tmp_path / "crlf"
    lf.mkdir()
    crlf.mkdir()
    a = load_dataset(_write(lf, VALID, second, newline="\n"))
    b = load_dataset(_write(crlf, VALID, second, newline="\r\n"))
    assert dataset_hash(a) == dataset_hash(b)

    noted = [a[0].model_copy(update={"note": "changed"}), a[1]]
    assert dataset_hash(noted) == dataset_hash(a)

    relabelled = [a[0], a[1].model_copy(update={"label": "ar"})]
    assert dataset_hash(relabelled) != dataset_hash(a)
