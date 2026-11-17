"""Shared pytest fixtures."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_provider
from app.config import Settings, get_settings
from app.languages import Language, get_language
from app.main import create_app
from app.providers.base import TranslationProvider, TranslationResult

ENV_VARS = (
    "PROVIDER",
    "GEMINI_API_KEY",
    "GEMINI_MODEL",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "MAX_CHARS",
    "REQUEST_TIMEOUT_S",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never see the developer's real environment or .env file."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def make_settings(**overrides: object) -> Settings:
    """Build Settings for tests without reading .env."""
    values: dict[str, object] = {"provider": "gemini", "gemini_api_key": "test-gemini-key"}
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class FakeProvider(TranslationProvider):
    """Records calls and returns a canned result, or raises ``error`` if set."""

    name = "fake"

    def __init__(
        self,
        translation: str = "TRANSLATED",
        detected: str = "en",
        error: Exception | None = None,
    ) -> None:
        self.translation = translation
        self.detected = detected
        self.error = error
        self.calls: list[tuple[str, Language | None, Language]] = []

    async def translate(
        self, text: str, source: Language | None, target: Language
    ) -> TranslationResult:
        self.calls.append((text, source, target))
        if self.error is not None:
            raise self.error
        detected = source if source is not None else get_language(self.detected)
        return TranslationResult(translation=self.translation, detected_source=detected)


@pytest.fixture
def settings() -> Settings:
    return make_settings()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def client(settings: Settings, fake_provider: FakeProvider) -> Iterator[TestClient]:
    """App wired to ``settings`` and ``fake_provider``; server exceptions become responses."""
    app = create_app()
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_provider] = lambda: fake_provider
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    app.dependency_overrides.clear()
