import inspect
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


async def test_request_kwargs_match_installed_sdk_signature() -> None:
    """Catch kwargs the installed google-genai would reject.

    ``create`` declares a few named parameters and forwards everything else as the
    request body (``**body``), so every kwarg must be either a declared parameter or
    a field of the typed request body ``CreateModelInteractionParam``.
    """
    from google import genai
    from google.genai.interactions import CreateModelInteractionParam

    client = make_client(interaction(GOOD_JSON))
    await GeminiProvider(client=client, model="m", timeout_s=3).translate("x", None, EN)
    sent = client.aio.interactions.create.await_args.kwargs

    real_create = genai.Client(api_key="unused").aio.interactions.create
    declared = inspect.signature(real_create).parameters
    body_fields = set(CreateModelInteractionParam.__annotations__)
    for name in sent:
        is_declared = name in declared and declared[name].kind is not inspect.Parameter.VAR_KEYWORD
        assert is_declared or name in body_fields, f"unsupported kwarg: {name}"
    # The declared ones must bind (catches wrong names like `timeout_s`).
    inspect.signature(real_create).bind(**sent)
    assert "timeout" in declared and declared["timeout"].kind is inspect.Parameter.KEYWORD_ONLY


@pytest.mark.parametrize("code", [401, 403])
async def test_auth_codes_map_to_auth_error(code: int) -> None:
    client = make_client(side_effect=client_error(code, "API key not valid"))
    with pytest.raises(ProviderAuthError) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert "API key not valid" in exc_info.value.detail


async def test_400_api_key_invalid_reason_maps_to_auth_error() -> None:
    payload = {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "API_KEY_INVALID",
                    "domain": "googleapis.com",
                    "metadata": {"service": "generativelanguage.googleapis.com"},
                }
            ],
        }
    }
    client = make_client(side_effect=genai_errors.ClientError(400, payload))
    with pytest.raises(ProviderAuthError) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert "HTTP 400" in exc_info.value.detail


async def test_400_with_invalid_key_message_but_no_reason_maps_to_auth_error() -> None:
    client = make_client(side_effect=client_error(400, "API key not valid. Please pass a valid API key."))
    with pytest.raises(ProviderAuthError):
        await GeminiProvider(client=client, model="m").translate("x", None, EN)


async def test_plain_400_stays_unavailable() -> None:
    client = make_client(side_effect=client_error(400, "Invalid JSON payload received."))
    with pytest.raises(ProviderUnavailableError):
        await GeminiProvider(client=client, model="m").translate("x", None, EN)


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


# --- Interactions API exception family -----------------------------------------
# The Interactions surface raises an OpenAI-style family (APIStatusError with
# `status_code` + `body`) that is only importable from a private module. The provider
# duck-types it; these tests build the real classes to prove the mapping holds.

from google.genai._gaos.lib import compat_errors  # noqa: E402  (test-only private import)

INVALID_KEY_BODY = [
    {
        "error": {
            "code": 400,
            "message": "API key not valid. Please pass a valid API key.",
            "status": "INVALID_ARGUMENT",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                    "reason": "API_KEY_INVALID",
                    "domain": "googleapis.com",
                }
            ],
        }
    }
]


def compat_status_error(
    cls: type, status: int, message: str, body: object
) -> Exception:
    httpx = compat_errors.httpx
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1/interactions")
    response = httpx.Response(status, request=request)
    return cls(message, response=response, body=body)


async def test_interactions_400_api_key_invalid_maps_to_auth_error() -> None:
    exc = compat_status_error(
        compat_errors.BadRequestError, 400, "Error code: 400 - [...]", INVALID_KEY_BODY
    )
    client = make_client(side_effect=exc)
    with pytest.raises(ProviderAuthError) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert exc_info.value.detail.startswith("HTTP 400")


@pytest.mark.parametrize(
    ("cls", "status", "expected"),
    [
        (compat_errors.RateLimitError, 429, ProviderRateLimitError),
        (compat_errors.AuthenticationError, 401, ProviderAuthError),
        (compat_errors.PermissionDeniedError, 403, ProviderAuthError),
        (compat_errors.InternalServerError, 503, ProviderUnavailableError),
        (compat_errors.BadRequestError, 400, ProviderUnavailableError),
    ],
)
async def test_interactions_status_errors_are_mapped(
    cls: type, status: int, expected: type[Exception]
) -> None:
    exc = compat_status_error(cls, status, "upstream text", {"error": {"message": "m"}})
    client = make_client(side_effect=exc)
    with pytest.raises(expected) as exc_info:
        await GeminiProvider(client=client, model="m").translate("x", None, EN)
    assert str(status) in exc_info.value.detail


async def test_interactions_connection_and_timeout_errors_are_unavailable() -> None:
    httpx = compat_errors.httpx
    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/v1/interactions")
    for exc in (compat_errors.APIConnectionError(request=request), compat_errors.APITimeoutError(request)):
        client = make_client(side_effect=exc)
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await GeminiProvider(client=client, model="m").translate("x", None, EN)
        assert type(exc).__name__ in exc_info.value.detail
