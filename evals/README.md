# Evaluations

## Dialect detection: MSA (`ar`) vs Egyptian Arabic (`arz`)

### What is measured

When the source is `auto`, the app has to report which Arabic variety the text is in.
This eval sends every dataset sentence through the real app path:

```
Settings (.env) -> build_provider -> TranslationService.translate(text, "auto", target)
```

The prediction is `result.detected_source.code`. The run reports accuracy with a 95% Wilson
interval, a confusion matrix (rows `ar`/`arz`; columns `ar`, `arz`, `other`, `error`),
precision, recall and F1 per label, accuracy per tag, and median latency.

Errors and non-Arabic predictions count as wrong and stay in the denominator. Items not
sent because a run stopped early (quota) are reported as `not_run` and are not counted.

Translation quality is **not** measured here.

The dataset is a regression check: every change to the prompt in
`app/providers/prompts.py` is measured against it. Never copy dataset sentences into
the prompt, because then we'd be testing on examples the model was shown.

### Labelling policy

This mirrors the auto-detect rule in `app/providers/prompts.py`.

- **`arz`** if the text has clear Egyptian features: vocabulary, negation (مش, ما…ش),
  verb prefixes (بـ, هـ), pronouns (إنت, إحنا, …) or question words (إيه, ليه, فين, …).
  This applies even when the text is mixed with English.
- **`ar`** otherwise. That includes greetings and religious phrases both varieties use
  (السلام عليكم, إن شاء الله, الحمد لله, …).
- Out of scope: other Arabic dialects and Franco-Arabic (Arabic written in Latin script).

A label changes only if it breaks this policy, **never to match the model's output**.
The commit that changes labels lists which ids changed and why.

### Dataset schema: `data/dialect.jsonl`

UTF-8 without BOM, one JSON object per line:

```json
{"id": "d001", "text": "...", "label": "arz", "tags": ["short"], "note": "optional"}
```

| Field | Rules |
|---|---|
| `id` | `d` + 3 or more digits. Neutral and stable: ids are never renumbered or reused, and new items are appended. The label is not part of the id because labels can be corrected. |
| `text` | One line, no leading or trailing whitespace, unique (after whitespace normalisation). |
| `label` | `ar` or `arz`. |
| `tags` | From the fixed vocabulary below. An unknown tag is a loading error. |
| `note` | Optional free text for reviewers. It is not part of the dataset hash. |

No real names, phone numbers or personal data: the file is public and is sent to a
free-tier API.

### Tags

| Tag | Meaning |
|---|---|
| `clear` | Clear, typical example of its variety |
| `short` | 1–3 words |
| `shared` | Greeting or religious phrase used by both varieties (always `ar`) |
| `topic_swap` | MSA about casual everyday topics, or Egyptian about news, work or serious topics, so the topic doesn't give the answer away |
| `no_markers` | Egyptian that uses none of the marker words listed in `prompts.py`. It also avoids the بـ/هـ verb prefixes and ما…ش, using past tense, imperatives or nominal sentences instead, and still sounds natural. A test checks the marker words as whole tokens, including with a leading و/ف. |
| `code_switch` | Mixed with English words |
| `chat_spelling` | Egyptian chat spelling: no hamzas, ى for final ي, elongated letters |
| `polite` | Polite or work-register Egyptian |
| `long` | 2–3 sentences |

An item can carry several tags, for example `["polite", "long"]`.

Current composition: 95 items, 45 `ar` and 50 `arz`. In d001–d080 the labels alternate
in file order, so a small `--limit` still covers both. d081–d095 are human-written
additions.

| Tag | ar | arz |
|---|---|---|
| clear | 15 | 8 |
| short | 8 | 11 |
| shared | 5 | 0 |
| topic_swap | 12 | 6 |
| no_markers | 0 | 11 |
| code_switch | 2 | 5 |
| chat_spelling | 0 | 6 |
| polite | 0 | 6 |
| long | 8 | 6 |

### How to run

The CLI makes **real API calls** with the provider and key set in `.env`. One request is
sent per item, one at a time.

```
uv run python -m evals.dialect --limit 3           # smoke run: 3 requests
uv run python -m evals.dialect                     # full run (asks to confirm)
uv run python -m evals.dialect --tag no_markers    # one slice
uv run python -m evals.dialect --baseline evals/results/<earlier>.json
```

