"""FastAPI app: /api/capture, /api/search, /api/aggs, plus the static frontend in web/.

    uv run uvicorn app.main:app --reload     (or: make serve)

Reads labels, never advises: no endpoint computes a dose or suggests what to eat.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import eis, es, pipeline
from app.allergens import NAMES

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 15 * 1024 * 1024

app = FastAPI(title="Food Insights", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _tri(value: str | None) -> bool | None:
    """Query flag: true / false / absent."""
    return None if value in (None, "") else value.lower() in ("1", "true", "yes")


def _check_kind(kind: str | None) -> None:
    if kind and kind not in es.KINDS:
        raise HTTPException(400, f"allergen_kind must be one of {list(es.KINDS)}")


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "index": es.index_name(),
        "prompts": list(eis.PROMPTS),
        "prompt_texts": eis.PROMPTS,
        "default_prompt": eis.DEFAULT_PROMPT,
        "endpoint": eis.ocr_endpoint(),
        "allergen_names": NAMES,
        "allergen_kinds": list(es.KINDS),
    }


@app.post("/api/warmup")
async def warmup() -> dict:
    """First call after idle can take 2-3 minutes; the UI fires this on load and ignores the result."""
    seconds = await asyncio.to_thread(eis.warmup)
    return {"seconds": round(seconds, 1)}


@app.post("/api/capture")
async def capture(
    image: Annotated[UploadFile, File()],
    prompt: Annotated[str, Form()] = eis.DEFAULT_PROMPT,
    barcode: Annotated[str | None, Form()] = None,
    language: Annotated[str | None, Form()] = None,
    product_name: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "demo",
    index: Annotated[bool, Form()] = True,
) -> JSONResponse:
    if prompt not in eis.PROMPTS:
        raise HTTPException(400, f"prompt must be one of {sorted(eis.PROMPTS)}")
    data = await image.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(400, "send one image up to 15 MB")
    try:
        result = await asyncio.to_thread(
            pipeline.capture,
            data,
            prompt_variant=prompt,
            barcode=(barcode or "").strip() or None,
            language=(language or "").strip() or None,
            product_name=(product_name or "").strip() or None,
            source=source,
        )
    except OSError as exc:  # Pillow could not open the file
        raise HTTPException(400, f"not an image: {exc}") from exc
    except pipeline.OcrError as exc:
        c = exc.call
        return JSONResponse(
            {
                "error": "ocr_failed",
                "status": c.status,
                "detail": c.raw[:400],
                "request": c.request,
            },
            status_code=502,
        )
    result["indexed"] = {"ok": False, "skipped": True}
    if index:
        try:
            await asyncio.to_thread(es.index_doc, result["doc"])
            result["indexed"] = {"ok": True, "index": es.index_name()}
        except Exception as exc:  # noqa: BLE001 - the read still succeeded; show it, say it was not stored
            result["indexed"] = {"ok": False, "error": str(exc)[:300]}
    result["image_url"] = "/" + result["doc"]["image_path"]
    return JSONResponse(result)


@app.get("/api/search")
async def search(
    q: str = "",
    allergen: Annotated[list[str] | None, Query()] = None,
    language: str | None = None,
    verified: str | None = None,
    size: int = Query(24, ge=1, le=100),
    allergen_kind: str | None = None,
) -> dict:
    _check_kind(allergen_kind)
    try:
        return await asyncio.to_thread(
            es.search, q, allergen or [], language or None, _tri(verified), size, allergen_kind
        )
    except Exception as exc:
        raise HTTPException(503, f"search unavailable: {str(exc)[:200]}") from exc


@app.get("/api/aggs")
async def aggs(
    q: str = "",
    allergen: Annotated[list[str] | None, Query()] = None,
    language: str | None = None,
    verified: str | None = None,
    allergen_kind: str | None = None,
) -> dict:
    _check_kind(allergen_kind)
    try:
        return await asyncio.to_thread(
            es.aggregate, q, allergen or [], language or None, _tri(verified), allergen_kind
        )
    except Exception as exc:
        raise HTTPException(503, f"aggregation unavailable: {str(exc)[:200]}") from exc


@app.get("/api/doc/{doc_id}")
async def doc(doc_id: str) -> dict:
    found = await asyncio.to_thread(es.get_doc, doc_id)
    if found is None:
        raise HTTPException(404, "no such capture")
    return found


(ROOT / "data" / "captures").mkdir(parents=True, exist_ok=True)
app.mount("/captures", StaticFiles(directory=ROOT / "data" / "captures"), name="captures")
(ROOT / "web").mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
