# AGENTS.md — Food Insights · jina-ocr-v1 on Elastic Inference Service

Instructions for any coding agent (Claude Code, Codex, Cursor, Gemini CLI, …) and for humans. Claude Code reads this through `CLAUDE.md`.

Demo app + benchmark for an Elastic Community YouTube video. Photograph a food
label, send it to `jina-ocr-v1` through the Elastic Inference Service (EIS),
parse the nutrition panel into verified fields, cross-check against
Open Food Facts by barcode, index everything in Elasticsearch Serverless, and
search it. Read `docs/BRIEF.md` before doing anything; it holds the story,
the decisions already made, and the EIS gotchas learned the hard way.

## Phase we are in

**Phase 1 — test assumptions, scaffold the skeleton, fetch sample data.**
No product UI yet. Deliverables for this phase are listed in
`docs/BRIEF.md` § "Phase 1 tasks". Each check has a pass/fail criterion;
write results to `reports/` as Markdown with the raw responses attached.

## Stack (keep it this small)

- Python 3.12, managed with `uv` (`uv sync`, `uv run ...`).
- Backend: FastAPI + uvicorn. `httpx` for every call to `_inference/*` and
  to Open Food Facts (we want to show the exact HTTP request in the UI later).
  Official `elasticsearch` client only for index / bulk / search / aggs.
- Images: Pillow (EXIF transpose, resize). PyMuPDF only if PDFs come in later.
- Frontend (phase 2): one `web/index.html` + `app.js` + `style.css`, no build
  step, served as static files by FastAPI. No React, no Streamlit.
- Tooling: `ruff` (lint+format), `pytest` for the parser and scoring code,
  `python-dotenv` for `.env`. A `Makefile` with `setup`, `probe`, `smoke`,
  `fetch-sample`, `score`, `serve`, `test`.

## Layout

```
app/            FastAPI app (phase 2) — eis.py, ocr.py, parse.py, off.py, es.py, main.py
scripts/        api_probe.py, smoke_test.py, fetch_off_sample.py, score.py, benchmark_hammer.py
data/kitchen/   my own phone photos (committed; they are mine)
data/off/       Open Food Facts sample (git-ignored; fetched by script; attribution kept)
reports/        probe + smoke + score reports (Markdown + JSON)
docs/           BRIEF.md, console-requests.md, decisions.md (append-only log)
web/            static frontend (phase 2)
```

## Environment

`.env` (git-ignored) with `ES_URL` and `ES_API_KEY`. Auth header is
`Authorization: ApiKey <key>`. Never print the key, never commit it. The
Serverless project is `FoodInsights` (Azure eastus); default EIS endpoints
already exist, nothing to PUT for chat_completion.

## Rules that bite

- OCR endpoint is `chat_completion`; EIS rejects `repetition_penalty` and
  `no_repeat_ngram_size`. Only `max_completion_tokens`, `temperature`,
  `top_p`, `stop` are safe. Cap `max_completion_tokens` at 2048.
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
- Token usage arrives on the last SSE chunk (streaming) or in `usage`
  (non-streaming). Record `prompt_tokens`, `completion_tokens`, wall time
  on every call.
- Open Food Facts: send `User-Agent: FoodInsights/0.1 (<contact email>)`,
  ≤ 10 search requests/min, cache product JSON to disk, treat 503 and
  `status: 0` as "no match", never as an error that stops the run.
- Do not add OpenCV, deskew, or any CV pipeline. Framing is the user's job.
- Do not build chat/RAG, reranking, or embeddings in this repo yet. Those are
  a follow-up video.

## Reference code (colleague's demo)

Two files from a colleague's internal demo, `eis.py` and `ocr.py`, live in
`reference/colleague/` (git-ignored). Read them; do **not** copy them in.
Port only these pieces into `app/eis.py` / `app/ocr.py`, smaller and with
our names: pooled httpx client, retry with backoff on 429/5xx, `warmup()` /
keep-warm, SSE parsing of `delta.content` + trailing `usage`, the
runaway-repetition detector (distinct 5-gram ratio), and
`strip_region_tokens()` for the grounded prompt. Leave out everything
Frankenstein-specific (categories, bulk library ingest, Agent Builder).
Add a one-line attribution comment at the top of each ported file and a
credits line in README.

## Conventions

- Small functions, type hints, docstrings only where the why isn't obvious.
- Every script prints a one-line summary and writes a report file.
- Append every decision to `docs/decisions.md` with the date.
- Credit upstream: `elastic/demos/jina-ocr-v1` and the colleague's
  adaptation (see BRIEF) in README when phase 2 starts; MIT here.