| Flag | Default | Meaning |
|---|---|---|
| `--target` | `en` | Target language: `en`, `fr`, `it`, `de` or `es` (`ar`/`arz` are rejected) |
| `--limit N` | all | Only the first N items, applied after `--tag` |
| `--tag TAG` | none | Only items with this tag |
| `--model M` | from `.env` | Overrides the active provider's model |
| `--dataset PATH` | `evals/data/dialect.jsonl` | Dataset file |
| `--baseline PATH` | none | Earlier result JSON to compare against |
| `--delay S` | 4 | Seconds between requests |
| `--retry-wait S` | 60 | Seconds to wait after a rate limit before retrying |
| `--out-dir PATH` | `evals/results` | Where reports go |
| `--yes` | off | Skips the confirmation prompt shown for more than 10 requests |

**Rate limits.** After a `429`, the runner waits `--retry-wait` and retries the same item,
at most 2 times. If it still fails, the daily quota has probably run out. The run then
stops, saves a report marked partial, and exits with code 2. The free-tier quota resets
at midnight Pacific time.

**Other failures.**
- An auth error (bad or missing key) aborts the run without writing a report (exit 1).
- Any other provider error marks the item `error`, recording the exception type only,
  and the run continues.
- Anything unexpected crashes the run.

Exit codes: 0 = complete, 1 = aborted or declined, 2 = partial.

Tests never call a real API. They use a fake provider and fake sleep:

```
uv run pytest tests/test_eval_dataset.py tests/test_eval_metrics.py tests/test_eval_runner.py -q
```

### Reading a report

Each run writes two files to `evals/results/`, named
`dialect_<YYYYMMDD-HHMMSS>_<provider>_<model>` (UTC time, model name made safe for file
names). The `.json` and `.md` files share that name.

- **`meta`**:
  - UTC time, dataset path, sha256 and size, provider, model, target.
  - **prompt fingerprint**: short sha256 of the auto-detect system prompt, the user
    message template and the JSON schema. It tells you which prompt produced the numbers.
  - git commit (with `-dirty` if tracked files had changes), filters.
  - `partial`, `stop_reason`, `not_run`.
- **`summary`**: accuracy with 95% Wilson interval, the confusion matrix, P/R/F1 per
  label, accuracy per tag, median latency (successful requests only).
- **`items`**: id, text, label, predicted, outcome (`correct` / `wrong` / `error`),
  tags, translation, error type, latency in ms.
- **`baseline`** (only with `--baseline`): items that were fixed and items that broke,
  compared by id. It also says whether the prompt fingerprint changed and whether the
  **dataset hash** changed. If the hash changed, the numbers are not directly comparable.

The `.md` file shows the same information as tables and lists every wrong or error item
with its text. The console shows only an ASCII summary and the two file paths. Result
files are committed only when the maintainer chooses a run to keep (e.g. the baseline).

## Franco-Arabic (Arabizi): Egyptian Arabic in Latin script

### What is measured

Users type Egyptian Arabic in Latin letters, with digits standing in for some Arabic
letters: `ana msh fahem enta 3ayez eh`. This eval measures how the app handles that
input, through the same real path as the dialect eval:

```
Settings (.env) -> build_provider -> TranslationService
```

1. **Detection** (every item): `translate(text, "auto", "en")`, or target `"fr"` for
   items labelled `en`. `detected_source` must equal the label. The English or French
   output is saved for manual review but not scored.
2. **Arabization**, chosen with `--arabize`:
   - `script` (default): `to_arabic_script(text)` for **every** item. This is the app's
     script-conversion mode (`POST /api/arabic-script`): same words, Franco in Arabic
     script, everything else kept as written.
   - `translate`: `translate(text, "auto", item.label)` for ar/arz items only, so `arz`
     items go to Egyptian Arabic and `ar` items go to MSA. This is the path the baseline
     below was measured with.

   For ar/arz items the output is compared with the item's `arabic` reference:
   - **chrF** (character n-grams 1..6, beta = 2, 0-100) after Arabic normalisation:
     tashkeel and tatweel removed, أ/إ/آ -> ا, ة -> ه, ى -> ي, Arabic-Indic (٠-٩)
     and Persian (۰-۹) digits -> 0-9, punctuation dropped, spaces collapsed.
   - **Latin leak**: the output contains a Latin-script word that is not in the
     reference.

Controls (real English/French/Spanish/... text) get the detection pass, plus the script
pass in `script` mode. A control detected as `ar`/`arz` is a false positive. In `script`
mode a control must come back **unchanged**: output == input after whitespace
normalisation (runs of whitespace collapsed, ends stripped; case and punctuation count).

### Labelling policy

