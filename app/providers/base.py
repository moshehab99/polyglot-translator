"""Provider interface and the error hierarchy shared by all providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.languages import Language


@dataclass(frozen=True, slots=True)
class TranslationResult:
    translation: str
    detected_source: Language


class ProviderError(Exception):
    """Base class for all provider failures.

    ``detail`` holds the raw upstream information (status codes, messages).
    It is for server-side logging only and must never be sent to the client.
    """

    def __init__(self, detail: str, *, provider: str = "unknown") -> None:
        super().__init__(detail)
        self.detail = detail
        self.provider = provider


class ProviderAuthError(ProviderError):
    """The server's API key is invalid, missing or lacks permission."""


class ProviderRateLimitError(ProviderError):
    """The provider rejected the request because of rate limits / quota."""


class ProviderUnavailableError(ProviderError):
    """The provider could not be reached or returned a server-side error."""


class ProviderBadOutputError(ProviderError):
    """The provider answered, but not with a usable translation."""


class TranslationProvider(ABC):
    """Translate text between two supported languages, or convert Franco-Arabic to Arabic script.

    ``source`` is ``None`` when the caller wants the provider to auto-detect it.
    Implementations raise only ``ProviderError`` subclasses.
    """

    name: str = "base"

    @abstractmethod
    async def translate(
        self, text: str, source: Language | None, target: Language
    ) -> TranslationResult: ...

    @abstractmethod
    async def to_arabic_script(self, text: str) -> str:
        """Rewrite Franco-Arabic words in Arabic script; keep everything else as written."""
