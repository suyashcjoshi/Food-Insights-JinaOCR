"""One capture: photo -> prepared image -> EIS reader (Extract) -> parsed fields -> document.

Returns the `food_labels` document plus what the UI's raw view needs (model output and the
exact HTTP request, key redacted). Indexing is the caller's job so this stays testable offline.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from app import eis
from app.allergens import find_allergens
from app.images import JPEG_QUALITY, prepare_bytes, to_data_url
from app.naming import guess_product_name
from app.ocr import is_looped, strip_regions
from app.parse import normalize, parse

ROOT = Path(__file__).resolve().parent.parent
CAPTURES = ROOT / "data" / "captures"


class BadImage(ValueError):
    """An uploaded photo that cannot be read as an image (or has absurdly many pixels)."""


def _open(data: bytes) -> Image.Image:
    """Decode and prepare an upload; every way that can go wrong is one `BadImage`."""
    try:
        return prepare_bytes(data)
    except Image.DecompressionBombError as exc:
        raise BadImage("the image has too many pixels") from exc
    except OSError as exc:  # not an image, or truncated
        raise BadImage(str(exc)) from exc


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
    front_image_path: str | None = None,
    name_source: str | None = None,
    front_ms: int | None = None,
) -> tuple[dict, dict]:
    """Document for the index and a small dict of parse extras (looped, loop ratio)."""
    text = strip_regions(markdown)
    looped, ratio = is_looped(text)
    res = parse(text)
    nutrients = {
        **res.nutrients,
        **({"energy_kj": res.energy_kj} if res.energy_kj is not None else {}),
        **({"serving_text": res.serving_text} if res.serving_text else {}),
        **(
            {"carb_includes_fibre": res.carb_includes_fibre}
            if res.carb_includes_fibre is not None
            else {}
        ),
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
        "name_source": name_source,
        "front_image_path": front_image_path,
        "language": language,
        "nutrients": nutrients,
        "parse_flags": res.flags + (["looped"] if looped else []),
        "unverified_text": res.unverified_text,
        "allergen_mentions": find_allergens(res.unverified_text),
        "raw_markdown": markdown,
        "plain_text": plain_text(text),
        "telemetry": {**_telemetry(call), **({"front_ocr_ms": front_ms} if front_ms else {})},
    }
    return {k: v for k, v in doc.items() if v is not None}, {"looped": looped, "loop_ratio": ratio}


def _read_front(img: Image.Image, doc_id: str) -> tuple[str | None, str, int]:
    """Read the front of the pack: (name guess, saved image path, wall ms). `capture` treats any failure
    here as "no name from the front": the numbers are on the back, and the name can be typed."""
    CAPTURES.mkdir(parents=True, exist_ok=True)
    img.save(CAPTURES / f"{doc_id}_front.jpg", format="JPEG", quality=JPEG_QUALITY)
    path = f"captures/{doc_id}_front.jpg"
    call = eis.read(to_data_url(img))
    name = guess_product_name(call.text) if call.ok else None
    return name, path, call.ms


def capture(
    image_bytes: bytes,
    *,
    front_bytes: bytes | None = None,
    language: str | None = None,
    product_name: str | None = None,
    source: str = "demo",
    source_url: str | None = None,
    doc_id: str | None = None,
) -> dict:
    """Run the whole pipeline. Raises OcrError if EIS fails; everything else degrades to a flag.

    `doc_id` lets a seeding script make re-runs idempotent (`off-<barcode>`); the app uses a uuid."""
    img = _open(image_bytes)  # EXIF rotate + resize, the only preprocessing
    front_img, front_failed = None, False
    if front_bytes:  # decoded before the paid read, so a bad file costs nothing
        try:
            front_img = _open(front_bytes)
        except BadImage:
            front_failed = True
    doc_id = doc_id or uuid.uuid4().hex
    call = eis.read(to_data_url(img))
    if not call.ok:
        raise OcrError(call)
    CAPTURES.mkdir(parents=True, exist_ok=True)
    img.save(CAPTURES / f"{doc_id}.jpg", format="JPEG", quality=JPEG_QUALITY)
    front_name, front_path, front_ms = (None, None, None)
    if front_img is not None:
        try:
            front_name, front_path, front_ms = _read_front(front_img, doc_id)
        except Exception:  # noqa: BLE001  the back photo is already read and saved: keep it
            front_failed = True
    name = product_name or front_name
    doc, extras = build_doc(
        call.text,
        doc_id=doc_id,
        image_path=f"captures/{doc_id}.jpg",
        call=call,
        language=language,
        product_name=name,
        source=source,
        source_url=source_url,
        front_image_path=front_path,
        name_source=("typed" if product_name else "front") if name else None,
        front_ms=front_ms,
    )
    if front_failed:
        doc["parse_flags"] = [*doc.get("parse_flags", []), "front_failed"]
    return {
        "doc": doc,
        **extras,
        "raw": {
            "markdown": call.text,
            "response": call.body,
            "request": {"method": call.method, "path": call.path, "body": call.request},
        },
    }