The labels apply the dialect policy above to Latin-script text.

- **`arz`**: the text has clear Egyptian features, written in Latin script. These include
  negation (msh/mesh, ma...sh), verb prefixes (b-, ha-), pronouns (enta, enty, e7na),
  question words (eh, leh, fen, ezay, emta) and Egyptian vocabulary (3ayez, keda,
  delwa2ty, 7aga, bokra). This applies even when English words are mixed in.
- **`ar`**: Latin-script Arabic without Egyptian features. That includes greetings and
  religious phrases both varieties use (inshallah, el7amdulellah, salamo 3aleko,
  ramadan kareem), tagged `shared`, the same rule as the dialect set.
- **Controls** (`en`, `fr`, `it`, `de`, `es`): real text in that language, not Franco,
  tagged `control`. The label is its language. Some controls deliberately contain
  words that are also Franco words (law, mesh) and are tagged `ambiguous`.

**The `arabic` reference** is the word the writer meant, spelled normally in Egyptian
spelling: b7d -> بجد, 7a2olak -> هقولك.
- Fix letter slips, but never rephrase, reorder, or add words beyond what the writer
  meant.
- Follow the writer's word choices: 3ayez -> عايز, 3awez -> عاوز.
- English words inside the text stay in Latin script as written. The loader rejects any
  Latin word in `arabic` that does not occur in `text`.
- Chat abbreviations are written out in normal spelling: msh -> مش, m3lsh -> معلش,
  isa -> إن شاء الله.
- Elongation is written once: ahhhh -> آه.
- Real numbers stay as digits.

A label or reference changes only if it breaks this policy, **never to match the
model's output**. The commit that changes labels or references lists which ids changed
and why.

**Splits.** About one third of the items are `test`. Prompt work may only look at `dev`
failures. `test` is reported in every run but never used for tuning.

### Dataset schema: `data/franco.jsonl`

UTF-8 without BOM, one JSON object per line:

```json
{"id": "f001", "text": "ana msh fahem enta 3ayez eh", "label": "arz", "arabic": "أنا مش فاهم إنت عايز إيه", "meaning": "I don't understand what you want", "tags": ["clear", "numerals"], "split": "dev", "note": "optional"}
```

| Field | Rules |
|---|---|
| `id` | `f` + 3 or more digits. Never renumbered or reused; new items are appended. |
| `text` | One line, no leading or trailing whitespace, unique (after whitespace normalisation). |
| `label` | `arz`, `ar`, `en`, `fr`, `it`, `de` or `es`: the expected `detected_source`. |
| `arabic` | Required for `ar`/`arz`, absent for controls. It must contain Arabic letters, and its Latin words must all occur in `text`. |
| `meaning` | Short English gloss. Required for `ar`/`arz`, absent for controls. For review only, not scored. |
| `tags` | At least one, from the fixed vocabulary below. An unknown tag is a loading error. |
| `split` | `dev` or `test`. |
| `note` | Optional free text for reviewers. It is not part of the dataset hash. |

Cross-field rules, enforced by the loader:
- `control` is present exactly when the label is not `ar`/`arz`.
- `shared` requires `ar`.
- Every `ar`/`arz` item has exactly one of `numerals` / `no_numerals`.
- Controls have neither of them.

Duplicate ids or texts, a BOM, or a malformed line are errors that name `file:line`.
The dataset hash covers every field except `note`.

No real names, phone numbers or personal data: the file is public and is sent to a
free-tier API. Never copy dataset sentences into `app/providers/prompts.py`.

### Tags

| Tag | Meaning |
|---|---|
| `clear` | Clear, typical example |
| `short` | 1–3 words |
| `numerals` | Uses digits for letters: 2 ء/ق, 3 ع, 5 خ, 7 ح, 8 غ, 9 ق |
| `no_numerals` | Letters only, e.g. `a` for ع, `kh`, `gh`, `'` for ق |
| `code_switch` | English words inside |
| `chat` | Abbreviations, dropped vowels, elongation: msh, m3lsh, isa, ahhhh |
| `ambiguous` | Contains words that are also real English/French words: law, bas, ana, mesh, men, fen |
| `shared` | Religious or greeting phrase used by both varieties (always `ar`) |
| `long` | 2–3 sentences |
| `control` | Not Franco: real English/French/Spanish/... text; label = its language |

The same word is spelled differently across items, as real people do: 3ayez/aayez,
msh/mesh/mish, ezayak/izayak, 7aga/haga, dlwa2ty/dlwa2ti/dilwa'ti, enta/ent.

