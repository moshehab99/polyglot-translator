"""Dialect dataset: the ``EvalItem`` schema, loading and hashing.

The dataset is JSON Lines, one object per line:
``{"id": "d001", "text": "...", "label": "arz", "tags": ["short"], "note": "optional"}``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

DEFAULT_DATASET = Path(__file__).parent / "data" / "dialect.jsonl"

LABELS: tuple[str, ...] = ("ar", "arz")

# Fixed tag vocabulary. An unknown tag is a loading error.
TAGS: frozenset[str] = frozenset(
    {
        "clear",  # clear, typical example of its variety
        "short",  # 1-3 words
        "shared",  # greeting / religious phrase used by both varieties (always ar)
        "topic_swap",  # MSA on casual topics, or Egyptian on news / work / serious topics
        "no_markers",  # Egyptian without any marker word listed in prompts.py
        "code_switch",  # mixed with English words
        "chat_spelling",  # no hamzas, final ى for ي, elongated letters
        "polite",  # polite / work-register Egyptian
        "long",  # 2-3 sentences
    }
)

MAX_TEXT_CHARS = 5000


class DatasetError(ValueError):
    """The dataset file is malformed. The message names the file and line."""


def check_text(value: str) -> str:
    """Shared ``text`` rules: non-empty, stripped, one line, at most MAX_TEXT_CHARS."""
    if not value.strip():
        raise ValueError("text is empty")
    if value != value.strip():
        raise ValueError("text has leading or trailing whitespace")
    if "\n" in value or "\r" in value:
        raise ValueError("text must be a single line")
    if len(value) > MAX_TEXT_CHARS:
        raise ValueError(f"text is longer than {MAX_TEXT_CHARS} characters")
    return value


class EvalItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^d\d{3,}$")
    text: str
    label: Literal["ar", "arz"]
    tags: tuple[str, ...] = ()
    note: str | None = None

    @field_validator("text")
    @classmethod
    def _check_text(cls, value: str) -> str:
        return check_text(value)

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        unknown = sorted(set(value) - TAGS)
        if unknown:
            raise ValueError(f"unknown tag(s): {', '.join(unknown)}")
        if len(set(value)) != len(value):
            raise ValueError("duplicate tags")
        return value


ItemT = TypeVar("ItemT", bound=BaseModel)


def _normalized(text: str) -> str:
    return " ".join(text.split())


def load_dataset(path: str | Path, model: type[ItemT] = EvalItem) -> list[ItemT]:  # type: ignore[assignment]
    """Load and validate a JSONL dataset. Errors name the file and the 1-based line.

    ``model`` is the item schema; it needs ``id`` and ``text`` fields. Defaults to the
    dialect ``EvalItem``.
    """
    path = Path(path)
    items: list[ItemT] = []
    seen_ids: dict[str, int] = {}
    seen_texts: dict[str, int] = {}

    with open(path, encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            where = f"{path}:{lineno}"
            if lineno == 1 and raw.startswith("﻿"):
                raise DatasetError(f"{where}: file starts with a UTF-8 BOM; save it without BOM")
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise DatasetError(f"{where}: invalid JSON: {exc.msg}") from exc
            if not isinstance(data, dict):
                raise DatasetError(f"{where}: expected a JSON object")
            try:
                item = model.model_validate(data)
            except ValidationError as exc:
                problems = "; ".join(
                    f"{'.'.join(str(p) for p in err['loc']) or 'item'}: {err['msg']}"
                    for err in exc.errors()
                )
                raise DatasetError(f"{where}: {problems}") from exc

            if item.id in seen_ids:  # type: ignore[attr-defined]
                raise DatasetError(
                    f"{where}: duplicate id {item.id!r} (first seen on line {seen_ids[item.id]})"
                )
            key = _normalized(item.text)
            if key in seen_texts:
                raise DatasetError(
                    f"{where}: duplicate text (first seen on line {seen_texts[key]})"
                )
            seen_ids[item.id] = lineno
            seen_texts[key] = lineno
            items.append(item)
    return items


def dataset_hash(items: list[EvalItem]) -> str:
    """sha256 of the parsed items as canonical JSON (notes excluded).

    Computed from parsed values, so line endings or key order in the file don't matter.
    """
    payload = [
        {"id": item.id, "text": item.text, "label": item.label, "tags": list(item.tags)}
        for item in items
    ]
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
