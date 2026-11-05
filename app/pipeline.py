"""One capture: photo -> prepared image -> jina-ocr-v1 -> parsed fields -> OFF check -> document.

Returns the `food_labels` document plus what the UI's raw view needs (model output, prompt and the
exact HTTP request, key redacted). Indexing is the caller's job so this stays testable offline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from app import eis, off
from app.allergens import find_allergens
from app.images import prepare_bytes, to_data_url
from app.ocr import is_looped, strip_regions
from app.parse import normalize, parse

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "data" / "captures"


class OcrError(RuntimeError):
    """The EIS call failed; `call` carries status, body excerpt and the request."""

    def __init__(self, call: eis.Call):
        super().__init__(f"EIS returned {call.status}")
        self.call = call


def plain_text(markdown: str) -> str:
    """Tables flattened to one line per row, markup removed (what BM25 indexes)."""
    return "\n".join(normalize(markdown))


def build_doc(
    markdown: str,
    *,
    doc_id: str,
    image_path: str,
    call: eis.Call,
    prompt_variant: str,
    barcode: str | None = None,
    language: str | None = None,
    product_name: str | None = None,
    source: str = "demo",
    source_url: str | None = None,
    do_off: bool = True,
) -> tuple[dict, dict]:
    """Document for the index and a small dict of parse extras (looped, loop ratio)."""
    text = strip_regions(markdown)
    looped, ratio = is_looped(text)
    res = parse(text)
    code = barcode if barcode and off.valid_barcode(barcode) else off.find_barcode(text)
    match = (
        off.cross_check(code, res.nutrients.get("carbohydrates_g"), res.basis)
        if do_off
        else {
            "status": "not_found",
            "checked_at": datetime.now(UTC).isoformat(),
        }
    )
    nutrients = {
        **res.nutrients,
        **({"energy_kj": res.energy_kj} if res.energy_kj is not None else {}),
        **({"serving_text": res.serving_text} if res.serving_text else {}),
        "per": res.per,
        "basis": res.basis,
    }
    telemetry = {
        "endpoint": eis.ocr_endpoint(),
        "prompt_variant": prompt_variant,
        "prompt_tokens": call.usage.get("prompt_tokens"),
        "completion_tokens": call.usage.get("completion_tokens"),
        "ocr_ms": call.ms,
        "cost_est": eis.cost_est(call.usage),
    }
    doc = {
        "id": doc_id,
        "captured_at": datetime.now(UTC).isoformat(),
        "source": source,
        "image_path": image_path,
        "source_url": source_url,
        "barcode": code,
        "product_name": product_name or match.get("product_name"),
        "language": language or match.get("lang"),
        "nutrients": nutrients,
        "nutrients_verified": res.verified and not looped,
        "parse_flags": res.flags + (["looped"] if looped else []),
        "off_match": match,
        "unverified_text": res.unverified_text,
        "allergen_mentions": find_allergens(res.unverified_text),
        "raw_markdown": markdown,
        "plain_text": plain_text(text),
        "telemetry": {k: v for k, v in telemetry.items() if v is not None},
    }
    return {k: v for k, v in doc.items() if v is not None}, {"looped": looped, "loop_ratio": ratio}


def capture(
    image_bytes: bytes,
    *,
    prompt_variant: str = eis.DEFAULT_PROMPT,
    barcode: str | None = None,
    language: str | None = None,
    product_name: str | None = None,
    source: str = "demo",
    source_url: str | None = None,
    doc_id: str | None = None,
) -> dict:
    """Run the whole pipeline. Raises OcrError if EIS fails; everything else degrades to a flag.

    `doc_id` lets a seeding script make re-runs idempotent (`off-<barcode>`); the app uses a uuid."""
    img = prepare_bytes(image_bytes)  # EXIF rotate + resize, the only preprocessing
    doc_id = doc_id or uuid.uuid4().hex
    prompt = eis.PROMPTS[prompt_variant]
    call = eis.ocr_chat(to_data_url(img), prompt=prompt)
    if not call.ok:
        raise OcrError(call)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    img.save(CAPTURES / f"{doc_id}.jpg", format="JPEG", quality=90)
    doc, extras = build_doc(
        call.text,
        doc_id=doc_id,
        image_path=f"captures/{doc_id}.jpg",
        call=call,
        prompt_variant=prompt_variant,
        barcode=barcode,
        language=language,
        product_name=product_name,
        source=source,
        source_url=source_url,
    )
    return {
        "doc": doc,
        **extras,
        "raw": {
            "markdown": call.text,
            "prompt": prompt,
            "prompt_variant": prompt_variant,
            "finish_reason": call.finish_reason,
            "request": {"method": call.method, "path": call.path, "body": call.request},
        },
    }
