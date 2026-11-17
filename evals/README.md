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

Current composition: 80 items, 40 `ar` and 40 `arz`, with labels alternating in file
order so a small `--limit` still covers both.

| Tag | ar | arz |
|---|---|---|
| clear | 12 | 6 |
| short | 8 | 6 |
| shared | 5 | 0 |
| topic_swap | 10 | 6 |
| no_markers | 0 | 6 |
| code_switch | 2 | 5 |
| chat_spelling | 0 | 5 |
| polite | 0 | 6 |
| long | 8 | 6 |

### How to run

The runner CLI (`uv run python -m evals.dialect`) arrives in the next milestone. Tests
never call a real API:

```
uv run pytest tests/test_eval_dataset.py -q
```
