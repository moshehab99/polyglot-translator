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
- **Arabic script** button (`Arabic script / حروف عربي`): rewrites Franco-Arabic
  (Arabizi, `ana msh fahem`) in Arabic script (`أنا مش فاهم`) without translating.
  It keeps the same words in the same order:
  - English and other non-Arabic words stay in Latin script.
  - Digits used as letters become letters; real numbers stay digits.
  - Emoji, punctuation and existing Arabic are kept.
  - Text with no Franco comes back unchanged.
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

## Evaluation

The `evals/` harness checks the hardest part of auto-detection: telling **Modern
Standard Arabic (`ar`)** apart from **Egyptian Arabic (`arz`)**. It sends every sentence
of a small labelled dataset through the real app path:
`Settings -> build_provider -> TranslationService.translate(text, "auto", "en")`.
It then reports detection accuracy with a 95% Wilson interval, a confusion matrix,
precision, recall and F1 per label, and accuracy per slice (short texts, Egyptian
without marker words, code-switching, chat spelling, polite register, and more).
Translation quality is not measured.

```bash
uv run python -m evals.dialect --limit 3        # smoke run: 3 real requests
uv run python -m evals.dialect                  # full run (asks to confirm)
uv run python -m evals.dialect --baseline evals/results/<earlier>.json
```

The CLI makes **real API calls** with the key in `.env`. Each run writes a JSON and a
Markdown report to `evals/results/`, and each report records the prompt fingerprint
and the dataset hash. pytest never calls the API.

**Baseline (2026-11-18, `gemini-3.5-flash-lite`):** 100% on 95 items (95/95, 95% CI
96.1–100%). Report:
[`evals/results/dialect_20261118-030247_gemini_gemini-3.5-flash-lite.md`](evals/results/dialect_20261118-030247_gemini_gemini-3.5-flash-lite.md).

The set is saturated: the current model gets every item right. For now it works as a
**regression check**: every change to the prompt is measured against it, and a drop
shows up as "broken" ids in the `--baseline` comparison.

### Franco-Arabic (Arabizi)

A second eval measures Egyptian Arabic typed in Latin script (`ana msh fahem enta
3ayez eh`). It has two passes:
- **Detection**: `auto -> en` must report `arz`. Controls in other languages must not
  be reported as Arabic.
- **Arabization**: the Arabic-script output for every ar/arz item is compared with a
  hand-written reference. The scores are chrF (0–100, after Arabic normalisation) and a
  Latin-leak check. `--arabize` picks the path:
  - `script` (default) uses the script-conversion mode (`to_arabic_script(text)`) on
    every item. Controls must also come back unchanged.
  - `translate` is the original path, `auto -> arz` (or `ar`), kept to reproduce the
    first baseline.

The dataset has 80 items (61 arz, 6 ar, 13 controls), split into dev and test.

```bash
uv run python -m evals.franco --limit 3         # smoke run: 6 real requests
uv run python -m evals.franco                   # full run: 160 requests (asks to confirm)
uv run python -m evals.franco --arabize translate   # original path: 147 requests
uv run python -m evals.franco --baseline evals/results/franco_20261122-130723_gemini_gemini-3.5-flash-lite.json
```

#### Script conversion: before and after

The first baseline (2026-11-18) ran on the translate path, because the app had no
script-conversion mode yet. The script path was then measured with the same model,
the same dataset and the same translation prompts. The script prompt fingerprint is
`0d1af77c3a67`.

| Metric | Before: translate path (2026-11-18) | After: script path (2026-11-22) | Target |
|---|---:|---:|---|
| `code_switch` mean chrF | 52.0 | **87.8** | clearly above 52: met |
| Test mean chrF | 84.2 | **88.0** | above 84.2: met |
| Overall mean chrF (dev / test) | 84.9 (85.3 / 84.2) | **91.1** (92.7 / 88.0) | |
| Controls unchanged | n/a | **13/13** | at least 12/13: met |
| Latin leaks | 1/67 | **4/67** | at most 1: **missed** |
| `clear` mean chrF | 97.9 | 93.3 | |
| Detection | 77/80 = 96.2% | 77/80 = 96.2% | unchanged: met |

- **Missed target: Latin leaks went from 1/67 to 4/67.** All four are English-heavy
  code-switched sentences where a Franco word next to English words is left in Latin
  script (f065, f072, f073, f074). f072 was already the one leak in the baseline.
