# Project brief — Food Insights with jina-ocr-v1 on EIS

Last updated: 2026-11-04. Owner: Suyash (Elastic Developer Advocate).
This file is the handoff from a long planning conversation and is written for any coding agent or human contributor. Treat it as the
source of truth for scope and decisions; append changes to `decisions.md`.

## 1. What we are making and why

An educational video for the Elastic Community YouTube channel (~10 min,
show-not-teach) plus a small public demo app and a Search Labs post / README
that carry the how-to.

**Thesis:** you don't need to throw a frontier LLM at every document. A
purpose-built small model (`jina-ocr-v1`, 3.4B MoE, 570M active) running as a
managed service inside Elastic (EIS) reads labels accurately, fast, and for a
fraction of the cost — and the whole pipeline stays inside your Elastic
project: one key, one bill, no external AI vendor.

**Narrative:** "A label is a contract." Consumer hook: a parent of a child
with Type 1 diabetes needs the carbohydrates number off any label, in any
language, from a creased wrapper on holiday. B2B payoff: the same extraction
problem at the scale of a retailer / manufacturer / caterer with 40,000
products across 30 markets (allergen compliance, e.g. UK Natasha's Law).
Elastic payoff: "show me every product in the catalogue, any language, that
lists peanuts" — search + one aggregation.

**Hard boundary:** the app reads labels. It never computes a dose, never
suggests what to eat. Show the number and the source image; add one line
"reads the label, never advises". Allergens and ingredients are shown as
*unverified text*, never as parsed fields (see § 6).

## 2. How this differs from existing work (do not duplicate)

- `elastic/demos/jina-ocr-v1` (official): archive-style demo, categories
  incl. multilingual/labels/tables, Agent Builder chat, API inspector.
- Colleague's adaptation (Frankenstein manuscripts, FastAPI + nginx, search
  by photo, batch ingest, Agent Builder chat): retrieval story about EIS
  infrastructure for a meetup. Its `eis.py`/`ocr.py` patterns are worth
  reusing with permission: pooled httpx client, retries with backoff,
  warm-up/keep-warm, runaway-repetition detector (distinct 5-gram ratio),
  region-token stripping for the grounded prompt.
- Search Labs post "56 scanned pages to a cited answer in 5 minutes": scanned
  PDF → OCR via EIS → hybrid RAG, Node/React. Repo under
  `elastic/elastic-labs/supporting-blog-content/jina-ocr-v1-hybrid-rag-elasticsearch`.

**Our distinct angle:** photos of physical objects (not document scans),
structured field extraction with ground truth and per-bucket accuracy,
cross-check against a public database by barcode, honest two-tier output
(verified vs unverified), and a scalpel-vs-hammer cost benchmark run inside
the same project.

## 3. Decisions already made

| Topic | Decision |
|---|---|
| Platform | Elastic Cloud **Serverless**, project `FoodInsights`, type Elasticsearch (general purpose), Azure eastus. Global audience, region line dropped. |
| Model access | **EIS only** in the demo. Mention Jina API (outside project, separate billing) and Jina On-Prem (Docker, air-gapped, CC BY-NC weights / commercial via Elastic Sales) as alternatives in one sentence each. |
| Demo scope | OCR → structured fields → cross-check → index → keyword search + allergen aggregation. **No** RAG, reranker, or embeddings in this video. |
| Dataset | Own phone photos for footage + **Open Food Facts** sample for scale and ground truth (ODbL; images CC BY-SA; attribute). Patents, floor plans, archives rejected. |
| Input type | Photos (curved packs, paper wrappers, stains). Model does no CV preprocessing; we do EXIF rotate + resize only. |
| Output format | Model returns Markdown; nutrition panel came back as one line per nutrient, not a table. Parser is line-based with an HTML-table fallback. |
| Prompt | Test official vs "grounded" prompt (see § 5). Pick by measured invention count. |
| UI (phase 2) | One page, three states: Capture → Result → Library. Pencil mock exists. Verified card (panel fields) + amber "Unverified text · check the pack" box + barcode cross-check chip + telemetry line + raw view (output, prompt toggle, exact request). |
| How-to lives | README + Search Labs post. Video shows ≤ 3 API calls. |

## 4. EIS facts verified in the FoodInsights project (2026-11-04)

