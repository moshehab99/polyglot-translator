# Dialect detection eval (2026-11-18T03:02:47+00:00)

## Run

| Field | Value |
|---|---|
| Provider | gemini |
| Model | `gemini-3.5-flash-lite` |
| Target | en |
| Prompt fingerprint | `2ac34465d2fb` |
| Git commit | `5627e9e` |
| Dataset | `evals/data/dialect.jsonl` (95 items) |
| Dataset sha256 | `01a84f89ac07cce8` |
| Filters | tag=-, limit=- |
| Attempted / not run | 95 / 0 |
| Median latency | 766 ms |

## Accuracy

**100.0%** (95/95), 95% Wilson CI 96.1% to 100.0%. Wrong: 0, errors: 0.

## Confusion matrix

| label \ predicted | ar | arz | other | error |
|---|---:|---:|---:|---:|
| **ar** | 45 | 0 | 0 | 0 |
| **arz** | 0 | 50 | 0 | 0 |

## Per label

| Label | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| ar | 100.0% | 100.0% | 100.0% | 45 |
| arz | 100.0% | 100.0% | 100.0% | 50 |

## Per tag

| Tag | n | Correct | Accuracy |
|---|---:|---:|---:|
| chat_spelling | 6 | 6 | 100.0% |
| clear | 23 | 23 | 100.0% |
| code_switch | 7 | 7 | 100.0% |
| long | 14 | 14 | 100.0% |
| no_markers | 11 | 11 | 100.0% |
| polite | 6 | 6 | 100.0% |
| shared | 5 | 5 | 100.0% |
| short | 19 | 19 | 100.0% |
| topic_swap | 18 | 18 | 100.0% |

## Wrong and error items (0)

None.