Current composition: 80 items: 61 `arz`, 6 `ar`, 13 controls (7 en, 2 fr, 2 es, 1 it,
1 de). Split: 53 dev, 27 test (20 arz, 3 ar, 4 controls).
- f001–f060 were drafted. A control or `ar` item appears roughly every five lines in
  them, so a small `--limit` mixes labels.
- f061–f080 are human-written (note `human-written`). They are copied verbatim, with
  emoji, mixed Arabic script and English chat abbreviations (b4, 2mrw) in the controls.

| Tag | arz | ar | control |
|---|---|---|---|
| clear | 12 | 1 | 0 |
| short | 8 | 4 | 1 |
| numerals | 42 | 4 | 0 |
| no_numerals | 19 | 2 | 0 |
| code_switch | 18 | 0 | 0 |
| chat | 18 | 0 | 7 |
| ambiguous | 17 | 0 | 2 |
| shared | 0 | 5 | 0 |
| long | 6 | 0 | 0 |
| control | 0 | 0 | 13 |

Tests check the real file:
- `short` means at most 3 words.
- `numerals` / `no_numerals` match the text (ar/arz items only).
- `long` has at least 2 sentences.
- Every tag is used at least 3 times.
- The test split is 25–40% of items and contains arz, ar and controls.

```
uv run pytest tests/test_franco_dataset.py -q
```

### Metrics

- **Detection**:
  - Accuracy with a 95% Wilson interval. Errors stay in the denominator.
  - A confusion matrix with rows = labels present and columns = the 7 codes, `other`
    and `error`.
  - The control false-positive rate (controls detected as `ar`/`arz`) with a Wilson
    interval.
- **Arabization**:
  - chrF is computed on both sides after normalisation, as described above:
    - Character n-grams of order 1..6 with whitespace removed.
    - Precision and recall are averaged over the orders where both sides have n-grams.
    - Then F with beta = 2 (recall weighted more), scaled to 0–100.
  - Latin leak means the raw output has a Latin-script token (letters, optionally with
    digits, so a leaked `3ayez` counts) that the reference does not have. Case is
    ignored.
  - **Errors are not scored.** Mean chrF and the leak rate cover successful outputs
    only, and the arabization error count is reported next to them.
- **Controls unchanged** (`script` mode only): unchanged / successful script outputs on
  controls, with script errors counted separately.
- All of these are reported per tag and per split, along with the median latency of
  each pass.

### How to run

The CLI makes **real API calls** with the provider and key set in `.env`, one at a time.
- `script` mode (default): 2 requests per item (detection + script conversion), controls
  included. A full run is 160 requests.
- `translate` mode: 2 per `ar`/`arz` item and 1 per control (147 for a full run).

```
uv run python -m evals.franco --limit 3            # smoke run: f001-f003 = 6 requests
uv run python -m evals.franco                      # full run (asks to confirm)
uv run python -m evals.franco --split dev          # dev only (for prompt work): 106 requests
uv run python -m evals.franco --tag no_numerals    # one slice
uv run python -m evals.franco --arabize translate  # the old (baseline) path
uv run python -m evals.franco --baseline evals/results/franco_20261118-080836_gemini_gemini-3.5-flash-lite.json
```

| Flag | Default | Meaning |
|---|---|---|
| `--arabize P` | `script` | Arabization path: `script` (`to_arabic_script`, every item) or `translate` (`auto -> label`, ar/arz only) |
| `--limit N` | all | Only the first N items, applied after `--tag` and `--split` |
| `--tag TAG` | none | Only items with this tag |
| `--split S` | none | Only `dev` or only `test` items |
| `--model M` | from `.env` | Overrides the active provider's model |
| `--dataset PATH` | `evals/data/franco.jsonl` | Dataset file |
| `--baseline PATH` | none | Earlier **franco** result JSON to compare against |
| `--delay S` | 4 | Seconds between requests |
| `--retry-wait S` | 60 | Seconds to wait after a rate limit before retrying |
| `--out-dir PATH` | `evals/results` | Where reports go |
| `--yes` | off | Skips the confirmation prompt shown for more than 10 **requests** |

There is no `--target`, because the targets are fixed by design.

Rate limits, auth errors, other provider errors and exit codes work as in the dialect
eval. One difference: if the rate limit persists in the middle of an item, that item's
half-done result is dropped and counted in `not_run`.

### Reading a report

The files are named `franco_<YYYYMMDD-HHMMSS>_<provider>_<model>.json` / `.md`.

