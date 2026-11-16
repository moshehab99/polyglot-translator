from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors as genai_errors

from app.languages import get_language
from app.providers.base import (
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.providers.gemini_provider import GeminiProvider

EN = get_language("en")
ARZ = get_language("arz")

GOOD_JSON = '{"detected_source": "arz", "translation": "إزيك؟"}'


def make_client(result: object = None, side_effect: BaseException | None = None) -> MagicMock:
    client = MagicMock()
    client.aio.interactions.create = AsyncMock(return_value=result, side_effect=side_effect)
    return client


def interaction(text: str | None, status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(output_text=text, status=status)


def client_error(code: int, message: str = "boom") -> genai_errors.ClientError:
    return genai_errors.ClientError(
        code, {"error": {"code": code, "message": message, "status": "ERR"}}
    )


async def test_translate_sends_verified_request_shape() -> None:
    client = make_client(interaction(GOOD_JSON))
    provider = GeminiProvider(client=client, model="gemini-3.5-flash-lite", timeout_s=12.5)

    result = await provider.translate("how are you?", None, ARZ)

    assert result.translation == "إزيك؟"
    assert result.detected_source is ARZ
    create = client.aio.interactions.create
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["model"] == "gemini-3.5-flash-lite"
    assert kwargs["store"] is False
    assert kwargs["timeout"] == 12.5
    assert "Egyptian Arabic" in kwargs["system_instruction"]
    assert "Modern Standard Arabic" in kwargs["system_instruction"]
    assert "<text>\nhow are you?\n</text>" in kwargs["input"]
    rf = kwargs["response_format"]
    assert rf["type"] == "text"
    assert rf["mime_type"] == "application/json"
    assert set(rf["schema"]["required"]) == {"detected_source", "translation"}
    assert rf["schema"]["additionalProperties"] is False
    assert "arz" in rf["schema"]["properties"]["detected_source"]["enum"]


async def test_explicit_source_is_trusted_over_model_echo() -> None:
    client = make_client(interaction('{"detected_source": "ar", "translation": "Hello"}'))
    provider = GeminiProvider(client=client, model="m")

    result = await provider.translate("إزيك", ARZ, EN)

    assert result.detected_source is ARZ
    assert result.translation == "Hello"


async def test_auto_detect_uses_model_code() -> None:
    client = make_client(interaction('{"detected_source": "ar", "translation": "Hello"}'))
    result = await GeminiProvider(client=client, model="m").translate("مرحبا", None, EN)
    assert result.detected_source.code == "ar"


async def test_429_maps_to_rate_limit() -> None:
    client = make_client(side_effect=client_error(429, "Resource has been exhausted"))
    with pytest.raises(ProviderRateLimitError) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert "429" in exc_info.value.detail
    assert exc_info.value.provider == "gemini"


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_codes_map_to_auth_error(code: int) -> None:
    client = make_client(side_effect=client_error(code, "API key not valid"))
    with pytest.raises(ProviderAuthError) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert "API key not valid" in exc_info.value.detail


async def test_other_client_error_and_server_error_are_unavailable() -> None:
    for exc in (client_error(400), genai_errors.ServerError(503, {"error": {"message": "down"}})):
        client = make_client(side_effect=exc)
        with pytest.raises(ProviderUnavailableError):
            await GeminiProvider(client=client, model="m").translate("x", None, EN)


async def test_network_failure_is_unavailable() -> None:
    client = make_client(side_effect=ConnectionError("dns"))
    with pytest.raises(ProviderUnavailableError) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert "ConnectionError" in exc_info.value.detail


@pytest.mark.parametrize(
    "text",
    [None, "", "not json", '{"translation": "x"}', '{"detected_source": "xx", "translation": "x"}',
     '{"detected_source": "en", "translation": "   "}'],
)
async def test_bad_output_variants(text: str | None) -> None:
    client = make_client(interaction(text, status="incomplete"))
    with pytest.raises(ProviderBadOutputError):
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
