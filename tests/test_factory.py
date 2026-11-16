from app.providers.anthropic_provider import AnthropicProvider
from app.providers.factory import build_provider
from app.providers.gemini_provider import GeminiProvider
from tests.conftest import make_settings


def test_gemini_is_built_by_default() -> None:
    provider = build_provider(make_settings(gemini_model="gemini-3.8-flash", request_timeout_s=7))
    assert isinstance(provider, GeminiProvider)
    assert provider.name == "gemini"
    assert provider._model == "gemini-3.8-flash"
    assert provider._timeout_s == 7


def test_anthropic_is_built_when_selected() -> None:
    provider = build_provider(
        make_settings(provider="anthropic", gemini_api_key=None, anthropic_api_key="sk-test")
    )
    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"
    assert provider._model == "claude-opus-5"
