"""Language registry: the single source of truth for supported languages."""

from __future__ import annotations

from dataclasses import dataclass

AUTO = "auto"


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str
    native_name: str
    rtl: bool = False


LANGUAGES: tuple[Language, ...] = (
    Language("ar", "Modern Standard Arabic", "العربية الفصحى", rtl=True),
    Language("arz", "Egyptian Arabic", "العامية المصرية", rtl=True),
    Language("en", "English", "English"),
    Language("fr", "French", "Français"),
    Language("it", "Italian", "Italiano"),
    Language("de", "German", "Deutsch"),
    Language("es", "Spanish", "Español"),
)

LANGUAGES_BY_CODE: dict[str, Language] = {lang.code: lang for lang in LANGUAGES}
LANGUAGE_CODES: tuple[str, ...] = tuple(LANGUAGES_BY_CODE)


def get_language(code: str) -> Language:
    """Return the language for ``code`` or raise ``KeyError`` for unknown codes."""
    try:
        return LANGUAGES_BY_CODE[code]
    except KeyError:
        raise KeyError(f"Unsupported language code: {code!r}") from None


def is_supported(code: str) -> bool:
    return code in LANGUAGES_BY_CODE
