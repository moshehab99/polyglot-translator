# Polyglot – Smart Language Translator

A small web app that translates text between seven languages, in any direction
(any → any), using an LLM. It treats **Modern Standard Arabic** and **Egyptian Arabic**
as two separate languages, so you can translate into the formal written standard or
into everyday Cairene dialect, and even between the two.

| Code  | Language                     | Native name      | Direction |
|-------|------------------------------|------------------|-----------|
| `ar`  | Modern Standard Arabic (MSA) | العربية الفصحى   | RTL       |
| `arz` | Egyptian Arabic              | العامية المصرية  | RTL       |
| `en`  | English                      | English          | LTR       |
| `fr`  | French                       | Français         | LTR       |
| `it`  | Italian                      | Italiano         | LTR       |
| `de`  | German                       | Deutsch          | LTR       |
| `es`  | Spanish                      | Español          | LTR       |

The backend is FastAPI, the frontend is server-rendered Jinja2 with plain JavaScript
and CSS (no framework, no external fonts). The default translation engine is
**Google Gemini** on the free tier; **Anthropic Claude** is a drop-in alternative.

## Features

- Any-to-any translation between the seven languages above.
- Source auto-detection, including telling MSA apart from Egyptian Arabic.
- Right-to-left layout for Arabic input and output; text direction follows the
  selected or detected language.
- Swap languages, copy the result, live character counter, `Ctrl + Enter` to translate.
- Two interchangeable providers (Gemini, Anthropic) behind one interface, selected
  with a single environment variable.
- Safe error handling: the browser only ever sees a short generic message; provider
  details, model names and keys stay in the server log.
- User text is passed to the model as data inside `<text>` tags, not as instructions.
- Light and dark colour schemes, usable on mobile.

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 for you if needed)
- An API key for one provider: Gemini (free) or Anthropic (paid)

## Setup

```bash
git clone https://github.com/moshehab99/polyglot-translator.git
cd polyglot-translator
uv sync
cp .env.example .env        # PowerShell: Copy-Item .env.example .env
```

Then open `.env` and fill in the key for the provider you use. `.env` is git-ignored;
never commit it.

| Variable            | Default                 | Meaning                                    |
|---------------------|-------------------------|--------------------------------------------|
| `PROVIDER`          | `gemini`                | `gemini` or `anthropic`                    |
| `GEMINI_API_KEY`    | –                       | Required when `PROVIDER=gemini`            |
| `GEMINI_MODEL`      | `gemini-3.5-flash-lite` | Gemini model ID                            |
| `ANTHROPIC_API_KEY` | –                       | Required when `PROVIDER=anthropic`         |
| `ANTHROPIC_MODEL`   | `claude-opus-5`         | Claude model ID                            |
| `MAX_CHARS`         | `5000`                  | Maximum input length per request (1–50000) |
| `REQUEST_TIMEOUT_S` | `60`                    | Timeout for one provider call, in seconds  |

Only the key for the active provider is required. If it is missing, the server refuses
to start and tells you which variable to set.

### Get a free Gemini API key

1. Go to [Google AI Studio](https://aistudio.google.com/apikey) and sign in with a
   Google account.
2. Click **Create API key** (AI Studio creates or lets you pick a Google Cloud project).
3. Copy the key into `.env`:

   ```
   PROVIDER=gemini
   GEMINI_API_KEY=your-key-here
   ```

No credit card is needed for the free tier. Two things to know about it:

- **Rate limits.** The free tier allows a limited number of requests and tokens per
  minute and per day, and the limits differ per model. When you hit them the app
  answers `429` "Too many requests, please try again shortly." Current limits are
  listed in AI Studio and in the
  [rate limit docs](https://ai.google.dev/gemini-api/docs/rate-limits).
- **Your data may be used by Google.** On the free tier, Google may use the text you
  send and the responses to improve its products, and human reviewers may read it.
  Do not translate confidential or personal text on a free-tier key. See the
  [Gemini API terms](https://ai.google.dev/gemini-api/terms); paid usage has
  different data terms.

### Switch to Anthropic

Create an API key in the [Anthropic Console](https://console.anthropic.com/) (paid,
usage-based), then set in `.env`:

```
PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key-here
ANTHROPIC_MODEL=claude-opus-5
```

`ANTHROPIC_MODEL` is optional; the value shown is the default. Restart the server
after changing `.env`, because settings are read once at startup. Nothing else
changes: the UI and the API behave the same with either provider.

## Run the server

```bash
uv run uvicorn app.main:app --reload
```

Open <http://localhost:8000>. Interactive API docs are at <http://localhost:8000/docs>.

## Run the tests

```bash
uv run pytest                          # whole suite
uv run pytest tests/test_api.py -q     # one file
```

All LLM calls are mocked. The tests need no API key, do not read your `.env`, and
never touch the network.

## API

### `POST /api/translate`

Request body:

| Field    | Type   | Notes                                                            |
|----------|--------|------------------------------------------------------------------|
| `text`   | string | Text to translate, at most `MAX_CHARS` characters after trimming |
| `source` | string | A language code, or `auto` to detect it (default `auto`)         |
| `target` | string | A language code                                                  |

```bash
curl -X POST http://localhost:8000/api/translate \
  -H "Content-Type: application/json" \
  -d '{"text": "Where is the train station?", "source": "auto", "target": "arz"}'
```

```json
{
  "translation": "محطة القطر فين؟",
  "detected_source": "en",
  "source_rtl": false,
  "target_rtl": true
}
```

`detected_source` is the source you chose, or the detected language when `source`
is `auto`. `source_rtl` and `target_rtl` tell the client which text direction to use.

Errors always have the shape `{"detail": "<message>"}`:

| Status | When                                                                                           |
|--------|------------------------------------------------------------------------------------------------|
| `422`  | Invalid input: empty text, text too long, unknown language code, or the same source and target |
| `429`  | The provider's rate limit or quota was hit                                                     |
| `502`  | The model answered, but not with a usable translation                                          |
| `503`  | The provider is unreachable, or the server's API key is invalid                                |
| `500`  | Unexpected server error                                                                        |

### `GET /api/health`

```json
{ "status": "ok", "provider": "gemini" }
```

Reports only the active provider name, never keys or model names.

### `GET /`

The web UI.

## Project structure

```
app/
  main.py                   create_app(): routers, static files, startup checks
  config.py                 Settings (pydantic-settings) and provider-key validation
  languages.py              Language registry: the single source of truth
  logging.py                Logging setup
  api/
    schemas.py              Request/response models
    deps.py                 FastAPI dependencies (settings, provider, service)
    errors.py               Exception handlers: the only place errors become responses
    routes_pages.py         GET /
    routes_translate.py     POST /api/translate, GET /api/health
  providers/
    base.py                 TranslationProvider interface and ProviderError hierarchy
    schemas.py              Structured output: {detected_source, translation}
    prompts.py              Prompt builders (MSA vs Egyptian rules live here)
    gemini_provider.py      Gemini via the google-genai Interactions API (default)
    anthropic_provider.py   Claude via anthropic messages.parse
    factory.py              build_provider(settings)
  services/
    translation_service.py  Input validation, then calls the provider
  templates/                base.html, index.html (Jinja2)
  static/                   css/style.css, js/app.js
tests/                      pytest suite, everything mocked
```
