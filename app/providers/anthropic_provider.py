"""Anthropic Claude provider using ``messages.parse`` structured outputs.

Verified against anthropic 2.9.0: ``AsyncAnthropic().messages.parse`` accepts
``model``, ``max_tokens``, ``system``, ``messages``, ``output_format`` (a Pydantic
model class) and ``output_config``; the response exposes ``parsed_output`` and
``stop_reason``.
"""

from __future__ import annotations

from typing import Any

import anthropic

from app.languages import Language, get_language
from app.logging import get_logger
from app.providers.base import (
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderError,
    ProviderRateLimitError,
    ProviderUnavailableError,
    TranslationProvider,
    TranslationResult,
)
from app.providers.prompts import build_system_prompt, build_user_message
from app.providers.schemas import TranslationOutput

logger = get_logger("providers.anthropic")

# Translation is not a hard reasoning task; keep latency and cost low.
_EFFORT = "low"
_MAX_TOKENS = 4096


class AnthropicProvider(TranslationProvider):
    name = "anthropic"

    def __init__(self, client: Any, model: str) -> None:
        """``client`` is an ``anthropic.AsyncAnthropic`` (duck-typed for tests)."""
        self._client = client
        self._model = model

    async def translate(
        self, text: str, source: Language | None, target: Language
    ) -> TranslationResult:
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=build_system_prompt(source, target),
                messages=[{"role": "user", "content": build_user_message(text, source, target)}],
                output_format=TranslationOutput,
                output_config={"effort": _EFFORT},
            )
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            raise ProviderAuthError(self._detail(exc), provider=self.name) from exc
        except anthropic.RateLimitError as exc:
            raise ProviderRateLimitError(self._detail(exc), provider=self.name) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderUnavailableError(self._detail(exc), provider=self.name) from exc
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise ProviderUnavailableError(
                f"{type(exc).__name__}: {exc}", provider=self.name
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:
            logger.exception("Anthropic request failed unexpectedly")
            raise ProviderUnavailableError(
                f"{type(exc).__name__}: {exc}", provider=self.name
            ) from exc

        return self._parse(response, source)

    @staticmethod
    def _detail(exc: anthropic.APIStatusError) -> str:
        return f"HTTP {exc.status_code}: {exc.message}"

    def _parse(self, response: Any, source: Language | None) -> TranslationResult:
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason in {"refusal", "max_tokens"}:
            raise ProviderBadOutputError(f"stop_reason={stop_reason}", provider=self.name)
        output = getattr(response, "parsed_output", None)
        if not isinstance(output, TranslationOutput):
            raise ProviderBadOutputError(
                f"missing parsed_output (stop_reason={stop_reason!r})", provider=self.name
            )
        translation = output.translation.strip()
        if not translation:
            raise ProviderBadOutputError("empty translation", provider=self.name)
        detected = source if source is not None else get_language(output.detected_source)
        return TranslationResult(translation=translation, detected_source=detected)
