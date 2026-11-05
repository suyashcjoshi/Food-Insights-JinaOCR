"""Image preparation: the only preprocessing we do (EXIF rotate + resize). No CV."""

from __future__ import annotations

import base64
import io
from pathlib import Path

from PIL import Image, ImageOps

MAX_EDGE = 1600


def prepare(path: str | Path, max_edge: int = MAX_EDGE) -> Image.Image:
    """Open, apply EXIF orientation (a sideways image makes the model loop), shrink long edge."""
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_edge, max_edge))
    return img


def prepare_bytes(data: bytes, max_edge: int = MAX_EDGE) -> Image.Image:
    """Same as `prepare` for an uploaded file."""
    return prepare(io.BytesIO(data), max_edge)


def to_data_url(img: Image.Image, fmt: str = "JPEG") -> str:
    buf = io.BytesIO()
    img.save(buf, format=fmt, quality=90) if fmt == "JPEG" else img.save(buf, format=fmt)
    mime = {"JPEG": "image/jpeg", "PNG": "image/png", "PDF": "application/pdf"}[fmt]
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()
