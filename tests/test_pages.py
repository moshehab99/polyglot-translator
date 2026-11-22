import re

from fastapi.testclient import TestClient

from app.languages import LANGUAGES
from tests.conftest import FakeProvider
from tests.test_api import client_with


def test_index_renders_with_all_languages(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert "Polyglot" in html
    # Auto-detect is the first/selected source option.
    assert re.search(r'<option value="auto"[^>]*selected', html)
    for lang in LANGUAGES:
        # Each language appears in both dropdowns with its English and native name.
        assert html.count(f'<option value="{lang.code}"') == 2
        assert lang.name in html and lang.native_name in html


def test_index_marks_arabic_options_rtl(client: TestClient) -> None:
    html = client.get("/").text
    for code in ("ar", "arz"):
        assert re.search(rf'<option value="{code}" data-rtl="true"', html)
    for code in ("en", "fr", "it", "de", "es"):
        assert re.search(rf'<option value="{code}" data-rtl="false"', html)


def test_index_uses_configured_char_limit() -> None:
    with client_with(FakeProvider(), max_chars=321) as client:
        html = client.get("/").text
    assert 'maxlength="321"' in html
    assert 'data-max-chars="321"' in html
    assert "/ 321" in html


def test_index_has_core_controls(client: TestClient) -> None:
    html = client.get("/").text
    for element_id in ("source", "target", "source-text", "output", "swap", "copy", "translate", "error", "counter"):
        assert f'id="{element_id}"' in html, element_id
    assert 'dir="auto"' in html  # source textarea follows the typed text until a language is chosen
    assert 'src="/static/js/app.js"' in html
    assert 'href="/static/css/style.css"' in html


def test_index_never_exposes_secrets_or_model(client: TestClient) -> None:
    html = client.get("/").text
    assert "test-gemini-key" not in html
    assert "gemini-3.5" not in html


def test_static_assets_are_served(client: TestClient) -> None:
    css = client.get("/static/css/style.css")
    js = client.get("/static/js/app.js")
    assert css.status_code == 200 and "--font-text" in css.text
    assert js.status_code == 200 and "/api/translate" in js.text
    assert "Noto Naskh Arabic" in css.text  # Arabic-capable font stack


def test_index_has_arabic_script_button(client: TestClient) -> None:
    html = client.get("/").text
    button = re.search(r'<button type="button" id="arabic-script"[^>]*>(.*?)</button>', html, re.S)
    assert button, "arabic-script button missing"
    tag = button.group(0)
    assert 'class="secondary-button"' in tag
    assert " disabled" in tag  # enabled by app.js once there is text
    label = re.sub(r"<[^>]+>", "", button.group(1))
    assert " ".join(label.split()) == "Arabic script / حروف عربي"
    assert '<span lang="arz" dir="rtl">حروف عربي</span>' in tag
    # Both actions sit together, Translate first.
    assert html.index('id="translate"') < html.index('id="arabic-script"')


def test_static_assets_wire_arabic_script(client: TestClient) -> None:
    js = client.get("/static/js/app.js").text
    css = client.get("/static/css/style.css").text
    assert '"/api/arabic-script"' in js
    assert 'getElementById("arabic-script")' in js
    assert 'output.dir = "rtl"' in js
    assert ".secondary-button" in css
