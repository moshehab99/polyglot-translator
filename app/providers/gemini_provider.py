"""Google Gemini provider (default) using the google-genai Interactions API.

Verified against google-genai 3.4.0: ``client.aio.interactions.create`` accepts
``model``, ``input``, ``system_instruction``, ``response_format`` and ``store`` as
keyword arguments, and the returned ``Interaction`` exposes ``output_text``.
"""

from __future__ import annotations

from typing import Any, TypeVar

from google.genai import errors as genai_errors
from pydantic import BaseModel, ValidationError

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
from app.providers.prompts import (
    build_script_system_prompt,
    build_script_user_message,
    build_system_prompt,
    build_user_message,
)
from app.providers.schemas import ScriptOutput, TranslationOutput, json_schema_for

logger = get_logger("providers.gemini")

_Output = TypeVar("_Output", bound=BaseModel)

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
        output = await self._generate(
            build_system_prompt(source, target),
            build_user_message(text, source, target),
            TranslationOutput,
        )
        translation = output.translation.strip()
        if not translation:
            raise ProviderBadOutputError("empty translation", provider=self.name)
        detected = source if source is not None else get_language(output.detected_source)
        return TranslationResult(translation=translation, detected_source=detected)

    async def to_arabic_script(self, text: str) -> str:
        output = await self._generate(
            build_script_system_prompt(), build_script_user_message(text), ScriptOutput
        )
        converted = output.converted.strip()
        if not converted:
            raise ProviderBadOutputError("empty conversion", provider=self.name)
        return converted

    async def _generate(self, system: str, user: str, output_model: type[_Output]) -> _Output:
        """One structured-output request: SDK errors mapped, output parsed into ``output_model``."""
        try:
            interaction = await self._client.aio.interactions.create(
                model=self._model,
                system_instruction=system,
                input=user,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": json_schema_for(output_model),
                },
                store=False,
                timeout=self._timeout_s,
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc

        raw = getattr(interaction, "output_text", None)
        if not raw:
            status = getattr(interaction, "status", None)
            raise ProviderBadOutputError(
                f"empty output_text (status={status!r})", provider=self.name
            )
        try:
            return output_model.model_validate_json(raw)
        except ValidationError as exc:
            raise ProviderBadOutputError(
                f"invalid structured output: {exc.errors()[:3]}", provider=self.name
            ) from exc

    def _map_exception(self, exc: Exception) -> ProviderError:
        """Classify any failure raised by the SDK.

        google-genai raises two families:
        - ``google.genai.errors.APIError`` (``code`` / ``status`` / ``message`` / ``details``)
          from the classic ``models`` surface, and
        - an OpenAI-style family for the Interactions API whose status errors carry
          ``status_code`` and ``body`` (only importable from a private module, so we
          duck-type it). Connection/timeout errors in that family carry no status.
        """
        if isinstance(exc, genai_errors.APIError):
            return self._classify(exc.code, exc.message or "", exc.details, exc.status)
        status_code = getattr(exc, "status_code", None)
        if isinstance(status_code, int):
            message = getattr(exc, "message", None) or str(exc)
            return self._classify(status_code, message, getattr(exc, "body", None), None)
        logger.exception("Gemini request failed without an HTTP status")
        return ProviderUnavailableError(f"{type(exc).__name__}: {exc}", provider=self.name)

    def _classify(
        self, code: int, message: str, payload: Any, status: str | None
    ) -> ProviderError:
        detail = f"HTTP {code} {status or ''}: {message}".replace("  ", " ").strip()
        if code == 429:
            return ProviderRateLimitError(detail, provider=self.name)
        if code in _AUTH_STATUS_CODES or _is_invalid_api_key(code, message, payload):
            return ProviderAuthError(detail, provider=self.name)
        return ProviderUnavailableError(detail, provider=self.name)


def _is_invalid_api_key(code: int, message: str, payload: Any) -> bool:
    """Gemini reports a bad key as HTTP 400 with reason ``API_KEY_INVALID``.

    The reason lives in ``error.details[].reason`` of the JSON body (``payload`` is that
    body, or a one-element list wrapping it); the message is usually
    "API key not valid. Please pass a valid API key.". Check both.
    """
    if code != 400:
        return False
    if _INVALID_KEY_REASON in _reasons(payload):
        return True
    lowered = message.lower()
    return "api key not valid" in lowered or "api_key_invalid" in lowered


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
