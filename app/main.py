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
from pydantic import BaseModel

from app import eis, es, pipeline
from app.allergens import NAMES

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 15 * 1024 * 1024
MAX_NAME_CHARS = 200
OCR_ERROR_DETAIL_CHARS = 400  # how much of the service's error body goes back to the page
ERROR_DETAIL_CHARS = 200

app = FastAPI(title="Food Insights", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _check_kind(kind: str | None) -> None:
    if kind and kind not in es.KINDS:
        raise HTTPException(400, f"allergen_kind must be one of {list(es.KINDS)}")


def _clean(value: str | None) -> str | None:
    """Trimmed text, or None when empty (a blank form field means "not given")."""
    return (value or "").strip() or None


def _ocr_failed(call: eis.Call) -> JSONResponse:
    return JSONResponse(
        {
            "error": "ocr_failed",
            "status": call.status,
            "detail": call.raw[:OCR_ERROR_DETAIL_CHARS],
            "request": call.request,
        },
        status_code=502,
    )


async def _save(doc: dict) -> dict:
    """Index the document; a failure is reported to the page, not raised: the read still worked."""
    try:
        await asyncio.to_thread(es.index_doc, doc)
        return {"ok": True, "index": es.index_name()}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:300]}


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "index": es.index_name(),
        "endpoint": eis.reader_endpoint(),
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
    language: Annotated[str | None, Form()] = None,
    product_name: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "demo",
    index: Annotated[bool, Form()] = True,
) -> JSONResponse:
    data = await image.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(400, "send one image up to 15 MB")
    try:
        result = await asyncio.to_thread(
            pipeline.capture,
            data,
            language=_clean(language),
            product_name=_clean(product_name),
            source=source,
        )
    except OSError as exc:  # Pillow could not open the file
        raise HTTPException(400, f"not an image: {exc}") from exc
    except pipeline.OcrError as exc:
        return _ocr_failed(exc.call)
    result["indexed"] = await _save(result["doc"]) if index else {"ok": False, "skipped": True}
    result["image_url"] = "/" + result["doc"]["image_path"]
    return JSONResponse(result)


@app.get("/api/search")
async def search(
    q: str = "",
    allergen: Annotated[list[str] | None, Query()] = None,
    language: str | None = None,
    size: int = Query(24, ge=1, le=100),
    allergen_kind: str | None = None,
) -> dict:
    _check_kind(allergen_kind)
    try:
        return await asyncio.to_thread(
            es.search, q, allergen or [], language or None, size, allergen_kind
        )
    except Exception as exc:
        raise HTTPException(503, f"search unavailable: {str(exc)[:ERROR_DETAIL_CHARS]}") from exc


@app.get("/api/aggs")
async def aggs(
    q: str = "",
    allergen: Annotated[list[str] | None, Query()] = None,
    language: str | None = None,
    allergen_kind: str | None = None,
) -> dict:
    _check_kind(allergen_kind)
    try:
        return await asyncio.to_thread(
            es.aggregate, q, allergen or [], language or None, allergen_kind
        )
    except Exception as exc:
        raise HTTPException(
            503, f"aggregation unavailable: {str(exc)[:ERROR_DETAIL_CHARS]}"
        ) from exc


@app.get("/api/doc/{doc_id}")
async def doc(doc_id: str) -> dict:
    found = await asyncio.to_thread(es.get_doc, doc_id)
    if found is None:
        raise HTTPException(404, "no such capture")
    return found


def _is_language_code(lang: str) -> bool:
    return 2 <= len(lang) <= 3 and lang.isalpha()


class DocPatch(BaseModel):
    """Fields a person may correct on a capture. Only the ones sent are changed; empty clears."""

    product_name: str | None = None
    language: str | None = None


def _edits(patch: DocPatch) -> dict:
    """The fields the person sent, cleaned; an empty value clears the field."""
    sent = patch.model_fields_set
    updates: dict = {}
    if "product_name" in sent:
        updates["product_name"] = (patch.product_name or "").strip()[:MAX_NAME_CHARS] or None
    if "language" in sent:
        lang = (patch.language or "").strip().lower()
        if lang and not _is_language_code(lang):
            raise HTTPException(400, "language must be a two or three letter code, like en or fr")
        updates["language"] = lang or None
    return updates


@app.patch("/api/doc/{doc_id}")
async def patch_doc(doc_id: str, patch: DocPatch) -> dict:
    """Edit name or language."""
    updates = _edits(patch)
    found = await asyncio.to_thread(es.get_doc, doc_id)
    if found is None:
        raise HTTPException(404, "no such capture")
    if updates:
        await asyncio.to_thread(es.update_doc, doc_id, updates)
    return {k: updates.get(k, found.get(k)) for k in ("product_name", "language")}


(ROOT / "data" / "captures").mkdir(parents=True, exist_ok=True)
app.mount("/captures", StaticFiles(directory=ROOT / "data" / "captures"), name="captures")
(ROOT / "web").mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
