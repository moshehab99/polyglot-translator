"""Tests for the Franco-Arabic dataset, its item schema and loader."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from evals.dataset import DEFAULT_DATASET, DatasetError, dataset_hash, load_dataset
from evals.franco import (
    ARABIC_LABELS,
    DEFAULT_FRANCO_DATASET,
    FRANCO_TAGS,
    FrancoItem,
    franco_hash,
    load_franco,
)

DIALECT_BASELINE = (
    Path(__file__).resolve().parent.parent
    / "evals" / "results" / "dialect_20261118-030247_gemini_gemini-3.5-flash-lite.json"
)
NUMERAL_LETTER = re.compile(r"[A-Za-z][235789]|[235789][A-Za-z]")


@pytest.fixture(scope="module")
def items() -> list[FrancoItem]:
    return load_franco(DEFAULT_FRANCO_DATASET)


def _group(item: FrancoItem) -> str:
    return item.label if item.label in ARABIC_LABELS else "control"


# --- the real dataset -------------------------------------------------------------


def test_real_dataset_loads(items: list[FrancoItem]) -> None:
    assert len(items) >= 60
    assert [i.id for i in items[:60]] == [f"f{n:03d}" for n in range(1, 61)]


def test_composition(items: list[FrancoItem]) -> None:
    groups = Counter(_group(i) for i in items)
    assert groups["arz"] >= 45 and groups["ar"] >= 5 and groups["control"] >= 10, groups


def test_every_tag_used_at_least_three_times(items: list[FrancoItem]) -> None:
    counts = Counter(tag for item in items for tag in item.tags)
    assert {tag for tag in FRANCO_TAGS if counts[tag] < 3} == set(), counts


def test_split_about_one_third_test_and_stratified(items: list[FrancoItem]) -> None:
    share = sum(i.split == "test" for i in items) / len(items)
    assert 0.25 <= share <= 0.40, share
    for group in ("arz", "ar", "control"):
        splits = {i.split for i in items if _group(i) == group}
        assert splits == {"dev", "test"}, group


def test_short_items_have_at_most_three_words(items: list[FrancoItem]) -> None:
    for item in items:
        if "short" in item.tags:
            assert len(item.text.split()) <= 3, item.id


def test_numerals_tags_match_the_text(items: list[FrancoItem]) -> None:
    for item in items:
        uses_numerals = bool(NUMERAL_LETTER.search(item.text))
        if "numerals" in item.tags:
            assert uses_numerals, item.id
        if "no_numerals" in item.tags or "control" in item.tags:
            assert not uses_numerals, item.id


def test_long_items_have_at_least_two_sentences(items: list[FrancoItem]) -> None:
    for item in items:
        if "long" in item.tags:
            sentences = [s for s in re.split(r"[.?!]+", item.text) if s.strip()]
            assert len(sentences) >= 2, item.id


def test_shared_loader_still_reproduces_dialect_baseline_hash() -> None:
    with open(DIALECT_BASELINE, encoding="utf-8") as fh:
        recorded = json.load(fh)["meta"]["dataset"]["sha256"]
    assert dataset_hash(load_dataset(DEFAULT_DATASET)) == recorded


# --- item schema and loader errors -------------------------------------------------

ARZ = {
    "id": "f001", "text": "ana msh fahem", "label": "arz", "arabic": "أنا مش فاهم",
    "meaning": "I don't understand", "tags": ["short", "no_numerals"], "split": "dev",
}
CONTROL = {"id": "f002", "text": "see you later", "label": "en", "tags": ["control"], "split": "test"}


def _line(base: dict[str, object], **changes: object) -> str:
    data = {**base, **changes}
    return json.dumps({k: v for k, v in data.items() if v is not ...}, ensure_ascii=False)


def _write(tmp_path: Path, *lines: str, newline: str = "\n") -> Path:
    path = tmp_path / "franco.jsonl"
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(newline.join(lines) + newline)
    return path


def test_valid_lines_load(tmp_path: Path) -> None:
    loaded = load_franco(_write(tmp_path, _line(ARZ), _line(CONTROL)))
    assert [i.id for i in loaded] == ["f001", "f002"]
    assert loaded[1].arabic is None


@pytest.mark.parametrize(
    ("bad_line", "fragment"),
    [
        ("{not json", "invalid JSON"),
        ("[1, 2]", "JSON object"),
        (_line(ARZ, id="d003"), "id"),
        (_line(ARZ, id="f3"), "id"),
        (_line(ARZ, id="f003", label="apc"), "label"),
        (_line(ARZ, id="f003", text="  x"), "whitespace"),
        (_line(ARZ, id="f003", text=...), "text"),
        (_line(ARZ, id="f003", split="train"), "split"),
        (_line(ARZ, id="f003", split=...), "split"),
        (_line(ARZ, id="f003", tags=["nope"]), "unknown tag"),
        (_line(ARZ, id="f003", tags=[]), "at least one tag"),
        (_line(ARZ, id="f003", tags=["short", "short", "numerals"]), "duplicate tags"),
        (_line(ARZ, id="f003", extra=1), "extra"),
        (_line(ARZ, id="f003", arabic=...), "arabic is required"),
        (_line(ARZ, id="f003", meaning=...), "meaning is required"),
        (_line(ARZ, id="f003", arabic="ana msh fahem"), "Arabic letters"),
        (_line(ARZ, id="f003", arabic="أنا مش فاهم meeting"), "not in text: meeting"),
        (_line(ARZ, id="f003", tags=["short"]), "exactly one of numerals"),
        (_line(ARZ, id="f003", tags=["numerals", "no_numerals"]), "exactly one of numerals"),
        (_line(ARZ, id="f003", tags=["control", "no_numerals"]), "control tag"),
        (_line(ARZ, id="f003", tags=["shared", "no_numerals"]), "shared"),
        (_line(CONTROL, id="f003", arabic="نص"), "arabic must be absent"),
        (_line(CONTROL, id="f003", meaning="x"), "meaning must be absent"),
        (_line(CONTROL, id="f003", tags=["chat"]), "needs the control tag"),
        (_line(CONTROL, id="f003", tags=["control", "numerals"]), "controls must not"),
        (_line(ARZ, text="other text"), "duplicate id"),
        (_line(ARZ, id="f003", text="ana  msh fahem"), "duplicate text"),
    ],
)
def test_malformed_line_names_file_and_line(tmp_path: Path, bad_line: str, fragment: str) -> None:
    path = _write(tmp_path, _line(ARZ), "", bad_line)
    with pytest.raises(DatasetError) as excinfo:
        load_franco(path)
    message = str(excinfo.value)
    assert f"{path}:3" in message
    assert fragment in message


def test_latin_words_in_arabic_may_differ_in_case(tmp_path: Path) -> None:
    line = _line(
        ARZ, text="el Meeting et2agel", arabic="الـ meeting اتأجل",
        tags=["code_switch", "numerals"],
    )
    assert load_franco(_write(tmp_path, line))[0].arabic == "الـ meeting اتأجل"


def test_bom_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "bom.jsonl"
    with open(path, "w", encoding="utf-8-sig") as fh:
        fh.write(_line(ARZ) + "\n")
    with pytest.raises(DatasetError, match="BOM"):
        load_franco(path)


def test_hash_ignores_line_endings_and_notes(tmp_path: Path) -> None:
    lf, crlf = tmp_path / "lf", tmp_path / "crlf"
    lf.mkdir()
    crlf.mkdir()
    a = load_franco(_write(lf, _line(ARZ), _line(CONTROL), newline="\n"))
    b = load_franco(_write(crlf, _line(ARZ), _line(CONTROL), newline="\r\n"))
    assert franco_hash(a) == franco_hash(b)
    assert len(franco_hash(a)) == 64

    noted = [a[0].model_copy(update={"note": "changed"}), a[1]]
    assert franco_hash(noted) == franco_hash(a)
    for field, value in [("arabic", "أنا مش فاهمة"), ("split", "test"), ("meaning", "x")]:
        changed = [a[0].model_copy(update={field: value}), a[1]]
        assert franco_hash(changed) != franco_hash(a), field
