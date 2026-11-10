"""FastAPI app: /api/capture, /api/search, /api/aggs, plus the static frontend in web/.

    uv run uvicorn app.main:app --reload     (or: make serve)

Reads labels and adds up what you ate; never advises: no endpoint suggests what to eat or computes a dose.
Limits are the person's own and live in the browser.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import diary, eis, es, pipeline
from app.allergens import NAMES

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD = 15 * 1024 * 1024
MAX_NAME_CHARS = 200
OCR_ERROR_DETAIL_CHARS = 400  # how much of the service's error body goes back to the page
ERROR_DETAIL_CHARS = 200
WARMUP_GAP_S = 300  # each warmup is a paid model call: at most one per five minutes
_last_warmup: float | None = None

app = FastAPI(title="Food Insights", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _check_kind(kind: str | None) -> None:
    if kind and kind not in es.KINDS:
        raise HTTPException(400, f"allergen_kind must be one of {list(es.KINDS)}")


def _clean(value: str | None) -> str | None:
    """Trimmed text, or None when empty (a blank form field means "not given")."""
    return (value or "").strip() or None


async def _es(fn, *args, what: str):
    """Run a blocking Elasticsearch call; any failure becomes a 503, like search and today do."""
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception as exc:
        raise HTTPException(503, f"{what} unavailable: {str(exc)[:ERROR_DETAIL_CHARS]}") from exc


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
    """First call after idle can take 2-3 minutes; the UI fires this on load and ignores the result.
    Every page load asks, so repeats within `WARMUP_GAP_S` are skipped (no model call)."""
    global _last_warmup
    now = time.monotonic()
    if _last_warmup is not None and now - _last_warmup < WARMUP_GAP_S:
        return {"seconds": 0.0, "skipped": True}
    _last_warmup = now  # set before the slow call, so several tabs opening at once warm up once
    seconds = await asyncio.to_thread(eis.warmup)
    return {"seconds": round(seconds, 1)}


@app.post("/api/capture")
async def capture(
    image: Annotated[UploadFile, File()],
    front: Annotated[UploadFile | None, File()] = None,
    language: Annotated[str | None, Form()] = None,
    product_name: Annotated[str | None, Form()] = None,
    source: Annotated[str, Form()] = "demo",
    index: Annotated[bool, Form()] = True,
) -> JSONResponse:
    data = await image.read()
    if not data or len(data) > MAX_UPLOAD:
        raise HTTPException(400, "send one image up to 15 MB")
    front_data = await front.read() if front else None
    if front_data is not None and (not front_data or len(front_data) > MAX_UPLOAD):
        raise HTTPException(400, "the front photo must be one image up to 15 MB")
    try:
        result = await asyncio.to_thread(
            pipeline.capture,
            data,
            front_bytes=front_data,
            language=_clean(language),
            product_name=_clean(product_name),
            source=source,
        )
    except pipeline.BadImage as exc:  # not an image, truncated, or far too many pixels
        raise HTTPException(400, f"not an image: {exc}") from exc
    except pipeline.OcrError as exc:  # EIS answered with an error status
        return _ocr_failed(exc.call)
    except RuntimeError as exc:  # EIS could not be reached at all
        raise HTTPException(
            502, f"cannot reach the model: {str(exc)[:ERROR_DETAIL_CHARS]}"
        ) from exc
    except OSError as exc:  # the photo was fine but could not be saved
        raise HTTPException(
            500, f"could not save the photo: {str(exc)[:ERROR_DETAIL_CHARS]}"
        ) from exc
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
    mode: Annotated[str, Query(pattern="^(words|meaning)$")] = "words",
) -> dict:
    _check_kind(allergen_kind)
    try:
        return await asyncio.to_thread(
            es.search, q, allergen or [], language or None, size, allergen_kind, mode
        )
    except Exception as exc:
        raise HTTPException(503, f"search unavailable: {str(exc)[:ERROR_DETAIL_CHARS]}") from exc


@app.get("/api/aggs")
async def aggs(
    q: str = "",
    allergen: Annotated[list[str] | None, Query()] = None,
    language: str | None = None,
    allergen_kind: str | None = None,
    mode: Annotated[str, Query(pattern="^(words|meaning)$")] = "words",
) -> dict:
    _check_kind(allergen_kind)
    try:
        return await asyncio.to_thread(
            es.aggregate, q, allergen or [], language or None, allergen_kind, mode
        )
    except Exception as exc:
        raise HTTPException(
            503, f"aggregation unavailable: {str(exc)[:ERROR_DETAIL_CHARS]}"
        ) from exc


@app.get("/api/doc/{doc_id}")
async def doc(doc_id: str) -> dict:
    found = await _es(es.get_doc, doc_id, what="library")
    if found is None:
        raise HTTPException(404, "no such capture")
    return found


def _is_language_code(lang: str) -> bool:
    return 2 <= len(lang) <= 3 and lang.isalpha()


# The numbers a person may correct by hand (the ones the totals and the big figures depend on).
EDITABLE_NUTRIENTS = ("carbohydrates_g", "fiber_g", "energy_kcal")
MAX_NUTRIENT_VALUE = 10_000


class DocPatch(BaseModel):
    """Fields a person may correct on a capture. Only the ones sent are changed; empty clears."""

    product_name: str | None = None
    language: str | None = None
    nutrients: dict[str, float] | None = None


def _nutrient_edits(sent: dict[str, float], current: dict) -> tuple[dict, list[str]]:
    """(the nutrients object with the edits applied, the keys that were edited)."""
    unknown = sorted(set(sent) - set(EDITABLE_NUTRIENTS))
    if unknown:
        raise HTTPException(400, f"only {list(EDITABLE_NUTRIENTS)} can be edited, not {unknown}")
    if any(not 0 <= value <= MAX_NUTRIENT_VALUE for value in sent.values()):
        raise HTTPException(400, f"numbers must be between 0 and {MAX_NUTRIENT_VALUE}")
    return {**current, **sent}, sorted(sent)


def _edits(patch: DocPatch) -> dict:
    """The name / language the person sent, cleaned; an empty value clears the field."""
    sent = patch.model_fields_set
    updates: dict = {}
    if "product_name" in sent:
        updates["product_name"] = (patch.product_name or "").strip()[:MAX_NAME_CHARS] or None
        updates["name_source"] = "typed"
    if "language" in sent:
        lang = (patch.language or "").strip().lower()
        if lang and not _is_language_code(lang):
            raise HTTPException(400, "language must be a two or three letter code, like en or fr")
        updates["language"] = lang or None
    return updates


@app.patch("/api/doc/{doc_id}")
async def patch_doc(doc_id: str, patch: DocPatch) -> dict:
    """Edit name, language, or the carbohydrate / fibre / calorie numbers (marked as edited by hand)."""
    updates = _edits(patch)
    found = await _es(es.get_doc, doc_id, what="library")
    if found is None:
        raise HTTPException(404, "no such capture")
    if patch.nutrients:
        nutrients, edited = _nutrient_edits(patch.nutrients, found.get("nutrients", {}))
        updates["nutrients"] = nutrients
        updates["edited_fields"] = sorted({*found.get("edited_fields", []), *edited})
    if updates:
        await _es(es.update_doc, doc_id, updates, what="library")
    merged = {**found, **updates}
    return {k: merged.get(k) for k in ("product_name", "language", "nutrients", "edited_fields")}


# --- the daily log -------------------------------------------------------------------------------


class LogIn(BaseModel):
    label_id: str
    portions: float = 1.0
    day: str  # the person's local date, from the page


def _check_day(day: str) -> None:
    if not diary.is_valid_day(day):
        raise HTTPException(400, "day must be a date like 2026-11-06")


@app.post("/api/log")
async def add_to_today(entry_in: LogIn) -> dict:
    """Add a read label to a day's log: its numbers (as stored, edits included) times the portions."""
    _check_day(entry_in.day)
    if not diary.MIN_PORTIONS <= entry_in.portions <= diary.MAX_PORTIONS:
        raise HTTPException(
            400, f"portions must be between {diary.MIN_PORTIONS} and {diary.MAX_PORTIONS}"
        )
    label = await _es(es.get_doc, entry_in.label_id, what="library")
    if label is None:
        raise HTTPException(404, "no such label")
    entry = diary.entry_from_label(label, entry_in.portions, entry_in.day)
    await _es(es.log_entry, entry, what="log")
    return entry


@app.get("/api/today")
async def today(day: str) -> dict:
    _check_day(day)
    try:
        return await asyncio.to_thread(es.day_summary, day)
    except Exception as exc:
        raise HTTPException(503, f"log unavailable: {str(exc)[:ERROR_DETAIL_CHARS]}") from exc


@app.delete("/api/log/{entry_id}")
async def remove_entry(entry_id: str) -> dict:
    if not await _es(es.delete_log_entry, entry_id, what="log"):
        raise HTTPException(404, "no such entry")
    return {"removed": entry_id}


(ROOT / "data" / "captures").mkdir(parents=True, exist_ok=True)
app.mount("/captures", StaticFiles(directory=ROOT / "data" / "captures"), name="captures")
(ROOT / "web").mkdir(exist_ok=True)
app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
