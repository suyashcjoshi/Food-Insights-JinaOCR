"""Open Food Facts cross-check by barcode.

Etiquette (AGENTS.md): a User-Agent, product JSON cached to disk, and a 503 or `status: 0` is
"no match", never an error that stops a capture. Only the carbohydrate figure is compared.
Data: Open Food Facts contributors, ODbL; images CC BY-SA.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "off" / "product_cache"  # data/off is git-ignored
URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
FIELDS = "code,product_name,lang,nutriments,image_front_url"
TOLERANCE_G = 0.5  # same tolerance as scripts/score.py
TIMEOUT_S = 10
# OFF is a volunteer service and is sometimes slow or down. After this many failures in a row,
# lookups pause for a while (status "error" at once) instead of costing a timeout per capture.
BREAKER_FAILS = 3
BREAKER_COOLDOWN_S = 120
_breaker = {"fails": 0, "open_until": 0.0}


def _record(ok: bool) -> None:
    _breaker["fails"] = 0 if ok else _breaker["fails"] + 1
    if _breaker["fails"] >= BREAKER_FAILS:
        _breaker["open_until"] = time.monotonic() + BREAKER_COOLDOWN_S
        _breaker["fails"] = 0


def user_agent() -> str:
    """OFF_USER_AGENT from .env (it may carry the contact OFF asks for); generic if unset."""
    return os.getenv("OFF_USER_AGENT") or "FoodInsights/0.1"


def valid_barcode(code: str) -> bool:
    """8/12/13/14 digits with a correct GS1 check digit."""
    if not re.fullmatch(r"\d{8}|\d{12,14}", code or ""):
        return False
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def find_barcode(text: str) -> str | None:
    """First number in the OCR text that is a valid EAN/UPC (checksum passes)."""
    for m in re.finditer(r"(?<!\d)\d(?:[\s-]?\d){7,13}(?!\d)", text or ""):
        code = re.sub(r"\D", "", m.group())
        if valid_barcode(code):
            return code
    return None


def lookup(code: str, client: httpx.Client | None = None) -> dict | None:
    """OFF product dict, or None for no match (404, `status: 0`). A 429 / 5xx or a timeout raises
    httpx.HTTPError, which `cross_check` turns into status `error`: it never reaches the caller."""
    cache = CACHE / f"{code}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if time.monotonic() < _breaker["open_until"]:
        raise httpx.ConnectError("Open Food Facts skipped: repeated failures, cooling down")
    own = client is None
    client = client or httpx.Client(
        headers={"User-Agent": user_agent()}, timeout=TIMEOUT_S, follow_redirects=True
    )
    try:
        try:
            r = client.get(URL.format(code=code), params={"fields": FIELDS})
        except httpx.HTTPError:
            _record(False)
            raise
        transient = r.status_code == 429 or r.status_code >= 500
        _record(not transient)
        if transient:
            # a busy or failing OFF says nothing about the product: surface it as status `error`
            # (retryable with `seed_off.py --recheck-off`), not as "not found"
            r.raise_for_status()
        if r.status_code != 200:
            return None  # 404 and friends: no such product
        body = r.json()
        if body.get("status") != 1:
            return None
        product = body.get("product") or {}
        CACHE.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(product, ensure_ascii=False))
        return product
    finally:
        if own:
            client.close()


def cross_check(code: str | None, carbs: float | None, basis: str) -> dict:
    """`off_match` object: match | mismatch | not_found | not_comparable | error.

    not_comparable: the panel is per serving (or carbs was not parsed), so there is nothing to
    compare with OFF's per-100 g figure.
    """
    out: dict = {"status": "not_found", "checked_at": datetime.now(UTC).isoformat()}
    if not code:
        return out
    try:
        product = lookup(code)
    except (httpx.HTTPError, ValueError) as exc:
        return {**out, "status": "error", "error": str(exc)[:200]}
    if product is None:
        return out
    off_carbs = (product.get("nutriments") or {}).get("carbohydrates_100g")
    out["url"] = f"https://world.openfoodfacts.org/product/{code}"
    out["product_name"] = product.get("product_name") or None
    out["lang"] = product.get("lang") or None
    if off_carbs is None:
        return out
    out["carbohydrates_100g"] = float(off_carbs)
    if carbs is None or not basis.startswith("100"):
        return {**out, "status": "not_comparable"}
    return {
        **out,
        "status": "match" if abs(carbs - float(off_carbs)) <= TOLERANCE_G else "mismatch",
    }
