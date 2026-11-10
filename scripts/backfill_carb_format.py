"""Set `nutrients.carb_includes_fibre` on labels saved before that flag existed.

    uv run python scripts/backfill_carb_format.py            # report what would change
    uv run python scripts/backfill_carb_format.py --apply    # write it

Re-parses each stored label's own `raw_markdown` (no model call, no cost) and sets ONLY that one boolean
inside `nutrients`. Existing numbers, edits and everything else are left alone. Writes a one-line summary
and a report under _notes/reports/.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import es
from app.ocr import strip_regions
from app.parse import parse

REPORTS = ROOT / "_notes" / "reports"
PAGE = 500


def stored_labels() -> list[dict]:
    body = es.client().search(
        index=es.index_name(),
        query={"match_all": {}},
        size=PAGE,
        source_includes=["id", "raw_markdown", "nutrients.carb_includes_fibre"],
    )
    return [hit["_source"] for hit in body["hits"]["hits"]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the flag (default: only report)")
    args = ap.parse_args()

    seen: Counter[str] = Counter()
    changed = 0
    for label in stored_labels():
        flag = parse(strip_regions(label.get("raw_markdown", ""))).carb_includes_fibre
        seen[{True: "US-style", False: "EU / UK", None: "unknown"}[flag]] += 1
        current = (label.get("nutrients") or {}).get("carb_includes_fibre")
        if flag is None or flag == current:
            continue
        changed += 1
        if args.apply:
            es.update_doc(label["id"], {"nutrients": {"carb_includes_fibre": flag}})

    summary = (
        f"{sum(seen.values())} labels: {dict(seen)}; "
        f"{changed} {'updated' if args.apply else 'would be updated (use --apply)'} in {es.index_name()}"
    )
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "backfill_carb_format.md").write_text(
        f"# Carbohydrate format backfill\n\n{summary}\n"
    )
    print(summary + " -> _notes/reports/backfill_carb_format.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
