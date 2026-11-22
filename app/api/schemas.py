"""Pydantic models for the HTTP API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.languages import AUTO, LANGUAGE_CODES

LanguageCode = Literal["ar", "arz", "en", "fr", "it", "de", "es"]
SourceCode = Literal["auto", "ar", "arz", "en", "fr", "it", "de", "es"]

assert set(LANGUAGE_CODES) == set(LanguageCode.__args__)  # keep in sync with languages.py
assert AUTO in SourceCode.__args__


class TranslateRequest(BaseModel):
    text: str = Field(description="Text to translate.")
    source: SourceCode = Field(default="auto", description="Source language code or 'auto'.")
    target: LanguageCode = Field(description="Target language code.")


class TranslateResponse(BaseModel):
    translation: str
    detected_source: LanguageCode
    source_rtl: bool
    target_rtl: bool


class ArabicScriptRequest(BaseModel):
    text: str = Field(description="Text whose Franco-Arabic words are written in Arabic script.")


class ArabicScriptResponse(BaseModel):
    result: str


class HealthResponse(BaseModel):
    status: str
    provider: str


class ErrorResponse(BaseModel):
    detail: str
