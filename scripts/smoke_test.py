"""Smoke test on real photos.

    uv run python scripts/smoke_test.py                       # data/kitchen
    uv run python scripts/smoke_test.py --dir data/scratch    # exploratory, no pass/fail

For each image: EXIF transpose, resize <=1600 px, read with the EIS document_extraction reader,
parse, then compare against `panel.nutrients` in `<stem>.truth.json`. Only the panel is scored.
PASS if >= 4 of 5 bucket photos parse carbohydrates correctly; occluded / sideways / two_products
are recorded as prose, not scored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import eis
from app.images import prepare, to_data_url
from app.ocr import is_looped, strip_regions
from app.parse import parse

REPORTS = ROOT / "_notes" / "reports"  # git-ignored local notes
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
EDGE_CASES = {"occluded", "sideways", "two_products"}
TOLERANCE = {"energy_kcal": 5}  # everything else +-0.5
DEFAULT_TOLERANCE = 0.5
MIN_BUCKET_PHOTOS = 5  # below this there is no verdict
PASS_AT = 4  # carbohydrates correct on at least this many bucket photos


def compare(parsed: dict, truth: dict) -> dict:
    """Score parsed nutrients against panel.nutrients only (nothing under `secondary`)."""
    detail = {}
    for key, want in truth.items():
        got = parsed.get(key)
        tol = TOLERANCE.get(key, DEFAULT_TOLERANCE)
        detail[key] = {"want": want, "got": got, "ok": got is not None and abs(got - want) <= tol}
    return {
        "correct": sum(d["ok"] for d in detail.values()),
        "total": len(detail),
        "detail": detail,
    }


def load_truth(image: Path) -> dict | None:
    """The photo's ground-truth nutrients (`<stem>.truth.json`), if it has one."""
    truth_file = image.with_suffix(".truth.json")
    return json.loads(truth_file.read_text())["panel"]["nutrients"] if truth_file.exists() else None


def read_photo(image: Path) -> dict:
    """Read one photo and score it against its truth file (if any)."""
    truth = load_truth(image)
    call = eis.read(to_data_url(prepare(image)))
    md = strip_regions(call.text)
    looped, ratio = is_looped(md)
    res = parse(md)
    row = {
        "image": image.name,
        "edge_case": image.stem in EDGE_CASES,
        "status": call.status,
        "ms": call.ms,
        "looped": looped,
        "distinct_5gram": ratio,
        "edge_cutoff_suspected": res.edge_cutoff_suspected,
        "panel_found": res.panel_found,
        "verified": res.verified and not looped,  # a runaway output is never verified
        "parsed": res.nutrients,
        "carbs_parsed": res.nutrients.get("carbohydrates_g"),
        "carbs_pack": truth.get("carbohydrates_g") if truth else None,
        "markdown": md,
    }
    if truth:
        row["score"] = compare(res.nutrients, truth)
        row["carbs_ok"] = row["score"]["detail"].get("carbohydrates_g", {}).get("ok", False)
    return row


def print_row(row: dict) -> None:
    score = row.get("score")
    carbs = (
        f"carbs {row['carbs_parsed']} vs {row['carbs_pack']}"
        if score
        else f"carbs {row['carbs_parsed']} (no truth)"
    )
    panel = f" panel {score['correct']}/{score['total']}" if score else ""
    print(
        f"{row['image']:22} {carbs:28}{panel} {row['ms']} ms"
        f"{' LOOPED' if row['looped'] else ''}{' CUTOFF?' if row['edge_cutoff_suspected'] else ''}"
    )


def verdict(bucket: list[dict]) -> str | None:
    """PASS / FAIL on the non-edge-case photos with truth; None when there are too few."""
    if len(bucket) < MIN_BUCKET_PHOTOS:
        return None
    return "PASS" if sum(r["carbs_ok"] for r in bucket) >= PASS_AT else "FAIL"


def render_report(
    folder: Path, rows: list[dict], bucket: list[dict], carbs_ok: int, result: str | None
) -> str:
    md = [
        f"# Smoke test ({folder.name})",
        "",
        f"Bucket photos with truth: {len(bucket)}; carbs correct: {carbs_ok}; verdict: {result or 'n/a (needs 5 bucket photos with truth)'}",
        "",
        "| Image | carbs parsed | carbs pack | panel | ms | flags |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        score = r.get("score")
        panel = f"{score['correct']}/{score['total']}" if score else "-"
        flags = ", ".join(
            name
            for name, on in (
                ("looped", r["looped"]),
                ("cutoff?", r["edge_cutoff_suspected"]),
                ("edge case", r["edge_case"]),
            )
            if on
        )
        md.append(
            f"| {r['image']} | {r['carbs_parsed']} | {r['carbs_pack']} | {panel} | {r['ms']} | {flags} |"
        )
    return "\n".join(md) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "kitchen"))
    folder = Path(ap.parse_args().dir)
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        sys.exit(f"no images in {folder}")

    rows = []
    for image in images:
        rows.append(read_photo(image))
        print_row(rows[-1])

    bucket = [r for r in rows if not r["edge_case"] and "carbs_ok" in r]
    carbs_ok = sum(r["carbs_ok"] for r in bucket)
    result = verdict(bucket)
    summary = {
        "dir": str(folder),
        "bucket_photos": len(bucket),
        "carbs_correct": carbs_ok,
        "verdict": result,
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    tag = "smoke_test" if folder.name == "kitchen" else f"smoke_test_{folder.name}"
    (REPORTS / f"{tag}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False)
    )
    (REPORTS / f"{tag}.md").write_text(render_report(folder, rows, bucket, carbs_ok, result))
    print(
        f"{len(rows)} images, carbs correct {carbs_ok}/{len(bucket)}, verdict {result or 'n/a'} -> _notes/reports/{tag}.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
