import pytest
from pydantic import ValidationError

from app.config import Settings
from tests.conftest import make_settings


def test_defaults_use_gemini() -> None:
    settings = make_settings()
    assert settings.provider == "gemini"
    assert settings.gemini_model == "gemini-3.5-flash-lite"
    assert settings.anthropic_model == "claude-opus-5"
    assert settings.max_chars == 5000
    assert settings.active_model == "gemini-3.5-flash-lite"
    assert settings.active_api_key is not None
    assert settings.active_api_key.get_secret_value() == "test-gemini-key"


def test_missing_gemini_key_fails_with_clear_message() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, provider="gemini")  # type: ignore[call-arg]
    assert "GEMINI_API_KEY" in str(exc_info.value)


def test_blank_key_is_treated_as_missing() -> None:
    with pytest.raises(ValidationError):
        make_settings(gemini_api_key="   ")


def test_anthropic_requires_only_its_own_key() -> None:
    settings = Settings(_env_file=None, provider="anthropic", anthropic_api_key="sk-test")  # type: ignore[call-arg]
    assert settings.gemini_api_key is None
    assert settings.active_model == "claude-opus-5"
    assert settings.active_api_key is not None


def test_missing_anthropic_key_fails() -> None:
    with pytest.raises(ValidationError) as exc_info:
        Settings(_env_file=None, provider="anthropic", gemini_api_key="unused")  # type: ignore[call-arg]
    assert "ANTHROPIC_API_KEY" in str(exc_info.value)


def test_invalid_provider_rejected() -> None:
    with pytest.raises(ValidationError):
        make_settings(provider="openai")


def test_env_vars_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    monkeypatch.setenv("MAX_CHARS", "1200")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.provider == "anthropic"
    assert settings.active_model == "claude-sonnet-5"
    assert settings.max_chars == 1200


def test_secret_is_not_in_repr() -> None:
    assert "test-gemini-key" not in repr(make_settings())
