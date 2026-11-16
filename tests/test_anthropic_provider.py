from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anthropic
import httpx2
import pytest

from app.languages import get_language
from app.providers.anthropic_provider import AnthropicProvider
from app.providers.base import (
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.providers.schemas import TranslationOutput

EN = get_language("en")
AR = get_language("ar")
FR = get_language("fr")


def make_client(result: object = None, side_effect: BaseException | None = None) -> MagicMock:
    client = MagicMock()
    client.messages.parse = AsyncMock(return_value=result, side_effect=side_effect)
    return client


def response(parsed: object, stop_reason: str = "end_turn") -> SimpleNamespace:
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason)


def status_error(cls: type[anthropic.APIStatusError], status: int, message: str) -> anthropic.APIStatusError:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    http_response = httpx2.Response(status, request=request)
    return cls(message, response=http_response, body={"error": {"message": message}})


async def test_translate_sends_verified_request_shape() -> None:
    client = make_client(response(TranslationOutput(detected_source="ar", translation="Bonjour")))
    provider = AnthropicProvider(client=client, model="claude-opus-5")

    result = await provider.translate("مرحبا", None, FR)

    assert result.translation == "Bonjour"
    assert result.detected_source is AR
    kwargs = client.messages.parse.await_args.kwargs
    assert kwargs["model"] == "claude-opus-5"
    assert kwargs["output_format"] is TranslationOutput
    assert kwargs["output_config"] == {"effort": "low"}
    assert kwargs["max_tokens"] > 0
    assert "Egyptian Arabic" in kwargs["system"] and "Modern Standard Arabic" in kwargs["system"]
    assert kwargs["messages"] == [
        {"role": "user", "content": "Source: auto-detect\nTarget: French\n\n<text>\nمرحبا\n</text>"}
    ]


async def test_explicit_source_is_trusted() -> None:
    client = make_client(response(TranslationOutput(detected_source="en", translation="x")))
    result = await AnthropicProvider(client=client, model="m").translate("t", AR, EN)
    assert result.detected_source is AR


@pytest.mark.parametrize(
    ("cls", "status", "expected"),
    [
        (anthropic.AuthenticationError, 401, ProviderAuthError),
        (anthropic.PermissionDeniedError, 403, ProviderAuthError),
        (anthropic.RateLimitError, 429, ProviderRateLimitError),
        (anthropic.InternalServerError, 500, ProviderUnavailableError),
        (anthropic.BadRequestError, 400, ProviderUnavailableError),
    ],
)
async def test_status_errors_are_mapped(
    cls: type[anthropic.APIStatusError], status: int, expected: type[Exception]
) -> None:
    client = make_client(side_effect=status_error(cls, status, "upstream says no"))
    with pytest.raises(expected) as exc_info:
        await AnthropicProvider(client=client, model="m").translate("x", None, EN)
    assert str(status) in exc_info.value.detail
    assert "upstream says no" in exc_info.value.detail
    assert exc_info.value.provider == "anthropic"


async def test_connection_error_is_unavailable() -> None:
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    client = make_client(side_effect=anthropic.APIConnectionError(request=request))
    with pytest.raises(ProviderUnavailableError):
        await AnthropicProvider(client=client, model="m").translate("x", None, EN)


@pytest.mark.parametrize(
    "resp",
    [
        response(None),
        response(TranslationOutput(detected_source="en", translation="x"), stop_reason="refusal"),
        response(TranslationOutput(detected_source="en", translation="x"), stop_reason="max_tokens"),
        response(TranslationOutput(detected_source="en", translation="  ")),
    ],
)
async def test_bad_output_variants(resp: SimpleNamespace) -> None:
    client = make_client(resp)
    with pytest.raises(ProviderBadOutputError):
        await AnthropicProvider(client=client, model="m").translate("x", None, EN)
