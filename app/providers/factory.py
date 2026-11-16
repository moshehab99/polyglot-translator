"""Build the configured ``TranslationProvider`` from ``Settings``."""

from __future__ import annotations

from app.config import Settings
from app.providers.base import TranslationProvider


def build_provider(settings: Settings) -> TranslationProvider:
    key = settings.active_api_key
    if key is None:  # Settings validation already guarantees this; keep mypy honest.
        raise ValueError(f"No API key configured for provider {settings.provider!r}")
    secret = key.get_secret_value()

    if settings.provider == "gemini":
        from google import genai

        from app.providers.gemini_provider import GeminiProvider

        client = genai.Client(api_key=secret)
        return GeminiProvider(
            client=client, model=settings.gemini_model, timeout_s=settings.request_timeout_s
        )

    if settings.provider == "anthropic":
        import anthropic

        from app.providers.anthropic_provider import AnthropicProvider

        client = anthropic.AsyncAnthropic(api_key=secret, timeout=settings.request_timeout_s)
        return AnthropicProvider(client=client, model=settings.anthropic_model)

    raise ValueError(f"Unknown provider: {settings.provider!r}")
