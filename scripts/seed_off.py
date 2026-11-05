"""Seed the `food_labels` index with the Open Food Facts sample.

    uv run python scripts/seed_off.py [--limit N] [--workers 3] [--prompt table] [--force] [--dry-run]
    uv run python scripts/seed_off.py --recheck-off     # fill in OFF statuses after an outage

Every image in data/off/manifest.jsonl goes through the SAME code as `/api/capture`
(`app.pipeline.capture`, then `app.es.index_doc`) with `source: off`, the OFF barcode, the OFF
language tag and product name, and the OFF product page as `source_url`. The document id is
`off-<barcode>`, so a re-run overwrites instead of duplicating; documents already in the index are
skipped (no EIS call) unless --force. Writes reports/seed_off.md.

Costs one EIS call per image (about $0.002) and one OFF product lookup (cached to disk).
Data: Open Food Facts contributors, ODbL; images CC BY-SA (see data/off/ATTRIBUTION.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import eis, es, off, pipeline

OFF = ROOT / "data" / "off"
REPORTS = ROOT / "reports"


def seed_one(entry: dict, prompt: str, force: bool) -> dict:
    """Capture + index one manifest entry. Never raises: the outcome is the return value."""
    doc_id = f"off-{entry['barcode']}"
    try:
        if not force and es.get_doc(doc_id) is not None:
            return {"barcode": entry["barcode"], "outcome": "skipped"}
        result = pipeline.capture(
            (OFF / entry["image"]).read_bytes(),
            prompt_variant=prompt,
            barcode=entry["barcode"],
            language=entry.get("lang"),
            product_name=entry.get("name"),
            source="off",
            source_url=entry.get("product_url"),
            doc_id=doc_id,
        )
        es.index_doc(result["doc"])
    except pipeline.OcrError as exc:
        return {
            "barcode": entry["barcode"],
            "outcome": "ocr_failed",
            "detail": f"EIS {exc.call.status}",
        }
    except Exception as exc:  # noqa: BLE001 - one bad image must not stop the run
        return {"barcode": entry["barcode"], "outcome": "failed", "detail": str(exc)[:160]}
    d = result["doc"]
    return {
        "barcode": entry["barcode"],
        "outcome": "indexed",
        "verified": d["nutrients_verified"],
        "looped": result["looped"],
        "off_status": d["off_match"]["status"],
        "allergens": d.get("allergen_mentions", []),
        "tokens_in": d["telemetry"].get("prompt_tokens", 0),
        "tokens_out": d["telemetry"].get("completion_tokens", 0),
        "ms": d["telemetry"].get("ocr_ms", 0),
        "cost": d["telemetry"].get("cost_est") or 0.0,
    }


def recheck_off(entries: list[dict]) -> int:
    """OFF is flaky: a document seeded while it was down keeps status `error` until rechecked here."""
    todo = fixed = 0
    for e in entries:
        doc = es.get_doc(f"off-{e['barcode']}")
        status = (doc or {}).get("off_match", {}).get("status")
        # a seeded barcode comes from OFF, so "not found" there means a busy OFF, not a missing product
        if doc is None or not (status == "error" or (status == "not_found" and doc.get("barcode"))):
            continue
        todo += 1
        n = doc.get("nutrients", {})
        match = off.cross_check(
            doc.get("barcode"), n.get("carbohydrates_g"), n.get("basis", "unknown")
        )
        if match["status"] != "error":
            es.update_doc(doc["id"], {"off_match": match})
            fixed += 1
    print(f"recheck-off: {fixed} of {todo} documents with status error / not_found updated")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--prompt", choices=sorted(eis.PROMPTS), default=eis.DEFAULT_PROMPT)
    ap.add_argument("--force", action="store_true", help="re-read and overwrite existing documents")
    ap.add_argument(
        "--dry-run", action="store_true", help="list what would be seeded, call nothing"
    )
    ap.add_argument(
        "--recheck-off",
        action="store_true",
        help="no OCR: redo the Open Food Facts cross-check of seeded documents whose status is error or not_found",
    )
    args = ap.parse_args()

    entries = [json.loads(ln) for ln in (OFF / "manifest.jsonl").read_text().splitlines() if ln]
    entries = entries[: args.limit] if args.limit else entries
    if args.dry_run:
        print(
            f"dry run: {len(entries)} images -> index {es.index_name()}, source off, prompt {args.prompt}"
        )
        return 0

    if args.recheck_off:
        return recheck_off(entries)

    created = es.ensure_index()
    t0 = time.time()
    eis.warmup()  # the first call after idle can take minutes; do not let it land on image 1
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda e: seed_one(e, args.prompt, args.force), entries))
    secs = time.time() - t0

    by = Counter(r["outcome"] for r in results)
    done = [r for r in results if r["outcome"] == "indexed"]
    off = Counter(r["off_status"] for r in done)
    allergens = Counter(f"{a['name']}:{a['kind']}" for r in done for a in r["allergens"])
    fails = [r for r in results if r["outcome"] in ("ocr_failed", "failed")]
    cost = sum(r["cost"] for r in done)
    md = [
        "# Seed: Open Food Facts sample -> food_labels",
        "",
        (
            f"Index `{es.index_name()}` ({'created' if created else 'existed'}), source `off`, prompt "
            f"`{args.prompt}`, {len(entries)} images, {secs:.0f} s, same pipeline as `/api/capture`."
        ),
        "",
        "| Outcome | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(by.items())],
        "",
        (
            f"- Verified panels: {sum(r['verified'] for r in done)} of {len(done)}; looped outputs: "
            f"{sum(r['looped'] for r in done)}"
        ),
        f"- OFF cross-check statuses: {dict(sorted(off.items()))}",
        (
            f"- Tokens in / out: {sum(r['tokens_in'] for r in done)} / {sum(r['tokens_out'] for r in done)}; "
            f"cost_est ${cost:.4f}"
        ),
        f"- Allergen mentions as read (name:kind): {dict(sorted(allergens.items()))}",
    ]
    if fails:
        md += [
            "",
            "## Failures",
            "",
            *[f"- {r['barcode']}: {r['outcome']} {r.get('detail', '')}" for r in fails],
        ]
    (REPORTS / "seed_off.md").write_text("\n".join(md) + "\n")
    print(
        f"seeded {by.get('indexed', 0)}/{len(entries)} (skipped {by.get('skipped', 0)}, failed {len(fails)}) "
        f"into {es.index_name()} in {secs:.0f}s, ${cost:.4f} -> reports/seed_off.md"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
