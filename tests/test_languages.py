import pytest

from app.languages import AUTO, LANGUAGE_CODES, LANGUAGES, get_language, is_supported


def test_all_seven_languages_present() -> None:
    assert LANGUAGE_CODES == ("ar", "arz", "en", "fr", "it", "de", "es")
    assert len({lang.code for lang in LANGUAGES}) == len(LANGUAGES)


def test_arabic_variants_are_rtl_and_distinct() -> None:
    msa = get_language("ar")
    egy = get_language("arz")
    assert msa.rtl and egy.rtl
    assert msa.name == "Modern Standard Arabic"
    assert egy.name == "Egyptian Arabic"
    assert msa.native_name != egy.native_name


def test_latin_languages_are_ltr() -> None:
    assert all(not get_language(code).rtl for code in ("en", "fr", "it", "de", "es"))


def test_unknown_code() -> None:
    assert not is_supported("xx")
    assert not is_supported(AUTO)
    with pytest.raises(KeyError, match="xx"):
        get_language("xx")
