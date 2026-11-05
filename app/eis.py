"""Transport for the Elastic Inference Service (EIS) via the Elasticsearch `_inference` API.

Ported in reduced form from a colleague's jina-ocr-v1 demo (`eis.py`): pooled httpx client,
retry with backoff on transient errors, SSE parsing, warm-up. Used with permission; credit in README.

One function per API shape: `ocr_chat_stream`, `ocr_chat`, `ocr_document_extraction`.
Every function returns a `Call` carrying text, usage, wall time and the exact request (key redacted).
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from dataclasses import dataclass, field

import httpx
from dotenv import load_dotenv

load_dotenv()

TIMEOUT_S = 180  # cold start can take 2-3 minutes
RETRY_STATUS = {429, 502, 503, 504}
BACKOFF_S = (5, 15, 30)
# EIS rejects repetition_penalty / no_repeat_ngram_size; this cap is the only guard on runaways.
MAX_TOKENS = 2048

OFFICIAL_PROMPT = "Convert the document to markdown."
PROMPTS = {
    "official": OFFICIAL_PROMPT,
    "table": "Convert the document to markdown. Render nutrition tables as HTML tables.",
}
DEFAULT_PROMPT = "table"  # key into PROMPTS; the app and score.py use it unless told otherwise

_client: httpx.Client | None = None


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def ocr_endpoint() -> str:
    return _env("EIS_OCR_CHAT_ENDPOINT", ".jina-ocr-v1-chat_completion")


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
    text: str = ""  # model output (assembled for streaming)
    usage: dict = field(default_factory=dict)
    body: dict | None = None  # parsed JSON response when not streaming
    finish_reason: str | None = None
    raw: str = ""  # raw response text (SSE payload for streaming)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def _shorten(obj):
    """Copy of a request body with long strings (base64 images) truncated, for reports."""
    if isinstance(obj, dict):
        return {k: _shorten(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shorten(v) for v in obj]
    if isinstance(obj, str) and len(obj) > 120:
        return obj[:60] + f"...[{len(obj)} chars]"
    return obj


def request(method: str, path: str, body: dict | None = None, retries: int = 4) -> Call:
    """Send one request; retry transient statuses and transport errors with backoff.

    Returns the final response even when it is an error status, so probes can record it.
    """
    last: Call | None = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            r = client().request(method, path, json=body)
            last = Call(
                r.status_code,
                int((time.time() - t0) * 1000),
                method,
                path,
                _shorten(body),
                raw=r.text,
            )
            if r.status_code not in RETRY_STATUS:
                return last
        except httpx.ConnectError as e:
            raise RuntimeError(f"cannot reach Elasticsearch: {e}") from e
        except httpx.TransportError as e:  # read timeout, dropped connection
            last = Call(
                0,
                int((time.time() - t0) * 1000),
                method,
                path,
                _shorten(body),
                raw=f"{type(e).__name__}: {e}",
            )
        if attempt < retries - 1:
            time.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
    assert last is not None
    return last


def parse_sse(payload: str) -> tuple[str, dict, str | None]:
    """Assemble `delta.content`, the trailing `usage` block and the finish_reason."""
    out: list[str] = []
    usage: dict = {}
    finish: str | None = None
    for line in payload.splitlines():
        line = line.lstrip("﻿")
        if not line.startswith("data:"):
            continue
        chunk = line[5:].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            d = json.loads(chunk)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("error"):
            raise RuntimeError(f"EIS in-band error: {str(d['error'])[:200]}")
        if d.get("usage"):
            usage = d["usage"]
        for ch in d.get("choices", []) or []:
            out.append((ch.get("delta") or {}).get("content") or "")
            finish = ch.get("finish_reason") or finish
    return "".join(out), usage, finish


def _ocr_body(image_data_url: str, prompt: str, max_tokens: int, temperature: float) -> dict:
    return {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
    }


def ocr_chat(
    image_data_url: str,
    prompt: str = OFFICIAL_PROMPT,
    endpoint: str | None = None,
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0,
) -> Call:
    """Non-streaming chat_completion: one JSON response."""
    path = f"/_inference/chat_completion/{endpoint or ocr_endpoint()}"
    call = request("POST", path, _ocr_body(image_data_url, prompt, max_tokens, temperature))
    try:
        call.body = json.loads(call.raw)
    except ValueError:
        return call
    if call.ok:
        choice = (call.body.get("choices") or [{}])[0]
        call.text = (choice.get("message") or {}).get("content") or ""
        call.finish_reason = choice.get("finish_reason")
        call.usage = call.body.get("usage") or {}
    return call


def ocr_chat_stream(
    image_data_url: str,
    prompt: str = OFFICIAL_PROMPT,
    endpoint: str | None = None,
    max_tokens: int = MAX_TOKENS,
    temperature: float = 0,
) -> Call:
    """Streaming chat_completion (SSE), assembled into one Call."""
    path = f"/_inference/chat_completion/{endpoint or ocr_endpoint()}/_stream"
    call = request("POST", path, _ocr_body(image_data_url, prompt, max_tokens, temperature))
    if call.ok:
        call.text, call.usage, call.finish_reason = parse_sse(call.raw)
    return call


def ocr_document_extraction(
    content_type: str, data_url: str, endpoint: str | None = None, output_format: str = "markdown"
) -> Call:
    """Experimental `document_extraction` task. `content_type` is "image" or "pdf"."""
    path = (
        f"/_inference/document_extraction/{endpoint or _env('EIS_OCR_DOCX_ENDPOINT', 'label-ocr')}"
    )
    body = {
        "input": {"content": {"type": content_type, "format": "base64", "value": data_url}},
        "task_settings": {"output_format": output_format},
    }
    call = request("POST", path, body)
    try:
        call.body = json.loads(call.raw)
    except ValueError:
        return call
    if call.ok:
        items = call.body.get("document_extraction") or [{}]
        call.text = items[0].get("content") or ""
    return call


def cost_est(usage: dict) -> float | None:
    """USD from reported tokens; None (omitted) when the price env vars are blank."""
    pin, pout = _env("EIS_OCR_PRICE_PER_MTOK_IN"), _env("EIS_OCR_PRICE_PER_MTOK_OUT")
    if not pin or not pout or not usage:
        return None
    tokens_in, tokens_out = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    return (tokens_in * float(pin) + tokens_out * float(pout)) / 1e6


def warmup() -> float:
    """Send a tiny image and ignore the outcome. Returns seconds spent. Never raises."""
    import base64
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    t0 = time.time()
    with contextlib.suppress(Exception):
        ocr_chat(url, max_tokens=16)
    return time.time() - t0
