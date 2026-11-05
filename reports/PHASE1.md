# Phase 1 report

Status 2026-11-05. Details: `api-probe.md`, `smoke_test.md`, `fetch_off_sample.md`, `score.md`,
`prompt_comparison.md`, `triage_model_misses.md`, `seed_off.md`, `off_live.md`; decisions in `docs/decisions.md`.

## Primary API: non-streaming `chat_completion`

`PUT _inference/document_extraction` for jina-ocr-v1 returns 400 `unsupported model: jina-ocr-v1`
(probe check 6), so there is no document-extraction path. `chat_completion` works: temp-0 runs are
identical (check 4) and streaming matches non-streaming (check 5). PDFs sent as a `file` part are
rejected (400, only `text` and `image_url`), so PDFs must be rendered to images.

## Prompt: `table` is the default, `official` stays selectable

Three prompts were looked at. The "grounded" prompt buys nothing on invented ingredients (official 5
unknown words, grounded 6, both hit `FIBER`) and is dropped. The official prompt ("Convert the
document to markdown.") and the table prompt (the same plus "Render nutrition tables as HTML
tables.") were compared on the same 50 images at temperature 0 (`reports/prompt_comparison.md`).
The choice rests on the model-side rows (what the prompt controls), not on total correct fields:

| | official | table |
|---|---|---|
| Model read accuracy (OFF value is in the text) | 70.6% | **74.3%** |
| Read accuracy after triage | 80.3% | **82.6%** |
| `model` misses | 91 | **78** |
| Looped outputs | 1 | **0** |
| Fields whose value only this prompt's text contains | 9 | **22** (sign test p = 0.029) |
| Completion tokens p50 / latency p50 / p95 | **306** / **3.4 s** / 10.7 s | 461 / 4.1 s / **8.1 s** |
| Cost for 50 images | **$0.080** | $0.087 |
| Parser-side losses (shift, column, synonym, unit) | 46 | 45 |

Table reads more of the numbers and never looped; official is cheaper and a little faster (+9% cost,
+0.6 s p50 for table). One run of 50 images, so treat it as a lean, not a proof.

## Photo go/no-go: not decided

Only one kitchen photo exists (`yogurt.jpg`): carbs 27 g correct, 16/16 panel fields. The brief's
criterion (at least 4 of 5 bucket photos parse carbs correctly) cannot be judged, and the occluded,
sideways and two-products cases are untested. Six scratch images (no truth) gave 3 with no carbs, 1
runaway loop and 1 cut-off flag, which is why the UI carries a framing guide. Smoke test postponed on request.

## Cost per page

About $0.0017 per image with the table prompt ($0.087 for 50, from reported tokens and the price env
vars). Latency p50 4.1 s. Cost stays a one-line mention, not a segment. Still to check by hand: the
price on the Serverless pricing table and the Billing > Usage > Inference screenshot.

## Hammer vs scalpel: not run

Probe check 11 is deferred: EIS returns 403 for third-party LLM endpoints in this org (from Kibana
Console too). There is no comparison table; the script is in place if access is granted.

## OFF accuracy (50 images, scored against OFF, not against the pack)

Default prompt (`table`), parser after the column and alignment rounds (`reports/score.md`):

| Language | Images | Carbs correct | Fields correct |
|---|---|---|---|
| de | 8 | 62% | 66% (37/56) |
| en | 8 | 75% | 75% (42/56) |
| es | 8 | 62% | 68% (38/56) |
| fr | 8 | 50% | 43% (24/56) |
| it | 8 | 62% | 77% (43/56) |
| pt | 8 | 50% | 54% (30/56) |
| ja (n=2, not charted) | 2 | 0% | 36% (5/14) |
| **all** | 50 | 58% | 63% (219/350) |

Official prompt on the same parser: 205/350 (59%), carbs 56%. Progress on the same cached OCR text
(official): 51% (179) at the first score, 53% (185) after commas / kJ / synonyms, 57% (201) after
order-aware alignment, 59% (205) after the column fixes; the table prompt went 204 to 219 with the
column fixes (HTML tables are where column choice matters).

Why the other 131 table-prompt fields are wrong or missing: model 78 (value not in the text), shift
20, column 14, synonym 11 (mostly 20+ language EU blobs, out of scope), truth_disagreement 8, unit 0,
comma 0. The model puts the OFF value in its text for 74% of fields, 83% once triaged misses that are
really "the pack differs from OFF" are counted as read, so the parser is at 63% against a ceiling of
about 74 to 83%.

`nutrients_verified` (panel parsed, nothing cut off, numbers consistent) is a weak signal: 69%
field accuracy (209/301) among the 43 verified images against 20% (10/49) among the other 7. It does not mean "numbers
are right"; the UI shows the source photo beside every number.

## Triage of the "model" misses

`reports/triage_model_misses.md`: one row per `model` miss of the official run (91 now; 92 when it
was first written), with the three numbers in the OCR text closest to the OFF value, the basis words
found in the text and a `suggested_cause`. `confirmed_cause` is blank for you to fill in after looking
at the photos; re-running the script keeps what you filled in, and `scripts/score.py` uses it.

| suggested_cause | count |
|---|---|
| misread | 52 |
| rounding_lt05 | 20 |
| basis_mismatch | 8 |
| revision | 6 |
| multilang_blob | 5 |

These are heuristics, not findings. `misread` is the residue. `rounding_lt05`: a number within 0.5 g
(5 kcal) of OFF is in the text. `basis_mismatch`: one serving size explains 3 or more fields of the
image, or the text shows only a serving basis. `revision`: 2 or more fields of the image are outside
tolerance but within 15% of OFF. Rows where OFF is 0 can only be `misread` or `multilang_blob`.

## Phase 2

Built and verified (163 tests with EIS, ES and OFF faked; headless-Chrome run of the real UI):
`app/es.py` (`food_labels` mapping, search, aggregations), `app/off.py` (cross-check with timeout and
circuit breaker), `app/allergens.py` (14 EU allergens in en/fr/es/pt/de/it, each tagged `contains` or
`may_contain`), `app/pipeline.py`, `app/main.py` (`/api/capture`, `/api/search`, `/api/aggs`, plus
`/api/doc`, `/api/health`, `/api/warmup`), `web/` (Capture, Result, Library), README.

Seeded (`reports/seed_off.md`): all 50 Open Food Facts samples are in the real `food_labels` index with
`source: off`, through the same code as `/api/capture` (47 in one run of 118 s and $0.083, 3 from a
trial run). 42 of 50 panels verified; OFF cross-check: 25 match, 12 mismatch, 13 not comparable (per
serving). Seeding found a real bug: under parallel load OFF answered 429/503 and the app reported 8
existing products as "not found"; a busy OFF is now status `error`, and `--recheck-off` fixed all 11
affected documents.

Open Food Facts live lookup (`reports/off_live.md`): barcode 021130077403 returned HTTP 200 in 1.8 s
with the shape the code expects. The product API had timed out for several minutes before that (a
transient outage), which is why the client now has a 10 s timeout and a circuit breaker, and
`scripts/seed_off.py --recheck-off` can fill in OFF statuses later without any OCR.

Not done: `docs/mock/` is not in the repo, so the UI follows BRIEF section 3 and a mock-up
comparison is still to do. Allergen matching is a keyword match: it cannot read negation ("free from
milk") and it matches invented words.

## Open questions

1. Kitchen photos: add the five bucket photos plus occluded, sideways and two-products, then run
   `make smoke`. The photo go/no-go is still undecided (postponed).
2. Fill `confirmed_cause` in the triage file; if `rounding_lt05` holds (20 fields), the tolerance or
   OFF's own rounding is part of the story.
3. The table prompt's 14 remaining `column` misses are the next parser target.
4. OFF is not ground truth (8 fields look like a different recipe or revision). Hand-assign
   buckets (clean, glossy, stained, paper, multilingual) before putting a chart in the video.
5. Hammer comparison needs EIS access to a third-party LLM endpoint.
6. Manual checks: price table, billing screenshot, Jina On-Prem catalogue; the mock file for the UI.
