"""One capture: photo -> prepared image -> EIS reader (Extract) -> parsed fields -> document.

Returns the `food_labels` document plus what the UI's raw view needs (model output and the
exact HTTP request, key redacted). Indexing is the caller's job so this stays testable offline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from app import eis
from app.allergens import find_allergens
from app.images import JPEG_QUALITY, prepare_bytes, to_data_url
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


def _telemetry(call: eis.Call) -> dict:
    """What we record about the call: the endpoint, the task type and wall time.

    The path is `/_inference/<task>/<endpoint>`. There is no token usage: the reader returns none."""
    parts = call.path.strip("/").split("/")
    telemetry = {
        "endpoint": parts[-1],
        "task": parts[1] if len(parts) >= 3 else None,
        "ocr_ms": call.ms,
    }
    return {k: v for k, v in telemetry.items() if v is not None}


def build_doc(
    markdown: str,
    *,
    doc_id: str,
    image_path: str,
    call: eis.Call,
    language: str | None = None,
    product_name: str | None = None,
    source: str = "demo",
    source_url: str | None = None,
) -> tuple[dict, dict]:
    """Document for the index and a small dict of parse extras (looped, loop ratio)."""
    text = strip_regions(markdown)
    looped, ratio = is_looped(text)
    res = parse(text)
    nutrients = {
        **res.nutrients,
        **({"energy_kj": res.energy_kj} if res.energy_kj is not None else {}),
        **({"serving_text": res.serving_text} if res.serving_text else {}),
        "per": res.per,
        "basis": res.basis,
    }
    doc = {
        "id": doc_id,
        "captured_at": datetime.now(UTC).isoformat(),
        "source": source,
        "image_path": image_path,
        "source_url": source_url,
        "product_name": product_name,
        "language": language,
        "nutrients": nutrients,
        "parse_flags": res.flags + (["looped"] if looped else []),
        "unverified_text": res.unverified_text,
        "allergen_mentions": find_allergens(res.unverified_text),
        "raw_markdown": markdown,
        "plain_text": plain_text(text),
        "telemetry": _telemetry(call),
    }
    return {k: v for k, v in doc.items() if v is not None}, {"looped": looped, "loop_ratio": ratio}


def capture(
    image_bytes: bytes,
    *,
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
    call = eis.read(to_data_url(img))
    if not call.ok:
        raise OcrError(call)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    img.save(CAPTURES / f"{doc_id}.jpg", format="JPEG", quality=JPEG_QUALITY)
    doc, extras = build_doc(
        call.text,
        doc_id=doc_id,
        image_path=f"captures/{doc_id}.jpg",
        call=call,
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
            "response": call.body,
            "request": {"method": call.method, "path": call.path, "body": call.request},
        },
    }
