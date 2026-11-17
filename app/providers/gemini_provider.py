"""Google Gemini provider (default) using the google-genai Interactions API.

Verified against google-genai 3.4.0: ``client.aio.interactions.create`` accepts
``model``, ``input``, ``system_instruction``, ``response_format`` and ``store`` as
keyword arguments, and the returned ``Interaction`` exposes ``output_text``.
"""

from __future__ import annotations

from typing import Any

from google.genai import errors as genai_errors
from pydantic import ValidationError

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
from app.providers.schemas import TranslationOutput, translation_json_schema

logger = get_logger("providers.gemini")

_AUTH_STATUS_CODES = frozenset({401, 403})
_INVALID_KEY_REASON = "API_KEY_INVALID"


class GeminiProvider(TranslationProvider):
    name = "gemini"

    def __init__(self, client: Any, model: str, timeout_s: float = 60.0) -> None:
        """``client`` is a ``google.genai.Client`` (duck-typed so tests can mock it)."""
        self._client = client
        self._model = model
        self._timeout_s = timeout_s

    async def translate(
        self, text: str, source: Language | None, target: Language
    ) -> TranslationResult:
        try:
            interaction = await self._client.aio.interactions.create(
                model=self._model,
                system_instruction=build_system_prompt(source, target),
                input=build_user_message(text, source, target),
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": translation_json_schema(),
                },
                store=False,
                timeout=self._timeout_s,
            )
        except genai_errors.APIError as exc:
            raise self._map_api_error(exc) from exc
        except ProviderError:
            raise
        except Exception as exc:  # network / timeout / SDK-internal failures
            logger.exception("Gemini request failed unexpectedly")
            raise ProviderUnavailableError(
                f"{type(exc).__name__}: {exc}", provider=self.name
            ) from exc

        return self._parse(interaction, source)

    def _map_api_error(self, exc: genai_errors.APIError) -> ProviderError:
        detail = f"HTTP {exc.code} {exc.status or ''}: {exc.message or ''}".strip()
        if exc.code == 429:
            return ProviderRateLimitError(detail, provider=self.name)
        if exc.code in _AUTH_STATUS_CODES or _is_invalid_api_key(exc):
            return ProviderAuthError(detail, provider=self.name)
        return ProviderUnavailableError(detail, provider=self.name)

    def _parse(self, interaction: Any, source: Language | None) -> TranslationResult:
        raw = getattr(interaction, "output_text", None)
        if not raw:
            status = getattr(interaction, "status", None)
            raise ProviderBadOutputError(
                f"empty output_text (status={status!r})", provider=self.name
            )
        try:
            output = TranslationOutput.model_validate_json(raw)
        except ValidationError as exc:
            raise ProviderBadOutputError(
                f"invalid structured output: {exc.errors()[:3]}", provider=self.name
            ) from exc

        translation = output.translation.strip()
        if not translation:
            raise ProviderBadOutputError("empty translation", provider=self.name)
        detected = source if source is not None else get_language(output.detected_source)
        return TranslationResult(translation=translation, detected_source=detected)


def _is_invalid_api_key(exc: genai_errors.APIError) -> bool:
    """Gemini reports a bad key as HTTP 400 with reason ``API_KEY_INVALID``.

    The reason lives in ``error.details[].reason`` of the JSON body; the message is
    usually "API key not valid. Please pass a valid API key.". Check both.
    """
    if exc.code != 400:
        return False
    if _INVALID_KEY_REASON in _reasons(exc.details):
        return True
    message = (exc.message or "").lower()
    return "api key not valid" in message or "api_key_invalid" in message


def _reasons(details: Any) -> set[str]:
    """Collect every ``reason`` string nested anywhere in the error payload."""
    found: set[str] = set()
    stack = [details]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            reason = node.get("reason")
            if isinstance(reason, str):
                found.add(reason)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found
