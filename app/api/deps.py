"""FastAPI dependencies.

``get_settings`` and ``get_provider`` are the two override points for tests.
The provider is built once at startup (see ``app.main``) and read from ``app.state``.
"""

from __future__ import annotations

from fastapi import Request

from app.config import Settings, get_settings
from app.providers.base import TranslationProvider

__all__ = ["Settings", "TranslationProvider", "get_provider", "get_settings"]


def get_provider(request: Request) -> TranslationProvider:
    provider = getattr(request.app.state, "provider", None)
    if provider is None:  # pragma: no cover - lifespan always sets it
        raise RuntimeError("Translation provider was not initialised at startup")
    return provider
