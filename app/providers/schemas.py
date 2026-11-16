"""Structured-output schema shared by every LLM provider."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

LanguageCode = Literal["ar", "arz", "en", "fr", "it", "de", "es"]


class TranslationOutput(BaseModel):
    """What the model must return. Both providers enforce this via JSON schema."""

    detected_source: LanguageCode = Field(
        description=(
            "Language code of the source text. 'ar' = Modern Standard Arabic, "
            "'arz' = Egyptian Arabic, 'en' = English, 'fr' = French, 'it' = Italian, "
            "'de' = German, 'es' = Spanish."
        )
    )
    translation: str = Field(
        description="The translated text only. No notes, labels, quotes or explanations."
    )


def translation_json_schema() -> dict[str, object]:
    """JSON schema in the plain form both provider APIs accept."""
    schema = TranslationOutput.model_json_schema()
    schema.pop("title", None)
    schema["additionalProperties"] = False
    return schema
