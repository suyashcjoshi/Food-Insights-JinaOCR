# AGENTS.md — Food Insights · Jina OCR on Elastic Inference Service

Instructions for any coding agent (Claude Code, Codex, Cursor, Gemini CLI, …) and for humans. Claude Code reads this through `CLAUDE.md`.

Demo app + benchmark for an Elastic Community YouTube video. Pipeline: Extract → Ingest → Search.
Photograph a food label, send it to the EIS `document_extraction` task (`.jina-reader`, Jina OCR),
parse the nutrition panel into fields, index everything in Elasticsearch Serverless, and search it.
Two photos per pack (front: name, optional; back: the panel). A daily log (`food_log` index) adds up net
carbs (carbohydrate − fibre) and calories against the person's own limits, which live in the browser.
There is no barcode check and no "Verified" badge: both were removed on purpose.

## Stack (keep it this small)

- Python 3.12, managed with `uv` (`uv sync`, `uv run ...`).
- Backend: FastAPI + uvicorn. `httpx` for every call to `_inference/*` and
  to nothing else (the UI shows the exact HTTP request).
  Official `elasticsearch` client only for index / bulk / search / aggs.
- Images: Pillow (EXIF transpose, resize). PyMuPDF only if PDFs come in later.
- Frontend: `web/index.html` + `style.css` + five plain ES modules in `web/js/` (`main.js`, `result.js`, `today.js`,
  `library.js`, `util.js`; one-way imports, no cycles), no build
  step, served as static files by FastAPI. No React, no Streamlit.
- Tooling: `ruff` (lint+format), `pytest` for the parser and scoring code,
  `python-dotenv` for `.env`. A `Makefile` with `setup`, `smoke`,
  `fetch-sample`, `score`, `seed`, `serve`, `test`, `lint`.

## Layout

```
app/            FastAPI app: eis.py, ocr.py, parse.py, naming.py, diary.py, allergens.py, es.py, pipeline.py, main.py
web/            static frontend (phone-first): index.html, style.css, js/ (5 ES modules)
scripts/        score.py, smoke_test.py, fetch_off_sample.py, seed_off.py, ui_screenshots.py
tests/          pytest; fixtures/ holds real model output for the cases that broke the parser
data/kitchen/   my own phone photos and their ground truth (committed; they are mine)
data/off/       Open Food Facts sample (git-ignored; fetched by script; attribution kept)
screenshots/    the images the README shows (capture, result, raw, library)
_notes/         local notes, results and working scripts (git-ignored, never committed)
```

## Environment

`.env` (git-ignored) with `ES_URL` and `ES_API_KEY`. Auth header is
`Authorization: ApiKey <key>`. Never print the key, never commit it. The
Serverless project is `FoodInsights` (Azure eastus); default EIS endpoints
already exist (`.jina-reader` for document_extraction), nothing to PUT.

## Rules that bite

- Main read: `POST _inference/document_extraction/.jina-reader` (preview, Serverless). Body is
  `{"input":[{"content":{"type":"image","format":"base64","value":"data:…"}}]}`; the answer is
  `document_extraction[0].content` Markdown. No prompt, no `usage` in the response. It stores nothing:
  indexing is a separate call. `pdf` needs `task_settings.parameters.preset: "ocr"` when it has no text layer.
- First call after idle can take 2–3 minutes (cold start). Use a 180 s client
  timeout in scripts; add a `warmup()` that sends a tiny image and ignores the
  result.
- Always `ImageOps.exif_transpose()` then resize so the long edge ≤ 1600 px
  before base64-encoding. A sideways image makes the model loop.
- Output is Markdown with blank lines between items; tables often come back
  as HTML `<table>`, but a Nutrition Facts panel came back as one line per
  nutrient (`Total Carbohydrate 27g 10%`). The parser must handle both.
- The model invents text for anything cut off at the frame edge. Never parse
  ingredients/allergens into fields; keep them as `unverified_text`.
- The reader is preview (not GA in 9.6) and returns no token usage today; that may change. Record wall time (`ocr_ms`), the endpoint and the task on every call, and ignore response fields we do not know. If a `usage` field appears later, add it to telemetry then.
- Open Food Facts is data for the benchmark and the sample Library only (`scripts/fetch_off_sample.py`,
  `score.py`, `seed_off.py`); the app does not call it. When fetching: a descriptive `User-Agent` from
  `OFF_USER_AGENT` in `.env`, ≤ 10 search requests/min, product JSON cached to disk.
- Do not add OpenCV, deskew, or any CV pipeline. Framing is the user's job.
- Do not build chat/RAG, reranking, or embeddings in this repo yet. Those are
  a follow-up video.
- No barcode check and no verification badge (removed on purpose; do not re-add).
- The app compares totals with the person's own limits and never advises: no "you should", no targets we
  choose, no recommendations. Defaults (100 g net carbs, 1800 kcal) are only starting values the person edits.
- Net carbs = carbohydrate − fibre, never below 0; if fibre was not read, count the full carbohydrate and say
  so. The rule lives in `app/diary.py` (and is mirrored in `web/js/util.js` for display): change both.
- A log entry is a snapshot (label numbers × portions); hand edits are stored in `edited_fields`, never
  silently mixed with what the model read. The product name from the front photo is a guess: always editable.
- Index writes use `refresh=True` (0.9 s) because Serverless refreshes every ~5 s and `wait_for` made each
  save feel slow. Fine at demo volume; do not copy it into a production write path.
- Only the `document_extraction` reader is used. The older `chat_completion` + `jina-ocr-v1` path was
  removed on purpose (expected to be sunset); do not re-add it, a prompt picker or token/cost telemetry.
- Say "open weights, non-commercial licence" about the model, never "open source".

## Conventions

- Small functions, type hints, docstrings only where the why isn't obvious.
- Every script prints a one-line summary and writes a report file under `_notes/reports/`
  (git-ignored), so a run never dirties the tree.
- Keep a dated log of decisions in `_notes/docs/decisions.md` (local, git-ignored).
- Code ported from other projects keeps a one-line attribution comment at the top of the file; MIT here.