- **Small drop on `clear` (97.9 -> 93.3).** The model sometimes writes another valid
  Egyptian variant of the same word (for example `3ayez` as عاوز instead of عايز).
  chrF counts that against it, even though the text is correct Egyptian.
- **One tuning round was reverted.** Adding more rules to the script prompt made dev
  worse (chrF 89.9 -> 87.0, Latin leaks 1 -> 5), so the change was reverted and the
  first script prompt was kept. Tuning used dev failures only; test was never tuned on.

Report:
[`evals/results/franco_20261122-130723_gemini_gemini-3.5-flash-lite.md`](evals/results/franco_20261122-130723_gemini_gemini-3.5-flash-lite.md).
It is the baseline for the script path. Every script-prompt change is measured against
it with `--baseline`.

#### First baseline: translate path

**Baseline (2026-11-18, `gemini-3.5-flash-lite`, current app with no Franco-specific
changes):**
- **Detection: 77/80 = 96.2%** (95% CI 89.5–98.7%).
  - All 61 arz items are correct.
  - 0/13 controls were falsely detected as Arabic, including English chat with
    b4/2mrw/law/mesh.
  - The 3 misses are all shared phrases (f017, f029, f076) predicted `arz`. That is a
    labelling-policy edge, not a Franco weakness. The labels stay as they are.
- **Arabization: mean chrF 84.9** (dev 85.3, test 84.2), Latin leak 1/67.
  - Pure Franco is near-perfect: `clear` 97.9, `no_numerals` 95.7.
  - Code-switching is the weak spot (chrF 52.0). `auto -> arz` translates English words
    into Arabic (meeting -> الاجتماع, file -> الملف) instead of keeping them, because
    the app only translated and had no script-conversion mode. The script path above
    fixes this.
  - Other misses: one copy-through with no conversion (f072), one wrong word (f055),
    and spelling drift (3ayez -> عاوز).
- chrF is strict on short sentences: one changed letter can cost ~20 points. Read the
  review table in the report, not only the mean.

Report:
[`evals/results/franco_20261118-080836_gemini_gemini-3.5-flash-lite.md`](evals/results/franco_20261118-080836_gemini_gemini-3.5-flash-lite.md).

The labelling policies, dataset schemas, tags, flags and report formats of both evals are
in [`evals/README.md`](evals/README.md).

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

### `POST /api/arabic-script`

Writes Franco-Arabic in Arabic script. It is script conversion, not translation: the
same words in the same order, with no language choice. English and other non-Arabic
words stay in Latin script. Digits used as letters (`3` = ع, `7` = ح, ...) become
letters, and real numbers stay digits. Emoji, punctuation and existing Arabic script
are kept. Text with no Franco-Arabic comes back unchanged.

| Field  | Type   | Notes                                                           |
|--------|--------|-----------------------------------------------------------------|
| `text` | string | Text to convert, at most `MAX_CHARS` characters after trimming  |

```bash
curl -X POST http://localhost:8000/api/arabic-script \
  -H "Content-Type: application/json" \
  -d '{"text": "il printer 3amal restart lwa7do kmn"}'
```

```json
{ "result": "الـ printer عمل restart لوحده كمان" }
```

Errors use the same `{"detail": "<message>"}` shape and status codes as
`/api/translate`: `422` for empty or too long text, then `429`, `502`, `503` and `500`.

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
    routes_translate.py     POST /api/translate, POST /api/arabic-script, GET /api/health
  providers/
    base.py                 TranslationProvider interface and ProviderError hierarchy
    schemas.py              Structured output: {detected_source, translation}, {converted}
    prompts.py              Prompt builders (MSA vs Egyptian rules, script conversion)
    gemini_provider.py      Gemini via the google-genai Interactions API (default)
    anthropic_provider.py   Claude via anthropic messages.parse
    factory.py              build_provider(settings)
  services/
    translation_service.py  Input validation, then calls the provider
  templates/                base.html, index.html (Jinja2)
  static/                   css/style.css, js/app.js
evals/
  README.md                 What is measured, labelling policy, schema, how to run
  dataset.py                EvalItem schema, load_dataset, dataset hash
  metrics.py                Accuracy, Wilson interval, confusion matrix, P/R/F1 (pure)
  dialect.py                MSA vs Egyptian detection runner and CLI
  franco.py                 Franco-Arabic detection + arabization runner and CLI
  data/dialect.jsonl        Labelled dataset (human-reviewed)
  data/franco.jsonl         Franco-Arabic dataset with Arabic-script references, dev/test
  results/                  Committed run reports (baselines)
tests/                      pytest suite, everything mocked
```
