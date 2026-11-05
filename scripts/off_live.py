"""One live Open Food Facts lookup, recorded as reports/off_live.md.

    uv run python scripts/off_live.py [BARCODE] [--timeout 30]

Makes exactly ONE request, with the same URL, `fields` list and User-Agent as `app/off.py`, and
writes down what came back: status, headers that matter, top-level keys, the shape and types of the
`product` object and the fields the app reads. A failure (timeout, 5xx, `status: 0`) is recorded the
same way. The User-Agent contact from OFF_USER_AGENT is redacted in the report.
Data: Open Food Facts contributors, ODbL.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import off

DEFAULT_CODE = "021130077403"
NUTRIMENT_KEYS = (
    "energy-kcal_100g",
    "fat_100g",
    "saturated-fat_100g",
    "carbohydrates_100g",
    "sugars_100g",
    "proteins_100g",
    "salt_100g",
)


def shape(value, depth: int = 0):
    """Type skeleton of a JSON value: dicts keep their keys, lists show one element, leaves show
    the type (and a short sample for strings and numbers)."""
    if isinstance(value, dict):
        return {k: shape(v, depth + 1) for k, v in value.items()} if depth < 2 else "object"
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    if isinstance(value, str):
        return f"string ({value[:40]!r}{'…' if len(value) > 40 else ''})"
    return f"{type(value).__name__} ({value!r})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("barcode", nargs="?", default=DEFAULT_CODE)
    ap.add_argument("--timeout", type=float, default=30.0)
    args = ap.parse_args()
    code = args.barcode
    url = off.URL.format(code=code)
    ua = off.user_agent()
    ua_shown = re.sub(r"\([^)]*\)", "(<contact from OFF_USER_AGENT>)", ua)
    started = datetime.now(UTC).isoformat(timespec="seconds")

    md = [
        f"# Open Food Facts live lookup: {code}",
        "",
        f"Recorded {started} by `scripts/off_live.py`: one GET, same URL, `fields` and User-Agent as `app/off.py`.",
        "",
        "## Request",
        "",
        "```",
        f"GET {url}?fields={off.FIELDS}",
        f"User-Agent: {ua_shown}",
        "```",
        "",
        (
            f"Barcode check digit (GS1): {'valid' if off.valid_barcode(code) else 'INVALID'}. Client timeout {args.timeout:.0f} s, "
            "redirects followed, no retry."
        ),
        "",
        "## Response",
        "",
    ]
    t0 = time.time()
    outcome = "failed"
    try:
        r = httpx.get(
            url,
            params={"fields": off.FIELDS},
            headers={"User-Agent": ua},
            timeout=args.timeout,
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        ms = int((time.time() - t0) * 1000)
        md += [
            f"**No response.** `{type(exc).__name__}` after {ms} ms: {str(exc)[:200] or 'no message'}.",
            "",
            (
                'In the app this is `off_match.status = "error"` (and the circuit breaker counts it); '
                "a capture is never blocked. Re-run this script, or `scripts/seed_off.py --recheck-off`, when the service is back."
            ),
        ]
    else:
        ms = int((time.time() - t0) * 1000)
        hdrs = {
            k: r.headers.get(k)
            for k in ("content-type", "content-length", "server", "cache-control")
            if r.headers.get(k)
        }
        md += [
            f"HTTP **{r.status_code}** in {ms} ms, {len(r.content)} bytes.",
            "",
            "```",
            *[f"{k}: {v}" for k, v in hdrs.items()],
            "```",
            "",
        ]
        try:
            body = r.json()
        except ValueError:
            body = None
            md += ["Body is not JSON:", "", "```", r.text[:400], "```"]
        if isinstance(body, dict):
            product = body.get("product") or {}
            outcome = "found" if body.get("status") == 1 else "not found"
            md += [
                f"Top-level keys: `{', '.join(body)}`.",
                f"`status` = `{body.get('status')!r}`, `status_verbose` = `{body.get('status_verbose')!r}`, `code` = `{body.get('code')!r}`.",
                "",
                f"Outcome for the app: **{outcome}**"
                + ("" if outcome == "found" else " (`app/off.py` returns None, status `not_found`)")
                + ".",
                "",
            ]
            if product:
                nutr = product.get("nutriments") or {}
                md += [
                    "### `product` shape (types, short samples)",
                    "",
                    "```json",
                    json.dumps(
                        shape({k: v for k, v in product.items() if k != "nutriments"}),
                        indent=2,
                        ensure_ascii=False,
                    ),
                    "```",
                    "",
                    f"`nutriments` has {len(nutr)} keys. The ones the app can use (per 100 g):",
                    "",
                    "| key | value | type |",
                    "|---|---|---|",
                    *[
                        f"| `{k}` | {nutr[k]!r} | {type(nutr[k]).__name__} |"
                        if k in nutr
                        else f"| `{k}` | absent | - |"
                        for k in NUTRIMENT_KEYS
                    ],
                    "",
                    "### What `app/off.py` reads",
                    "",
                    f"- `product_name`: {product.get('product_name')!r}",
                    f"- `lang`: {product.get('lang')!r}",
                    f"- `nutriments.carbohydrates_100g`: {nutr.get('carbohydrates_100g')!r}"
                    + (
                        " (the only figure compared; absent means status `not_found`)"
                        if "carbohydrates_100g" not in nutr
                        else ""
                    ),
                    f"- `image_front_url`: {'present' if product.get('image_front_url') else 'absent'}",
                ]
        elif body is not None:
            md += [f"JSON is a `{type(body).__name__}`, not an object."]

    md += [
        "",
        "Data: Open Food Facts contributors, available under the Open Database License (ODbL).",
    ]
    (ROOT / "reports" / "off_live.md").write_text("\n".join(md) + "\n")
    print(f"off live {code}: {outcome} in {ms} ms -> reports/off_live.md")
    return 0 if outcome == "found" else 1


if __name__ == "__main__":
    sys.exit(main())