- `GET _inference/_all` lists `.jina-ocr-v1-chat_completion`
  (task_type `chat_completion`, service `elastic`, model_id `jina-ocr-v1`,
  status ga, properties `multimodal, ocr-only, zero-data-retention`,
  regions: gcp us-east4). Also present: `.jina-embeddings-v5-text-small`,
  `.jina-embeddings-v5-omni-small/nano`, `.jina-reranker-v3.5`,
  `.jina-clip-v2`, and frontier LLM endpoints
  (`.google-gemini-3.8-flash-chat_completion`,
  `.openai-gpt-6-astra-chat_completion`,
  `.anthropic-claude-5.5-opus-chat_completion`,
  `.nvidia-nemotron-3.5-super-vl-chat_completion`, …).
- First OCR run (streaming): yogurt tub photo, 1920×1440, curved, right edge
  cut off. `prompt_tokens 905, completion_tokens 390`. Nutrition panel 24/24
  correct. Ingredients column (cut off at frame edge) hallucinated:
  `TREE NUTS (COCONUT)` → `TREE HUTS (CREAM)`, `VITAMIN A PALMITATE` →
  `VITAMIN A (VITAMIN E)`, `YOGURT CULTURES` → `FIBER`, invented ZIP digit.
  Ground truth and raw output are in `data/kitchen/yogurt.*` (to add).
- API shapes available (Elasticsearch API docs, main):
  - Streaming: `POST _inference/chat_completion/{id}/_stream` (SSE).
  - Non-streaming: `POST _inference/chat_completion/{id}` (GA 9.6; `elastic`
    service supported; default timeout 120 s; body supports `messages`,
    `max_completion_tokens`, `temperature`, `top_p`, `stop`; content parts
    `text`, `image_url`, `file` with base64 PDF).
  - **Document extraction (experimental, 9.6):**
    `PUT/POST _inference/document_extraction/{id}`; input `content` of
    `type: image|pdf`, `format: base64|url`; returns
    `document_extraction[].content/format/metadata`. Purpose-built for this
    job. **Unknown whether EIS will mint one for `jina-ocr-v1` — test it.**
  - Multimodal embedding: `POST _inference/embedding/{id}` (follow-up video).
- Model has no native PDF support (reads images via PIL). PDFs must be
  rendered to page images unless `document_extraction` does it server-side.
- EIS billing: per million tokens; input + output for chat models. Price per
  model on the Serverless pricing table (Suyash checks manually). Usage shows
  in Cloud Console → Billing → Usage, dimension "Inference".

## 5. Prompts

Official (model card): `Convert the document to markdown.`

Grounded (to test): `Transcribe only text that is fully visible in the
image. Where text is cut off or unreadable, write […] instead of guessing.
Return Markdown.` — colleague's variant suppressed blank-page hallucination
but leaked region tokens like `<|ref|>…<|/ref|>` that must be stripped.

Hammer prompt (frontier LLM, for the benchmark only): `Read this nutrition
label. Return ONLY JSON with keys energy_kcal, fat_g, saturated_fat_g,
carbohydrates_g, sugars_g, protein_g, salt_g (or sodium_mg), serving,
allergens_raw. Use null when not visible.`

## 6. Data model (index `food_labels`, one doc per capture)

```
id                  keyword   uuid
captured_at         date
source              keyword   kitchen | off | demo
image_path          keyword   local path or OFF URL
barcode             keyword   nullable
product_name        text
language            keyword   from OFF `lang` or user-set; never model-detected
nutrients           object    { energy_kcal, fat_g, saturated_fat_g,
                                carbohydrates_g, sugars_g, added_sugars_g,
                                fiber_g, protein_g, salt_g, sodium_mg,
                                serving_text, per: "serving"|"100g" }
nutrients_verified  boolean   parsed from the panel AND no edge cut-off flag
off_match           object    { status: match|mismatch|not_found|error,
                                carbohydrates_100g, checked_at }
unverified_text     text      ingredients / allergens / claims as read
raw_markdown        text      model output verbatim
plain_text          text      tables flattened for BM25
telemetry           object    { endpoint, prompt_variant, prompt_tokens,
                                completion_tokens, ocr_ms, cost_est }
```

### Ground truth schema

Every ground-truth record (`data/kitchen/<name>.truth.json` and each line of
`data/off/manifest.jsonl`) has two tiers:

```
{ "image": ..., "barcode": ...,
  "panel":     { "per": "serving"|"100g", "serving_text": ..., "nutrients": { ... } },
  "secondary": { "ingredients_visible": ..., "known_inventions": [...],
                 "scored": false, "note": ... } }
```

- `panel` is the Nutrition Facts panel: primary, and the only thing scored.
  Accuracy numbers (smoke test, `score.py`, hammer comparison) read
  `panel.nutrients` and nothing else. OFF records use `per: "100g"` with
  `nutrients` from `nutriments` (`energy-kcal_100g`, `fat_100g`,
  `saturated-fat_100g`, `carbohydrates_100g`, `sugars_100g`, `proteins_100g`,
  `salt_100g`).
- `secondary` is everything else (ingredients, allergens, claims). It is
  never scored. It exists only for the invention check (probe check 10):
  count words in the model's ingredients block that are not in
  `ingredients_visible`, and flag hits on `known_inventions`. For OFF records
  it is `{"scored": false}` unless there is something to record.

## 7. Phase 1 tasks (for the coding agent)

Write results to `reports/<task>.md` + `reports/<task>.json`. Pass/fail is
decided by the criteria below, not by vibes.

### 7.1 Scaffold
- `uv init`, `pyproject.toml` with deps: fastapi, uvicorn, httpx, pillow,
  python-dotenv, elasticsearch, ruff, pytest. Layout from `CLAUDE.md`.
- `.env.example`, `.gitignore` (`.env`, `data/off/`, `reports/*.json`).
- `Makefile` targets: setup, probe, smoke, fetch-sample, score, test.
- `app/eis.py` with ONE function per API shape (`ocr_chat_stream`,
  `ocr_chat`, `ocr_document_extraction`) sharing a pooled httpx client,
  180 s timeout, retry with backoff on 429/502/503/504, `warmup()`.
  No other app code yet.

### 7.2 `scripts/api_probe.py` — API shape checks (run against the project)
Each check records request (key redacted), status, latency, response excerpt.
1. `GET _inference/_all` → PASS if `.jina-ocr-v1-chat_completion` present.
2. `GET _inference/chat_completion/.jina-ocr-v1-chat_completion` → save
   metadata (properties, regions) for the video.
3. `GET _inference/_region_policy` → PASS if 404 "No region policy".
4. Non-streaming OCR on `data/kitchen/yogurt.jpg`, `temperature: 0`, twice →
   PASS if 200, `choices[0].message.content` non-empty, `usage` present,
   and both runs identical.
5. Streaming OCR, same image → PASS if concatenated `delta.content` equals
   the non-streaming content (ignoring whitespace).
6. `PUT _inference/document_extraction/label-ocr` with
   `{"service":"elastic","service_settings":{"model_id":"jina-ocr-v1"}}` →
   record PASS/FAIL and the exact error body if any. **This decides the
   primary API.**
7. If 6 PASS: `POST _inference/document_extraction/label-ocr` with the
   yogurt image as base64 and `task_settings.output_format: markdown` →
   PASS if `document_extraction[0].content` non-empty; diff vs check 4.
8. If 6 PASS: same with a one-page PDF (render the yogurt image to PDF with
   Pillow) using `type: pdf` → record outcome.
9. Non-streaming OCR with a `file` content part (base64 PDF) → record
   outcome (expected to fail; model has no PDF support).
10. Grounded prompt vs official prompt on the yogurt image → count
    differences in the ingredients block against the ground-truth file;
    write the comparison table.
11. Hammer: `POST _inference/chat_completion/.google-gemini-3.8-flash-chat_completion`
    (non-streaming) with the yogurt image and the hammer prompt → record
    tokens, latency, JSON validity, field accuracy vs ground truth. Repeat
    with `.openai-gpt-6-astra-chat_completion` if time allows.

### 7.3 `scripts/smoke_test.py` — real photos
Input: `data/kitchen/*.jpg` (Suyash adds five: clean, glossy/curved,
stained, paper wrapper, non-English; plus `occluded.jpg` with a finger over
the carbs row, `sideways.jpg`, `two_products.jpg`).
For each: EXIF transpose → resize ≤1600 px → OCR (primary API) → parse →
print `carbs_parsed` vs `carbs_pack` (from `panel.nutrients` in `data/kitchen/<name>.truth.json`)
→ tokens, ms. PASS if ≥ 4/5 bucket photos parse carbs correctly. Record
what the model did on occluded / sideways / two_products as prose.

