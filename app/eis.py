"""Transport for the Elastic Inference Service (EIS) via the Elasticsearch `_inference` API.

Ported in reduced form from a colleague's jina-ocr-v1 demo (`eis.py`): pooled httpx client,
retry with backoff on transient errors, warm-up. Used with permission; credit in README.

The one call this app makes is `document_extraction` on `.jina-reader`: image in, Markdown out.
`ocr_document_extraction` returns a `Call` carrying text, wall time and the exact request (key redacted).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass

import httpx
from dotenv import load_dotenv
from PIL import Image

from app.images import to_data_url

load_dotenv()

TIMEOUT_S = 180  # cold start can take 2-3 minutes
RETRY_STATUS = {429, 502, 503, 504}
BACKOFF_S = (5, 15, 30)  # seconds to wait before retry 1, 2, 3+
DEADLINE_S = (
    400  # stop retrying when another attempt could run past this (4 timeouts = ~13 minutes)
)
SHORTEN_ABOVE = 120  # request strings longer than this (base64 images) are cut in reports
SHORTEN_TO = 60

_client: httpx.Client | None = None


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def reader_endpoint() -> str:
    return _env("EIS_OCR_DOCX_ENDPOINT", ".jina-reader")


def client() -> httpx.Client:
    """One pooled client per process (avoids a TLS handshake per call)."""
    global _client
    if _client is None:
        url, key = _env("ES_URL").rstrip("/"), _env("ES_API_KEY")
        if not url or not key:
            raise RuntimeError("ES_URL and ES_API_KEY must be set in .env")
        _client = httpx.Client(
            base_url=url,
            headers={"Authorization": f"ApiKey {key}", "Content-Type": "application/json"},
            timeout=TIMEOUT_S,
        )
    return _client


@dataclass
class Call:
    """Result of one HTTP call to `_inference/*`."""

    status: int
    ms: int
    method: str
    path: str
    request: dict | None  # body as sent, with base64 payloads shortened
    text: str = ""  # the extracted Markdown
    body: dict | None = None  # the parsed JSON response
    raw: str = ""  # the response text as received
    attempts: int = 1  # how many tries it took; `ms` is the wall time of all of them

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def _shorten(obj):
    """Copy of a request body with long strings (base64 images) truncated, for reports."""
    if isinstance(obj, dict):
        return {k: _shorten(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shorten(v) for v in obj]
    if isinstance(obj, str) and len(obj) > SHORTEN_ABOVE:
        return obj[:SHORTEN_TO] + f"...[{len(obj)} chars]"
    return obj


def _record(
    started: float, method: str, path: str, body: dict | None, status: int, raw: str, attempts: int
) -> Call:
    """A `Call` for a response (or, with status 0, a transport failure). `started` is a
    `time.monotonic()` reading taken before the first attempt, so `ms` is what the caller waited."""
    ms = int((time.monotonic() - started) * 1000)
    return Call(status, ms, method, path, _shorten(body), raw=raw, attempts=attempts)


def request(method: str, path: str, body: dict | None = None, retries: int = 4) -> Call:
    """Send one request; retry transient statuses and transport errors with backoff.

    Returns the final response even when it is an error status, so probes can record it.
    """
    last: Call | None = None
    started = time.monotonic()
    for attempt in range(retries):
        n = attempt + 1
        try:
            r = client().request(method, path, json=body)
            last = _record(started, method, path, body, r.status_code, r.text, n)
            if r.status_code not in RETRY_STATUS:
                return last
        except httpx.ConnectError as e:
            raise RuntimeError(f"cannot reach Elasticsearch: {e}") from e
        except httpx.TransportError as e:  # read timeout, dropped connection
            last = _record(started, method, path, body, 0, f"{type(e).__name__}: {e}", n)
        if attempt < retries - 1:
            wait = BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)]
            if time.monotonic() - started + wait + TIMEOUT_S > DEADLINE_S:
                break  # another full attempt could run past the deadline: return what we have
            time.sleep(wait)
    assert last is not None
    return last


def ocr_document_extraction(
    content_type: str,
    data_url: str,
    endpoint: str | None = None,
    parameters: dict | None = None,
) -> Call:
    """`document_extraction` task (Serverless preview). `content_type`: "image" or "pdf".

    `parameters` go to `task_settings.parameters` (e.g. {"preset": "ocr"}). The extracted Markdown
    ends up in `Call.text`; unknown response fields are ignored.
    """
    path = f"/_inference/document_extraction/{endpoint or reader_endpoint()}"
    body: dict = {
        "input": [{"content": {"type": content_type, "format": "base64", "value": data_url}}]
    }
    if parameters:
        body["task_settings"] = {"parameters": parameters}
    call = request("POST", path, body)
    try:
        call.body = json.loads(call.raw)
    except ValueError:
        return call
    if call.ok:
        items = call.body.get("document_extraction") or [{}]
        call.text = items[0].get("content") or ""
    return call


READ_PARAMETERS = {
    "preset": "ocr"
}  # sent explicitly: the docs name it, and a changed default cannot move us


def read(image_data_url: str) -> Call:
    """Read one image into Markdown (the Extract step)."""
    return ocr_document_extraction("image", image_data_url, parameters=READ_PARAMETERS)


def warmup() -> float:
    """Send a tiny image and ignore the outcome. Returns seconds spent. Never raises."""
    url = to_data_url(Image.new("RGB", (32, 32), "white"), "PNG")
    started = time.monotonic()
    with contextlib.suppress(Exception):
        read(url)
    return time.monotonic() - started
