from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app
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
