"""Smoke test on real photos (BRIEF 7.3).

    uv run python scripts/smoke_test.py                       # data/kitchen
    uv run python scripts/smoke_test.py --dir data/scratch    # exploratory, no pass/fail

For each image: EXIF transpose, resize <=1600 px, OCR (primary API: non-streaming
chat_completion), parse, then compare against `panel.nutrients` in `<stem>.truth.json`.
Only the panel is scored. PASS if >= 4 of 5 bucket photos parse carbohydrates correctly;
occluded / sideways / two_products are recorded as prose, not scored.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import eis
from app.images import prepare, to_data_url
from app.ocr import is_looped, strip_regions
from app.parse import parse

REPORTS = ROOT / "reports"
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
EDGE_CASES = {"occluded", "sideways", "two_products"}
CARB_TOL = 0.5
NUTRIENT_TOL = {"energy_kcal": 5}  # everything else +-0.5


def cost_est(usage: dict) -> float | None:
    """USD from reported tokens; None (omitted) when the price env vars are blank."""
    pin, pout = os.getenv("EIS_OCR_PRICE_PER_MTOK_IN"), os.getenv("EIS_OCR_PRICE_PER_MTOK_OUT")
    if not pin or not pout or not usage:
        return None
    return (
        usage.get("prompt_tokens", 0) * float(pin) + usage.get("completion_tokens", 0) * float(pout)
    ) / 1e6


def compare(parsed: dict, truth: dict) -> dict:
    """Score parsed nutrients against panel.nutrients only (nothing under `secondary`)."""
    detail = {}
    for key, want in truth.items():
        got = parsed.get(key)
        tol = NUTRIENT_TOL.get(key, 0.5)
        detail[key] = {"want": want, "got": got, "ok": got is not None and abs(got - want) <= tol}
    return {
        "correct": sum(d["ok"] for d in detail.values()),
        "total": len(detail),
        "detail": detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(ROOT / "data" / "kitchen"))
    ap.add_argument("--prompt", default=eis.OFFICIAL_PROMPT)
    args = ap.parse_args()
    folder = Path(args.dir)
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in EXTS)
    if not images:
        sys.exit(f"no images in {folder}")

    rows = []
    for path in images:
        truth_file = path.with_suffix(".truth.json")
        truth = (
            json.loads(truth_file.read_text())["panel"]["nutrients"]
            if truth_file.exists()
            else None
        )
        call = eis.ocr_chat(to_data_url(prepare(path)), args.prompt)
        md = strip_regions(call.text)
        looped, ratio = is_looped(md)
        res = parse(md)
        row = {
            "image": path.name,
            "edge_case": path.stem in EDGE_CASES,
            "status": call.status,
            "ms": call.ms,
            "prompt_tokens": call.usage.get("prompt_tokens"),
            "completion_tokens": call.usage.get("completion_tokens"),
            "finish_reason": call.finish_reason,
            "cost_est": cost_est(call.usage),
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
        rows.append(row)
        carbs = (
            f"carbs {row['carbs_parsed']} vs {row['carbs_pack']}"
            if truth
            else f"carbs {row['carbs_parsed']} (no truth)"
        )
        acc = f" panel {row['score']['correct']}/{row['score']['total']}" if truth else ""
        print(
            f"{path.name:22} {carbs:28}{acc} tok {row['prompt_tokens']}/{row['completion_tokens']} {call.ms} ms"
            f"{' LOOPED' if looped else ''}{' CUTOFF?' if res.edge_cutoff_suspected else ''}"
        )

    bucket = [r for r in rows if not r["edge_case"] and "carbs_ok" in r]
    ok = sum(r["carbs_ok"] for r in bucket)
    verdict = None
    if len(bucket) >= 5:
        verdict = "PASS" if ok >= 4 else "FAIL"
    summary = {
        "dir": str(folder),
        "bucket_photos": len(bucket),
        "carbs_correct": ok,
        "verdict": verdict,
    }
    REPORTS.mkdir(exist_ok=True)
    tag = "smoke_test" if folder.name == "kitchen" else f"smoke_test_{folder.name}"
    (REPORTS / f"{tag}.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False)
    )
    md = [
        f"# Smoke test ({folder.name})",
        "",
        f"Bucket photos with truth: {len(bucket)}; carbs correct: {ok}; verdict: {verdict or 'n/a (needs 5 bucket photos with truth)'}",
        "",
        "| Image | carbs parsed | carbs pack | panel | tokens in/out | ms | flags |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        sc = r.get("score")
        flags = ", ".join(
            f
            for f, on in (
                ("looped", r["looped"]),
                ("cutoff?", r["edge_cutoff_suspected"]),
                ("edge case", r["edge_case"]),
            )
            if on
        )
        md.append(
            f"| {r['image']} | {r['carbs_parsed']} | {r['carbs_pack']} | {f'{sc["correct"]}/{sc["total"]}' if sc else '-'} | {r['prompt_tokens']}/{r['completion_tokens']} | {r['ms']} | {flags} |"
        )
    (REPORTS / f"{tag}.md").write_text("\n".join(md) + "\n")
    print(
        f"{len(rows)} images, carbs correct {ok}/{len(bucket)}, verdict {verdict or 'n/a'} -> reports/{tag}.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