### 7.4 `scripts/fetch_off_sample.py` — Open Food Facts sample
- API v2 search, e.g.
  `GET https://world.openfoodfacts.org/api/v2/search?fields=code,product_name,lang,countries_tags,image_nutrition_url,nutriments&page_size=50&countries_tags_en=<country>`
  for a spread of countries/languages (uk, france, germany, portugal, spain,
  italy, japan or china if available). Keep only products with
  `image_nutrition_url` and `nutriments.carbohydrates_100g`.
- Download the nutrition image (full size, not the 400 px variant) to
  `data/off/<code>.jpg`; write `data/off/manifest.jsonl` with code, name,
  lang, country, image URL, and ground-truth nutriments per 100 g
  (`energy-kcal_100g, fat_100g, saturated-fat_100g, carbohydrates_100g,
  sugars_100g, proteins_100g, salt_100g`).
- Target 50 images: 10 per bucket where buckets are assigned by eye later
  (clean / glossy / stained / paper / multilingual); for now balance by
  language. Respect User-Agent and ≤10 search calls/min. Cache responses.
- Write `data/off/ATTRIBUTION.md` (ODbL for data, CC BY-SA for images,
  link to each product page).

### 7.5 `app/parse.py` + tests
- Line-based nutrient parser: handles `Label 27g 10%`, `Incl. 18g Added
  Sugars 36%`, `Energy 1890 kJ / 448 kcal`, EU labels (`Hidratos de carbono
  72 g`, `Kohlenhydrate`, `Glucides`, `Carboidrati`) via a small synonym
  map; HTML `<table>` fallback; unit normalisation (g, mg, mcg, kJ, kcal);
  flags: `edge_cutoff_suspected` when any line ends mid-word or the model
  output contains `[…]`.
- `pytest` cases from the yogurt output and 3 OFF samples.

### 7.6 `scripts/score.py`
- Run all `data/off/*.jpg` through the primary API, parse, compare to
  manifest ground truth (per 100 g; tolerate ±0.5 g, ±5 kcal). Output per
  language accuracy and overall, plus tokens and ms percentiles, as a
  Markdown table and JSON. This becomes the chart in the video.

### 7.7 Report
`reports/PHASE1.md`: one page. Primary API chosen and why, prompt chosen,
photo go/no-go, cost per page (tokens × price from Suyash), hammer vs scalpel
table, OFF accuracy table, open questions.

## 8. Things Suyash checks manually (not the agent)
- jina-ocr-v1 price on the Serverless pricing table; put it in `.env` as
  `EIS_OCR_PRICE_PER_MTOK_IN` / `_OUT` once known.
- Billing → Usage → Inference after the probe run (screenshot for video).
- Permission from colleague to reuse `eis.py`/`ocr.py` patterns; credit.
- Whether `jina-ocr-v1` is in the Jina On-Prem catalogue (for the one-line
  on-prem mention; not required for the demo).

## 9. Talking points to preserve (for the video; do not lose these)
- Subword tokens split words mid-stream; ALL-CAPS text fragments more and
  costs more tokens (`ING RED I ENTS`).
- SSE is what streaming looks like on the wire; non-streaming exists.
- Chat completion = messages in, assistant message out; the OCR model only
  "talks" in Markdown (`ocr-only`).
- `document_extraction` is the purpose-built door; `chat_completion` is the
  generic one.
- The model can't run in an ingest pipeline (chat_completion endpoints are
  not pipeline-callable) → OCR lives in the app backend.
- Framing is the real guardrail: cut-off text gets invented. Show
  `TREE HUTS (CREAM)`.
- Cold start, keep-warm, EIS rejects repetition params, cap output tokens.
- Zero data retention + ocr-only properties on the endpoint metadata.
- Cost: 905 in / 390 out tokens for one label → × price.

## 10. Credits and licences to carry into README
- Jina OCR v1 by Jina AI (Elastic). Weights CC BY-NC 4.0 on Hugging Face;
  EIS usage under Elastic subscription.
- Open Food Facts: database ODbL, images CC BY-SA; attribute per product.
- Upstream demo code patterns: `elastic/demos/jina-ocr-v1` and the
  colleague's adaptation (name to add with permission).
- Own photos: Suyash. Web-search images were used for private testing only
  and must not appear in the video or repo.
