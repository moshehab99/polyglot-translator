import pytest

from app.languages import get_language
from app.providers.base import ProviderRateLimitError
from app.services.translation_service import TranslationService, TranslationValidationError
from tests.conftest import FakeProvider


def make_service(provider: FakeProvider | None = None, max_chars: int = 20) -> TranslationService:
    return TranslationService(provider=provider or FakeProvider(), max_chars=max_chars)


async def test_explicit_source_passes_languages_to_provider() -> None:
    provider = FakeProvider(translation="Hallo")
    result = await make_service(provider).translate("  Hello  ", "en", "de")

    assert result.translation == "Hallo"
    assert result.detected_source is get_language("en")
    assert provider.calls == [("Hello", get_language("en"), get_language("de"))]


async def test_auto_source_passes_none_and_returns_detected() -> None:
    provider = FakeProvider(detected="arz")
    result = await make_service(provider).translate("إزيك", "auto", "en")

    assert provider.calls[0][1] is None
    assert result.detected_source.code == "arz"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
async def test_empty_text_rejected(text: str) -> None:
    with pytest.raises(TranslationValidationError, match="enter some text"):
        await make_service().translate(text, "auto", "en")


async def test_too_long_text_rejected_after_strip() -> None:
    service = make_service(max_chars=5)
    await service.translate("  abcde  ", "auto", "en")  # exactly max after strip is fine
    with pytest.raises(TranslationValidationError, match="too long: 6 characters \\(maximum 5\\)"):
        await service.translate("abcdef", "auto", "en")


async def test_same_source_and_target_rejected() -> None:
    with pytest.raises(TranslationValidationError, match="same"):
        await make_service().translate("hi", "en", "en")


async def test_unknown_codes_rejected() -> None:
    with pytest.raises(TranslationValidationError, match="target"):
        await make_service().translate("hi", "en", "xx")
    with pytest.raises(TranslationValidationError, match="source"):
        await make_service().translate("hi", "xx", "en")


async def test_provider_errors_propagate_untouched() -> None:
    provider = FakeProvider(error=ProviderRateLimitError("quota", provider="fake"))
    with pytest.raises(ProviderRateLimitError):
        await make_service(provider).translate("hi", "auto", "en")


# --- to_arabic_script ------------------------------------------------------------


async def test_to_arabic_script_strips_and_delegates() -> None:
    provider = FakeProvider(script_result="الـ laptop وقع")
    result = await make_service(provider).to_arabic_script("  il laptop w2e3 \n")
    assert result == "الـ laptop وقع"
    assert provider.script_calls == ["il laptop w2e3"]
    assert provider.calls == []


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
async def test_to_arabic_script_rejects_empty_text(text: str) -> None:
    provider = FakeProvider()
    with pytest.raises(TranslationValidationError, match="enter some text"):
        await make_service(provider).to_arabic_script(text)
    assert provider.script_calls == []


async def test_to_arabic_script_rejects_too_long_text_after_strip() -> None:
    service = make_service(max_chars=5)
    await service.to_arabic_script("  abcde  ")  # exactly max after strip is fine
    with pytest.raises(TranslationValidationError, match="too long: 6 characters \\(maximum 5\\)"):
        await service.to_arabic_script("abcdef")


async def test_to_arabic_script_provider_errors_propagate() -> None:
    provider = FakeProvider(error=ProviderRateLimitError("quota", provider="fake"))
    with pytest.raises(ProviderRateLimitError):
        await make_service(provider).to_arabic_script("hi")
