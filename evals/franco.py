"""Franco-Arabic (Arabizi) eval: Egyptian Arabic typed in Latin script.

The dataset is JSON Lines, one object per line::

    {"id": "f001", "text": "ana msh fahem enta 3ayez eh", "label": "arz",
     "arabic": "أنا مش فاهم إنت عايز إيه", "meaning": "I don't understand what you want",
     "tags": ["clear", "numerals"], "split": "dev", "note": "optional"}

See ``evals/README.md`` (Franco section) for the labelling policy.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evals import metrics
from evals.dataset import check_text, load_dataset

DEFAULT_FRANCO_DATASET = Path(__file__).parent / "data" / "franco.jsonl"

FRANCO_LABELS: tuple[str, ...] = ("arz", "ar", "en", "fr", "it", "de", "es")
ARABIC_LABELS = frozenset({"ar", "arz"})

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
