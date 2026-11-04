# Phase 1 report

Status 2026-11-04. Details: `api-probe.md`, `smoke_test.md`, `fetch_off_sample.md`, `score.md`; decisions in `docs/decisions.md`.

## Primary API: non-streaming `chat_completion`

`PUT _inference/document_extraction` for jina-ocr-v1 returns 400 `unsupported model: jina-ocr-v1` (probe check 6), so there is no document-extraction path. `chat_completion` works: temp-0 runs are identical (check 4) and streaming matches non-streaming (check 5). PDFs sent as a `file` part are rejected (400, only `text` and `image_url`), so PDFs must be rendered to images.

## Prompt: official

Ingredients-paragraph invention count: official 5, grounded 6 (both hit `FIBER`). Grounding buys nothing. The count is comparative only. Ingredients and allergens stay `unverified_text` whatever the prompt.

## Photo go/no-go: not decided

Only one kitchen photo exists (`yogurt.jpg`): carbs 27 g correct, 16/16 panel fields. The brief's pass criterion (at least 4 of 5 bucket photos parse carbs correctly) cannot be judged. The occluded, sideways and two-products cases are untested. Six scratch images (not scored, no truth) gave 3 with no carbs, 1 runaway loop and 1 cut-off flag, which is a reason to keep the framing guide in the UI.

## Cost per page

About $0.0016 per image: $0.080 for 50 images, from reported tokens (p50 705 in / 306 out) and the price env vars. Latency p50 3.4 s, p95 10.7 s. Cost stays a one-line mention, not a segment (decision of 2026-11-04). Still to check by hand: the price on the Serverless pricing table and the Billing > Usage > Inference screenshot.

## Hammer vs scalpel: not run

Probe check 11 is deferred: EIS returns 403 for third-party LLM endpoints in this org, from Kibana Console too. There is no comparison table. The script is in place if access is granted.

## OFF accuracy (50 images, scored against OFF, not against the pack)

| Language | Images | Carbs correct | Fields correct |
|---|---|---|---|
| de | 8 | 38% | 57% (32/56) |
| en | 8 | 75% | 80% (45/56) |
| es | 8 | 50% | 50% (28/56) |
| fr | 8 | 25% | 21% (12/56) |
| it | 8 | 62% | 64% (36/56) |
| ja | 2 | 0% | 36% (5/14) |
| pt | 8 | 50% | 48% (27/56) |
| **all** | 50 | 48% | 53% (185/350) |

The parser round (decimal commas, kJ/kcal, synonyms, column choice, merged-label runs) moved fields from 51% to 53%.

Why the other 165 fields are wrong or missing: model 92 (value not in the OCR text), shift 41 (merged two-line labels move every row below by one), column 12, synonym 10 (mostly 20+ language EU blobs, out of scope), truth_disagreement 8, unit 2, comma 0. Model read accuracy is 70%, so 70% is the most any parser could reach on this sample.

`nutrients_verified` (panel parsed, nothing cut off, numbers consistent) is a weak signal: 63% field accuracy among verified images against 28% among the rest. It does not mean "numbers are right"; the UI must show the source image next to every number.

## Open questions

1. Kitchen photos: add the five bucket photos plus occluded, sideways and two-products, then run `make smoke` to settle go/no-go.
2. Shift is the largest parser-side loss (41 fields). Fixing it needs a rule for merged rows that lost a value; `parse_suspect` misses swaps of similar-sized values (Nutella).
3. OFF is not ground truth: 8 fields look like a different recipe or revision, and the language tag is contributor-supplied. Hand-assign buckets (clean, glossy, stained, paper, multilingual) before putting a chart in the video.
4. Hammer comparison needs EIS access to a third-party LLM endpoint.
5. Manual checks: price table, billing screenshot, Jina On-Prem catalogue.
