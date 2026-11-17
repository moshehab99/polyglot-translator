"""FastAPI dependencies.

``get_settings`` and ``get_provider`` are the two override points for tests.
The provider is built once at startup (see ``app.main``) and read from ``app.state``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.config import Settings, get_settings
from app.providers.base import TranslationProvider
from app.services.translation_service import TranslationService

__all__ = [
    "Settings",
    "TranslationProvider",
    "get_provider",
    "get_settings",
    "get_translation_service",
]


def get_provider(request: Request) -> TranslationProvider:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:  # pragma: no cover - lifespan always sets it
        raise RuntimeError("Translation provider was not initialised at startup")
    return provider


def get_translation_service(
    provider: Annotated[TranslationProvider, Depends(get_provider)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> TranslationService:
    return TranslationService(provider=provider, max_chars=settings.max_chars)
