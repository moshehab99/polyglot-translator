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
letters: `ana msh fahem enta 3ayez eh`. This eval measures how the **current** app
handles that input, through the same real path as the dialect eval:

```
Settings (.env) -> build_provider -> TranslationService.translate(text, "auto", target)
```

1. **Detection** (every item): `translate(text, "auto", "en")`, or target `"fr"` for
   items labelled `en`. `detected_source` must equal the label. The English or French
   output is saved for manual review but not scored.
2. **Arabization** (ar/arz items only): `translate(text, "auto", item.label)`, so `arz`
   items go to Egyptian Arabic and `ar` items go to MSA. The output is compared with the
   item's `arabic` reference:
   - **chrF** (character n-grams 1..6, beta = 2, 0-100) after Arabic normalisation:
     tashkeel and tatweel removed, أ/إ/آ -> ا, ة -> ه, ى -> ي, punctuation dropped,
     spaces collapsed.
   - **Latin leak**: the output contains a Latin-script word that is not in the
     reference.

Controls (real English/French/Spanish/... text) only get the detection pass. A control
detected as `ar`/`arz` is a false positive.

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

**The `arabic` reference** is a faithful transliteration of exactly what was written, in
normal Egyptian spelling:
- No rephrasing and no correcting.
- Follow the writer's choices: 3ayez -> عايز, 3awez -> عاوز.
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

Current composition: 60 items (f001–f060): 45 `arz`, 5 `ar`, 10 controls (4 en, 2 fr,
2 es, 1 it, 1 de). Split: 40 dev, 20 test (15 arz, 2 ar, 3 controls). A control or `ar`
item appears roughly every five lines, so a small `--limit` mixes labels.

| Tag | arz | ar | control |
|---|---|---|---|
| clear | 12 | 1 | 0 |
| short | 8 | 4 | 1 |
| numerals | 28 | 3 | 0 |
| no_numerals | 17 | 2 | 0 |
| code_switch | 8 | 0 | 0 |
| chat | 10 | 0 | 5 |
| ambiguous | 11 | 0 | 2 |
| shared | 0 | 4 | 0 |
| long | 6 | 0 | 0 |
| control | 0 | 0 | 10 |

Tests check the real file:
- `short` means at most 3 words.
- `numerals` / `no_numerals` match the text.
- `long` has at least 2 sentences.
- Every tag is used at least 3 times.
- The test split is 25–40% of items and contains arz, ar and controls.

```
uv run pytest tests/test_franco_dataset.py -q
```
