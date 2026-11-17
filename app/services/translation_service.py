"""Translation use-case: validation, then delegate to the configured provider."""

from __future__ import annotations

from app.languages import AUTO, Language, get_language, is_supported
from app.providers.base import TranslationProvider, TranslationResult


class TranslationValidationError(ValueError):
    """User input is invalid. The message is safe to show to the client."""


class TranslationService:
    def __init__(self, provider: TranslationProvider, max_chars: int) -> None:
        self._provider = provider
        self._max_chars = max_chars

    @property
    def max_chars(self) -> int:
        return self._max_chars

    async def translate(self, text: str, source_code: str, target_code: str) -> TranslationResult:
        cleaned = text.strip()
        if not cleaned:
            raise TranslationValidationError("Please enter some text to translate.")
        if len(cleaned) > self._max_chars:
            raise TranslationValidationError(
                f"Text is too long: {len(cleaned)} characters (maximum {self._max_chars})."
            )
        if not is_supported(target_code):
            raise TranslationValidationError(f"Unsupported target language: {target_code!r}.")
        target = get_language(target_code)

        source: Language | None
        if source_code == AUTO:
            source = None
        elif is_supported(source_code):
            source = get_language(source_code)
        else:
            raise TranslationValidationError(f"Unsupported source language: {source_code!r}.")

        if source is not None and source.code == target.code:
            raise TranslationValidationError(
                "Source and target languages are the same. Pick a different target."
            )

        return await self._provider.translate(cleaned, source, target)
