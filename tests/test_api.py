from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import get_settings
from app.main import create_app
from app.providers.gemini_provider import GeminiProvider
from tests.conftest import make_settings


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


def test_startup_builds_provider_from_overridden_settings(client: TestClient) -> None:
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