- **`meta`**:
  - `eval: "franco"`, UTC time, dataset path, sha256 and size, provider and model.
  - `arabize`: the path (`script` or `translate`). Reports from before this field read
    as `translate`.
  - `prompt_fingerprint`: one short sha256 per translation target (`en`, `fr`, `ar`,
    `arz`).
  - `script_prompt_fingerprint`: the same for the script-conversion prompt, user template
    and schema (`null` in `translate` mode).
  - git commit, filters (tag, split, limit), `requests_planned`, and `partial` /
    `stop_reason` / `not_run`.
- **`summary`**: everything listed under Metrics. It is computed from `items` alone,
  so a saved run can be re-scored with `franco.summarize_franco(report["items"])`
  without new API calls.
- **`items`**: the dataset fields plus every raw output:
  - Detection: `detect_target`, `predicted`, `outcome`, `translation` (the en/fr
    output), `detect_error_type`, `detect_latency_ms`.
  - Arabization: `arabize_target` (the label in `translate` mode, `"script"` in
    `script` mode), `arabic_output` (for controls too in `script` mode),
    `arabic_detected` (`translate` mode only), `arabize_error_type`,
    `arabize_latency_ms`.
  - Scores: `chrf`, `latin_leak` (ar/arz items), `control_unchanged` (controls in
    `script` mode).
- **`baseline`** (only with `--baseline`):
  - Detection: items fixed and broken.
  - The arabization path, before -> after.
  - Mean chrF, leak count and leak rate, before -> after, overall and per split and
    per tag (`groups`).
  - Ids with a new or fixed Latin leak.
  - Whether the translation prompt fingerprints or the dataset hash changed, and the
    script prompt status: `new` (baseline had none), `same`, `changed`, or `n/a`
    (`translate` run).

The `.md` file has:
- Run (including the arabization path), detection, confusion-matrix and arabization
  sections, plus the controls-unchanged count in `script` mode.
- Per-split and per-tag tables.
- The wrong detections.
- A **review table** for every ar/arz item:
  `id | text | arabic ref | arabized output | chrF | en output | meaning`. A `*` after
  chrF marks a Latin leak.
- A controls table. In `script` mode it adds `script output | unchanged`.
- With `--baseline`: per-split and per-tag tables of chrF and leaks, before -> after.

```
uv run pytest tests/test_franco_dataset.py tests/test_franco_runner.py tests/test_eval_metrics.py -q
```

### Baseline

Recorded 2026-11-18 with `gemini-3.5-flash-lite` on the app before the script-conversion
mode existed, so with the `translate` arabization path (`--arabize translate` reproduces
it):
- Git commit `2753347`, all 80 items, 147 requests, not partial.
- Prompt fingerprints: en `2ac34465d2fb`, fr `f081acbcb4e6`, ar `6760617d77bd`,
  arz `572d36e53152`.
- Dataset sha256 `5c5f40061ec0…`.
- Report:
  [`results/franco_20261118-080836_gemini_gemini-3.5-flash-lite.md`](results/franco_20261118-080836_gemini_gemini-3.5-flash-lite.md).

**Detection: 77/80 = 96.2%** (95% CI 89.5–98.7%), with no errors.
- All 61 arz items are correct.
- Controls falsely detected as Arabic: 0/13, including English chat with b4/2mrw/law/mesh.
- The 3 misses are all `shared` phrases (f017, f029, f076) predicted `arz`. That is a
  labelling-policy edge, not a Franco weakness. The labels stay as they are.

**Arabization: mean chrF 84.9** (dev 85.3, test 84.2). Latin leak: 1/67. No errors.

| Tag | Mean chrF |
|---|---:|
| clear | 97.9 |
| no_numerals | 95.7 |
| ambiguous | 91.3 |
| long | 91.0 |
| chat | 82.6 |
| numerals | 80.0 |
| code_switch | 52.0 |

- Pure Franco is near-perfect.
- Code-switching is the weak spot. `auto -> arz` translates English words into Arabic
  (meeting -> الاجتماع, file -> الملف) instead of keeping them as written, because the
  app only translates and has no script-conversion mode.
- Other misses:
  - One copy-through with no conversion (f072, also the only Latin leak).
  - One wrong word (f055).
  - Spelling drift (3ayez -> عاوز).
- chrF is strict on short sentences: one changed letter can cost ~20 points. Read the
  review table in the report, not only the mean.

Every Franco prompt or feature change is measured with `--baseline` against this run.
Tuning may only look at `dev` failures. `test` is reported, never tuned on.
