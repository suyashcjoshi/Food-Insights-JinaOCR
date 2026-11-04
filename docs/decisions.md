# Decision log (append-only)

- 2026-11-04 — Platform: Elastic Cloud Serverless, project FoodInsights, Elasticsearch (general purpose), Azure eastus. Region line dropped; global audience.
- 2026-11-04 — Model access: EIS only in the demo; Jina API and Jina On-Prem mentioned, not shown.
- 2026-11-04 — Scope: OCR → verified fields → OFF cross-check → index → keyword search + allergen aggregation. No RAG/rerank/embeddings (follow-up video).
- 2026-11-04 — Dataset: own phone photos + Open Food Facts sample. Web-search images are private test only.
- 2026-11-04 — Two-tier output: nutrition panel fields are "verified"; ingredients/allergens are "unverified text". Driven by the yogurt test (`TREE HUTS (CREAM)`).
- 2026-11-04 — No CV preprocessing beyond EXIF rotate + resize. Framing guide in UI instead.
- 2026-11-04 — Stack: Python 3.12 + uv, FastAPI, httpx, Pillow, elasticsearch client; static single-page frontend; no React/Streamlit.
- 2026-11-04 — Primary API: to be decided by probe check 6 (document_extraction PUT). Fallback: non-streaming chat_completion.
- 2026-11-04 — Prompt: to be decided by probe check 10 (invention count).
- 2026-11-04 — Scaffold: moved handoff files into docs/ and repo root; uv project on Python 3.12; `app/eis.py` ports pooled client, retry/backoff, SSE parsing and warmup from the colleague's `eis.py` (permission confirmed by Suyash). Loop detector and region stripping will be ported into `app/ocr.py` later.
- 2026-11-04 — Open Food Facts User-Agent contact: suyash.joshi@elastic.co.
