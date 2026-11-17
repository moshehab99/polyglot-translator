import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.deps import get_provider
from app.api.errors import BAD_OUTPUT_MESSAGE, RATE_LIMIT_MESSAGE, UNAVAILABLE_MESSAGE
from app.config import get_settings
from app.languages import get_language
from app.main import create_app
from app.providers.base import (
    ProviderAuthError,
    ProviderBadOutputError,
    ProviderRateLimitError,
    ProviderUnavailableError,
)
from app.providers.gemini_provider import GeminiProvider
from tests.conftest import FakeProvider, make_settings

SECRET_UPSTREAM = "HTTP 400: API key not valid. Please pass a valid key sk-REAL-KEY-123"


def client_with(provider: FakeProvider, **settings_overrides: object) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: make_settings(**settings_overrides)
    app.dependency_overrides[get_provider] = lambda: provider
    return TestClient(app, raise_server_exceptions=False)


# --- health -------------------------------------------------------------------


def test_health_reports_provider_only(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "provider": "gemini"}
    assert "key" not in response.text.lower()
    assert "gemini-3.5" not in response.text


def test_health_reflects_anthropic_provider() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: make_settings(
        provider="anthropic", gemini_api_key=None, anthropic_api_key="sk-test"
    )
    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"status": "ok", "provider": "anthropic"}


# --- startup ------------------------------------------------------------------


def test_startup_builds_real_provider_from_overridden_settings() -> None:
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: make_settings()
    with TestClient(app) as client:
        assert isinstance(client.app.state.provider, GeminiProvider)  # type: ignore[attr-defined]


def test_startup_fails_fast_without_api_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)  # no .env here; env vars are cleared by the autouse fixture
    app = create_app()
    with pytest.raises(ValidationError, match="GEMINI_API_KEY"):
        with TestClient(app):
            pass
    assert "Invalid configuration" in caplog.text


# --- translate: happy paths ---------------------------------------------------


def test_translate_with_explicit_source(client: TestClient, fake_provider: FakeProvider) -> None:
    fake_provider.translation = "Bonjour"
    response = client.post(
        "/api/translate", json={"text": "Hello", "source": "en", "target": "fr"}
    )
    assert response.status_code == 200
    assert response.json() == {
        "translation": "Bonjour",
        "detected_source": "en",
        "source_rtl": False,
        "target_rtl": False,
    }
    assert fake_provider.calls == [("Hello", get_language("en"), get_language("fr"))]


def test_translate_auto_detects_egyptian_and_reports_rtl_flags(
    client: TestClient, fake_provider: FakeProvider
) -> None:
    fake_provider.translation = "How are you?"
    fake_provider.detected = "arz"
    response = client.post("/api/translate", json={"text": "إزيك؟", "target": "en"})
    assert response.status_code == 200
    body = response.json()
    assert body["detected_source"] == "arz"
    assert body["source_rtl"] is True
    assert body["target_rtl"] is False
    assert fake_provider.calls[0][1] is None  # auto → provider detects


def test_translate_into_arabic_sets_target_rtl(client: TestClient, fake_provider: FakeProvider) -> None:
    fake_provider.translation = "مرحبا"
    body = client.post("/api/translate", json={"text": "Hi", "source": "en", "target": "ar"}).json()
    assert body["target_rtl"] is True
    assert body["translation"] == "مرحبا"


# --- translate: validation (422) ----------------------------------------------


@pytest.mark.parametrize(
    ("payload", "fragment"),
    [
        ({"text": "   ", "target": "en"}, "enter some text"),
        ({"text": "Hi", "source": "en", "target": "en"}, "same"),
        ({"text": "Hi", "source": "xx", "target": "en"}, "source"),
        ({"text": "Hi", "target": "xx"}, "target"),
        ({"target": "en"}, "text"),
        ({"text": "Hi"}, "target"),
    ],
)
def test_validation_errors_return_422_with_single_detail_string(
    client: TestClient, fake_provider: FakeProvider, payload: dict, fragment: str
) -> None:
    response = client.post("/api/translate", json=payload)
    assert response.status_code == 422
    body = response.json()
    assert set(body) == {"detail"}
    assert isinstance(body["detail"], str)
    assert fragment in body["detail"]
    assert fake_provider.calls == []


def test_too_long_text_uses_configured_limit() -> None:
    provider = FakeProvider()
    with client_with(provider, max_chars=10) as client:
        response = client.post("/api/translate", json={"text": "x" * 11, "target": "en"})
    assert response.status_code == 422
    assert "maximum 10" in response.json()["detail"]
    assert provider.calls == []


# --- translate: provider errors never leak ------------------------------------


def test_rate_limit_returns_429_with_friendly_message(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider(error=ProviderRateLimitError("quota exceeded for project 42", provider="fake"))
    with client_with(provider) as client, caplog.at_level(logging.WARNING):
        response = client.post("/api/translate", json={"text": "Hi", "target": "fr"})
    assert response.status_code == 429
    assert response.json() == {"detail": RATE_LIMIT_MESSAGE}
    assert "project 42" not in response.text
    assert "quota exceeded for project 42" in caplog.text


def test_invalid_server_key_returns_503_generic_and_logs_real_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider(error=ProviderAuthError(SECRET_UPSTREAM, provider="fake"))
    with client_with(provider) as client, caplog.at_level(logging.ERROR):
        response = client.post("/api/translate", json={"text": "Hi", "target": "fr"})
    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE_MESSAGE}
    assert "sk-REAL" not in response.text
    assert "400" not in response.text
    error_records = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert error_records and "sk-REAL-KEY-123" in error_records[0].getMessage()
    assert "Check your .env" in error_records[0].getMessage()


def test_provider_unavailable_returns_503_generic() -> None:
    provider = FakeProvider(error=ProviderUnavailableError("HTTP 503 upstream down", provider="fake"))
    with client_with(provider) as client:
        response = client.post("/api/translate", json={"text": "Hi", "target": "fr"})
    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE_MESSAGE}
    assert "upstream" not in response.text


def test_bad_output_returns_502_generic() -> None:
    provider = FakeProvider(error=ProviderBadOutputError("invalid structured output: ...", provider="fake"))
    with client_with(provider) as client:
        response = client.post("/api/translate", json={"text": "Hi", "target": "fr"})
    assert response.status_code == 502
    assert response.json() == {"detail": BAD_OUTPUT_MESSAGE}
    assert "structured" not in response.text


def test_unexpected_exception_returns_500_generic(caplog: pytest.LogCaptureFixture) -> None:
    provider = FakeProvider(error=RuntimeError("secret internal state"))
    with client_with(provider) as client, caplog.at_level(logging.ERROR):
        response = client.post("/api/translate", json={"text": "Hi", "target": "fr"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Unexpected server error."}
    assert "secret internal state" not in response.text
    assert "secret internal state" in caplog.text
