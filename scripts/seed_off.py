"""Seed the `food_labels` index with the Open Food Facts sample.

    uv run python scripts/seed_off.py [--limit N] [--workers 3] [--force] [--dry-run]

Every image in data/off/manifest.jsonl goes through the SAME code as `/api/capture`
(`app.pipeline.capture`, then `app.es.index_doc`) with `source: off`, the OFF
language tag and product name, and the OFF product page as `source_url`. The document id is
`off-<barcode>`, so a re-run overwrites instead of duplicating; documents already in the index are
skipped (no EIS call) unless --force. Writes _notes/reports/seed_off.md.

Costs one EIS call per image (the reader reports no usage, so no price is shown here).
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

from app import eis, es, pipeline

OFF = ROOT / "data" / "off"
REPORTS = ROOT / "_notes" / "reports"  # git-ignored local notes
FAILED = ("ocr_failed", "failed")  # outcomes that make the run exit non-zero


def seed_one(entry: dict, force: bool) -> dict:
    """Capture + index one manifest entry. Never raises: the outcome is the return value."""
    doc_id = f"off-{entry['barcode']}"
    try:
        if not force and es.get_doc(doc_id) is not None:
            return {"barcode": entry["barcode"], "outcome": "skipped"}
        result = pipeline.capture(
            (OFF / entry["image"]).read_bytes(),
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
        "looped": result["looped"],
        "allergens": d.get("allergen_mentions", []),
        "ms": d["telemetry"].get("ocr_ms", 0),
    }


def load_entries(limit: int | None) -> list[dict]:
    lines = (OFF / "manifest.jsonl").read_text().splitlines()
    entries = [json.loads(ln) for ln in lines if ln]
    return entries[:limit] if limit else entries


def render_report(results: list[dict], *, created: bool, n_images: int, secs: float) -> str:
    by = Counter(r["outcome"] for r in results)
    done = [r for r in results if r["outcome"] == "indexed"]
    allergens = Counter(f"{a['name']}:{a['kind']}" for r in done for a in r["allergens"])
    fails = [r for r in results if r["outcome"] in FAILED]
    md = [
        "# Seed: Open Food Facts sample -> food_labels",
        "",
        (
            f"Index `{es.index_name()}` ({'created' if created else 'existed'}), source `off`, "
            f"{n_images} images, {secs:.0f} s, same pipeline as `/api/capture`."
        ),
        "",
        "| Outcome | Count |",
        "|---|---|",
        *[f"| {k} | {v} |" for k, v in sorted(by.items())],
        "",
        f"- Looped outputs: {sum(r['looped'] for r in done)}",
        f"- Allergen mentions as read (name:kind): {dict(sorted(allergens.items()))}",
    ]
    if fails:
        md += ["", "## Failures", ""]
        md += [f"- {r['barcode']}: {r['outcome']} {r.get('detail', '')}" for r in fails]
    return "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--force", action="store_true", help="re-read and overwrite existing documents")
    ap.add_argument(
        "--dry-run", action="store_true", help="list what would be seeded, call nothing"
    )
    args = ap.parse_args()

    entries = load_entries(args.limit)
    if args.dry_run:
        print(f"dry run: {len(entries)} images -> index {es.index_name()}, source off")
        return 0

    created = es.ensure_index()
    started = time.time()
    eis.warmup()  # the first call after idle can take minutes; do not let it land on image 1
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda e: seed_one(e, args.force), entries))
    secs = time.time() - started

    REPORTS.mkdir(parents=True, exist_ok=True)
    report = render_report(results, created=created, n_images=len(entries), secs=secs)
    (REPORTS / "seed_off.md").write_text(report)
    by = Counter(r["outcome"] for r in results)
    failed = sum(by[o] for o in FAILED)
    print(
        f"seeded {by.get('indexed', 0)}/{len(entries)} (skipped {by.get('skipped', 0)}, failed {failed}) "
        f"into {es.index_name()} in {secs:.0f}s -> _notes/reports/seed_off.md"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
