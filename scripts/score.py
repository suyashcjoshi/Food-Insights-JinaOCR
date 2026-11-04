"""Score OCR + parser against the Open Food Facts sample (BRIEF 7.6).

    uv run python scripts/score.py              # OCR every image (cached), then score
    uv run python scripts/score.py --rescore    # score from cached OCR only, no API calls
    uv run python scripts/score.py --limit 10

Only `panel.nutrients` (per 100 g) is compared; nothing under `secondary` is ever scored.
Tolerance: +-0.5 g (or mg/mcg) and +-5 kcal. A field is correct, wrong (parsed, outside tolerance)
or missing (not parsed). Scores are against OFF, which can disagree with the pack.
Every wrong or missing field is classified by likely cause (see `classify`), and
`model_read_accuracy` says whether the OFF value appears anywhere in the raw OCR text.
`--freeze-baseline OLD_SCORE.json` re-annotates the rows of a score.json made by an older parser
and stores them in reports/baseline/score_before.json; every later run prints a before/after table
against it (same classifier on both sides, so the categories are comparable).
Writes reports/score.md and reports/score.json; raw OCR is cached in data/off/ocr_cache/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import eis
from app.images import prepare, to_data_url
from app.ocr import is_looped, strip_regions
from app.parse import LABEL_RE, fold, normalize, parse

OFF = ROOT / "data" / "off"
CACHE = OFF / "ocr_cache"
REPORTS = ROOT / "reports"
TOL = {"energy_kcal": 5.0}
DEFAULT_TOL = 0.5
WORKERS = 4
BASELINE = REPORTS / "baseline" / "score_before.json"
KJ_PER_KCAL = 4.184
CATEGORIES = ("shift", "comma", "unit", "synonym", "column", "truth_disagreement", "model")
CATEGORY_HELP = {
    "shift": "value sits on another nutrient's row, or the parser gave this value to a neighbour",
    "comma": "decimal comma misread (`1,7` taken as 17 or 7)",
    "unit": "kJ read as kcal, g/mg mixed up, sodium vs salt",
    "synonym": "the value is in the text on a row whose label the parser does not know",
    "column": "the label is known and the value is on its row, but another column was taken",
    "truth_disagreement": "OFF value not in the text and every parsed field is off by a similar small ratio",
    "model": "OFF value is not on this nutrient's row (or at all): misread, dropped, not that label, or OFF is wrong",
}


def cost_est(usage: dict) -> float | None:
    """USD from reported tokens; None (omitted) when the price env vars are blank."""
    pin, pout = os.getenv("EIS_OCR_PRICE_PER_MTOK_IN"), os.getenv("EIS_OCR_PRICE_PER_MTOK_OUT")
    if not pin or not pout or not usage:
        return None
    tokens_in, tokens_out = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
    return (tokens_in * float(pin) + tokens_out * float(pout)) / 1e6


def ocr(entry: dict, use_api: bool) -> dict | None:
    """Cached OCR record for one manifest entry; calls the API only if allowed and not cached."""
    cache = CACHE / f"{entry['barcode']}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if not use_api:
        return None
    call = eis.ocr_chat(to_data_url(prepare(OFF / entry["image"])))
    rec = {
        "status": call.status,
        "ms": call.ms,
        "usage": call.usage,
        "finish_reason": call.finish_reason,
        "text": call.text,
        "error": None if call.ok else call.raw[:300],
    }
    if call.ok:  # never cache a failure, so a rerun retries it
        cache.write_text(json.dumps(rec, ensure_ascii=False))
    return rec


def _forms(want: float) -> set[str]:
    return {f"{want:g}", f"{want:.1f}", f"{want:.2f}", f"{want:.3f}"}


def _pattern(forms: set[str]) -> re.Pattern:
    return re.compile("|".join(rf"(?<![\d.,]){re.escape(f)}(?![\d])" for f in sorted(forms)))


def in_text(want: float, text: str, key: str = "") -> bool:
    """Is the OFF value (normalised) written anywhere in the OCR text? Normalised: decimal comma or
    dot, trailing zeros, and for energy a whole kcal or the kJ equivalent (within 1 %). If not, a
    miss is not the parser's fault: the model misread it, the photo is not that label, or OFF is
    wrong. Zero is "read" by definition (it is everywhere), so it never hides a parser miss."""
    if want == 0:
        return True
    forms = _forms(want)
    forms |= {f.replace(".", ",") for f in forms}
    if key == "energy_kcal":
        forms |= {str(round(want))}
        kj = want * KJ_PER_KCAL
        if any(
            abs(int(n) - kj) <= 0.01 * kj for n in re.findall(r"(?<![\d.,])\d{3,4}(?![\d.,])", text)
        ):
            return True
    return bool(_pattern(forms).search(text))


def _comma_only(want: float, text: str) -> bool:
    """The value is written with a decimal comma and never with a dot."""
    if want == int(want):
        return False
    dots = _forms(want)
    commas = {f.replace(".", ",") for f in dots}
    return bool(_pattern(commas).search(text)) and not _pattern(dots).search(text)


def _tol(key: str) -> float:
    return TOL.get(key, DEFAULT_TOL)


def _same(a: float, b: float, key: str) -> bool:
    """Tight equality used to recognise 'this is another nutrient's number'."""
    return abs(a - b) <= (1.0 if key == "energy_kcal" else 0.06)


def similar_small_ratio(fields: dict) -> bool:
    """Every parsed field is within 15 % of OFF, at least 3 are parsed, and at least 2 are outside
    tolerance: the whole panel is a little off (a different recipe or revision), not misread."""
    ratios = [f["got"] / f["want"] for f in fields.values() if f["got"] is not None and f["want"]]
    wrong = sum(f["outcome"] == "wrong" for f in fields.values())
    return len(ratios) >= 3 and wrong >= 2 and all(abs(r - 1) <= 0.15 for r in ratios)


def _keys_on(line: str) -> set[str]:
    return {m.lastgroup for m in LABEL_RE.finditer(line)}


def classify(key: str, fields: dict, text: str) -> str:
    """Why a wrong/missing field is wrong. First match wins, in this order:

    unit       parsed value is kJ-as-kcal (x4.184), x1000 or /1000, or salt vs sodium (x2.5);
               or energy is missing while only the kJ value is in the text
    shift      parsed value equals another nutrient's OFF value, or this OFF value was parsed for
               another nutrient (merged two-line labels shift every row below by one)
    comma      value is written with a decimal comma and the parser produced its digits glued
    (OFF value 0:) column if a zero sits on a row of this nutrient, else model
    (not in the text:) truth_disagreement if the whole panel is a little off, else model
    (in the text, on a row with:) this key's label -> column; no known label -> synonym;
               only other nutrients' labels -> shift
    """
    f = fields[key]
    want, got = f["want"], f["got"]
    if got is not None and want:
        r = got / want
        if key == "energy_kcal" and abs(r - KJ_PER_KCAL) <= 0.03 * KJ_PER_KCAL:
            return "unit"
        if abs(r - 1000) <= 20 or abs(r - 0.001) <= 0.00002:
            return "unit"
        if key == "salt_g" and (abs(r - 2.5) <= 0.1 or abs(r - 0.4) <= 0.02):
            return "unit"
    if key == "energy_kcal" and got is None and want:
        kj = want * KJ_PER_KCAL
        ints = [int(n) for n in re.findall(r"(?<![\d.,])\d{3,4}(?![\d.,])", text)]
        if any(abs(n - kj) <= 0.01 * kj for n in ints) and not _pattern({str(round(want))}).search(
            text
        ):
            return "unit"
    for other, o in fields.items():
        if other == key:
            continue
        if got and o["want"] and _same(got, o["want"], key):
            return "shift"
        if want and o["got"] and _same(o["got"], want, key):
            return "shift"
    if got is not None and want and _comma_only(want, text):
        digits = float(f"{want:g}".replace(".", ""))
        if got in {digits, float(int(want)), digits / 10}:
            return "comma"
    if want == 0:  # "0" is on every label, so only a zero on a row of this nutrient counts as read
        zero = re.compile(r"(?<![\d.,])0(?:[.,]0+)?(?![\d])")
        lines = [fold(ln) for ln in normalize(text)]
        rows = [i for i, ln in enumerate(lines) if zero.search(ln)]
        return "column" if any(key in _keys_on(lines[i]) for i in rows) else "model"
    if not f["in_text"]:
        return (
            "truth_disagreement"
            if f["outcome"] == "wrong" and similar_small_ratio(fields)
            else "model"
        )
    forms = _forms(want) | {x.replace(".", ",") for x in _forms(want)}
    if key == "energy_kcal":
        forms |= {str(round(want))}
    rx = _pattern(forms)
    lines = [fold(ln) for ln in normalize(text)]
    seen_other = False
    for i, ln in enumerate(lines):
        if not rx.search(ln):
            continue
        keys = _keys_on(ln) or (_keys_on(lines[i - 1]) if i else set())
        if key in keys:
            return "column"
        seen_other |= bool(keys)
        if not keys:
            return "synonym"
    return "shift" if seen_other else "synonym"


def annotate(row: dict, text: str) -> None:
    """Add `model_read_accuracy` and, for wrong/missing fields, `category` to every field."""
    fields = row["fields"]
    for key, f in fields.items():
        f["in_text"] = in_text(f["want"], text, key) if f["outcome"] != "correct" else None
    for key, f in fields.items():
        f["model_read_accuracy"] = f["outcome"] == "correct" or bool(f["in_text"])
        f["category"] = None if f["outcome"] == "correct" else classify(key, fields, text)
        if f["want"] == 0 and f["category"] == "model":
            f["model_read_accuracy"] = False  # no zero on this nutrient's row: the model dropped it


def score_entry(entry: dict, rec: dict) -> dict:
    truth = entry["panel"]["nutrients"]
    row = {
        "barcode": entry["barcode"],
        "lang": entry["lang"],
        "name": entry["name"],
        "status": rec["status"],
        "ms": rec["ms"],
        "prompt_tokens": rec["usage"].get("prompt_tokens"),
        "completion_tokens": rec["usage"].get("completion_tokens"),
        "cost_est": cost_est(rec["usage"]),
        "finish_reason": rec["finish_reason"],
    }
    if rec["status"] != 200:
        return {**row, "error": rec.get("error"), "fields": {}}
    md = strip_regions(rec["text"])
    looped, _ = is_looped(md)
    res = parse(md)
    fields = {}
    for key, want in truth.items():
        got = res.nutrients.get(key)
        if got is None:
            outcome = "missing"
        else:
            outcome = "correct" if abs(got - want) <= TOL.get(key, DEFAULT_TOL) else "wrong"
        fields[key] = {"want": want, "got": got, "outcome": outcome}
    out = {
        **row,
        "looped": looped,
        "edge_cutoff_suspected": res.edge_cutoff_suspected,
        "parse_suspect": res.parse_suspect,
        "flags": res.flags,
        "verified": res.verified and not looped,
        "per_parsed": res.per,
        "basis": res.basis,
        "fields": fields,
    }
    annotate(out, md)
    return out


def tally(rows: list[dict]) -> dict:
    counts = {"correct": 0, "wrong": 0, "missing": 0}
    carbs = {"correct": 0, "wrong": 0, "missing": 0}
    for r in rows:
        for key, f in r["fields"].items():
            counts[f["outcome"]] += 1
            if key == "carbohydrates_g":
                carbs[f["outcome"]] += 1
    total = sum(counts.values())
    n = sum(carbs.values())
    return {
        "images": len(rows),
        "fields": total,
        **counts,
        "field_accuracy": round(counts["correct"] / total, 3) if total else None,
        "carbs_accuracy": round(carbs["correct"] / n, 3) if n else None,
    }


def pct(values: list[float], p: float) -> float | None:
    vals = sorted(v for v in values if v is not None)
    return vals[min(len(vals) - 1, int(p * len(vals)))] if vals else None


def digest(rows: list[dict]) -> dict:
    """The numbers compared before/after: accuracy, verified share, model reads, miss categories."""
    ok = [r for r in rows if r["status"] == 200]
    verified = [r for r in ok if r["verified"]]
    cats = {c: 0 for c in CATEGORIES}
    reads = n = 0
    for r in ok:
        for f in r["fields"].values():
            n += 1
            reads += f["model_read_accuracy"]
            if f["category"]:
                cats[f["category"]] += 1
    return {
        **tally(ok),
        "verified": {
            **tally(verified),
            "share_of_images": round(len(verified) / max(1, len(ok)), 3),
        },
        "model_read_accuracy": round(reads / n, 3) if n else None,
        "categories": cats,
        "per_language": {
            lang: tally([r for r in ok if r["lang"] == lang])
            for lang in sorted({r["lang"] for r in ok})
        },
    }


def freeze_baseline(old_path: Path, texts: dict[str, str]) -> None:
    old = json.loads(old_path.read_text())["rows"]
    for r in old:
        if r["status"] == 200 and r["barcode"] in texts:
            annotate(r, texts[r["barcode"]])
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps({"rows": old}, indent=1, ensure_ascii=False))
    print(f"baseline frozen: {len(old)} rows -> {BASELINE.relative_to(ROOT)}")


def ratio(a: float | None) -> str:
    return "-" if a is None else f"{a:.0%}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true", help="use cached OCR only, no API calls")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--freeze-baseline", type=Path, help="score.json from the old parser")
    args = ap.parse_args()

    entries = [json.loads(ln) for ln in (OFF / "manifest.jsonl").read_text().splitlines()]
    entries = entries[: args.limit] if args.limit else entries
    CACHE.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(WORKERS) as pool:
        recs = list(pool.map(lambda e: ocr(e, not args.rescore), entries))

    if args.freeze_baseline:
        texts = {
            e["barcode"]: strip_regions(r["text"])
            for e, r in zip(entries, recs, strict=True)
            if r and r["status"] == 200
        }
        freeze_baseline(args.freeze_baseline, texts)
        return 0

    rows, skipped = [], 0
    for entry, rec in zip(entries, recs, strict=True):
        if rec is None:
            skipped += 1
            continue
        rows.append(score_entry(entry, rec))
    ok_rows = [r for r in rows if r["status"] == 200]
    errors = len(rows) - len(ok_rows)

    by_lang: dict[str, list[dict]] = defaultdict(list)
    for r in ok_rows:
        by_lang[r["lang"]].append(r)
    overall = tally(ok_rows)
    verified = [r for r in ok_rows if r["verified"]]
    summary = {
        "overall": overall,
        "per_language": {k: tally(v) for k, v in sorted(by_lang.items())},
        "verified": {
            **tally(verified),
            "share_of_images": round(len(verified) / max(1, len(ok_rows)), 3),
        },
        "looped": sum(r["looped"] for r in ok_rows),
        "errors": errors,
        "not_cached": skipped,
        "tokens_in": {
            "p50": pct([r["prompt_tokens"] for r in ok_rows], 0.5),
            "p95": pct([r["prompt_tokens"] for r in ok_rows], 0.95),
        },
        "tokens_out": {
            "p50": pct([r["completion_tokens"] for r in ok_rows], 0.5),
            "p95": pct([r["completion_tokens"] for r in ok_rows], 0.95),
        },
        "ms": {
            "p50": pct([r["ms"] for r in ok_rows], 0.5),
            "p95": pct([r["ms"] for r in ok_rows], 0.95),
        },
        "cost_est_total": round(sum(r["cost_est"] for r in ok_rows if r["cost_est"] is not None), 6)
        if any(r["cost_est"] is not None for r in ok_rows)
        else None,
    }
    misses = [f for r in ok_rows for f in r["fields"].values() if f["outcome"] != "correct"]
    summary["misses"] = {
        "total": len(misses),
        "value_in_ocr_text": sum(bool(f["in_text"]) for f in misses),
        "value_not_in_ocr_text": sum(not f["in_text"] for f in misses),
    }
    after = digest(rows)
    summary["model_read_accuracy"] = after["model_read_accuracy"]
    summary["categories"] = after["categories"]
    summary["parse_suspect_images"] = sum(r["parse_suspect"] for r in ok_rows)
    before = None
    if BASELINE.exists():
        base_rows = json.loads(BASELINE.read_text())["rows"]
        keep = {r["barcode"] for r in rows}  # same images on both sides
        before = digest([r for r in base_rows if r["barcode"] in keep])
        summary["before"] = before
    by_key: dict[str, dict] = {}
    for r in ok_rows:
        for key, f in r["fields"].items():
            by_key.setdefault(key, {"correct": 0, "wrong": 0, "missing": 0})[f["outcome"]] += 1
    summary["per_nutrient"] = by_key

    REPORTS.mkdir(exist_ok=True)
    (REPORTS / "score.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False)
    )

    def acc(t: dict) -> str:
        return "-" if t["field_accuracy"] is None else f"{t['field_accuracy']:.0%}"

    md = [
        "# OFF score",
        "",
        "Per 100 g, tolerance ±0.5 g (±5 kcal). Truth is Open Food Facts, which can disagree with the pack.",
        "",
        "| Language | Images | Carbs correct | Fields correct | wrong | missing |",
        "|---|---|---|---|---|---|",
    ]
    for lang, t in {**summary["per_language"], "**all**": overall}.items():
        carbs = "-" if t["carbs_accuracy"] is None else f"{t['carbs_accuracy']:.0%}"
        md.append(
            f"| {lang} | {t['images']} | {carbs} | {acc(t)} ({t['correct']}/{t['fields']}) | {t['wrong']} | {t['missing']} |"
        )
    v = summary["verified"]
    md += [
        "",
        (
            f"- Verified (panel parsed, no cut-off flag, not looped): {v['images']} of {len(ok_rows)} images; "
            f"field accuracy among them {acc(v)}, carbs {'-' if v['carbs_accuracy'] is None else format(v['carbs_accuracy'], '.0%')}"
        ),
        f"- Looped outputs: {summary['looped']}; API errors: {errors}; not cached: {skipped}",
        (
            f"- Tokens in p50/p95: {summary['tokens_in']['p50']}/{summary['tokens_in']['p95']}; "
            f"out p50/p95: {summary['tokens_out']['p50']}/{summary['tokens_out']['p95']}"
        ),
        f"- Latency ms p50/p95: {summary['ms']['p50']}/{summary['ms']['p95']}",
    ]
    if summary["cost_est_total"] is not None:
        md.append(f"- cost_est for the whole run: ${summary['cost_est_total']:.5f}")
    m = summary["misses"]
    md += [
        (
            f"- Of {m['total']} wrong or missing fields, {m['value_in_ocr_text']} have the OFF value "
            f"somewhere in the OCR text (parser or column choice may be at fault) and "
            f"{m['value_not_in_ocr_text']} do not (model misread, photo is not that label, or OFF is wrong)"
        ),
    ]
    md += [
        (
            f"- Model read accuracy (OFF value appears in the OCR text, normalised): "
            f"{ratio(summary['model_read_accuracy'])}"
        ),
        f"- Panels flagged parse_suspect: {summary['parse_suspect_images']}",
    ]
    if before:
        a, b = after, before
        md += [
            "",
            "## Before / after the parser changes",
            "",
            (
                "Before = the parser as of the first full score (frozen in `reports/baseline/`); same 50 images, "
                "same cached OCR text, same classifier on both sides."
            ),
            "",
            "| | before | after |",
            "|---|---|---|",
            f"| Carbs correct | {ratio(b['carbs_accuracy'])} | {ratio(a['carbs_accuracy'])} |",
            (
                f"| Fields correct | {ratio(b['field_accuracy'])} ({b['correct']}/{b['fields']}) | "
                f"{ratio(a['field_accuracy'])} ({a['correct']}/{a['fields']}) |"
            ),
            f"| Wrong | {b['wrong']} | {a['wrong']} |",
            f"| Missing | {b['missing']} | {a['missing']} |",
            f"| Model read accuracy | {ratio(b['model_read_accuracy'])} | {ratio(a['model_read_accuracy'])} |",
            f"| Images verified | {b['verified']['images']} | {a['verified']['images']} |",
            (
                f"| Field accuracy among verified | {ratio(b['verified']['field_accuracy'])} "
                f"({b['verified']['correct']}/{b['verified']['fields']}) | "
                f"{ratio(a['verified']['field_accuracy'])} ({a['verified']['correct']}/{a['verified']['fields']}) |"
            ),
            "",
            "| Language | before | after |",
            "|---|---|---|",
        ]
        for lang in a["per_language"]:
            bl, al = b["per_language"].get(lang, {}), a["per_language"][lang]
            md.append(
                f"| {lang} | {ratio(bl.get('field_accuracy'))} ({bl.get('correct')}/{bl.get('fields')}) | "
                f"{ratio(al['field_accuracy'])} ({al['correct']}/{al['fields']}) |"
            )
    cats = summary["categories"]
    md += [
        "",
        "## Why fields are wrong or missing",
        "",
        "Each wrong or missing field gets one cause, first match wins (order below).",
        "",
        "| Category | before | after | meaning |",
        "|---|---|---|---|",
    ]
    for c in CATEGORIES:
        bc = "-" if not before else before["categories"][c]
        md.append(f"| {c} | {bc} | {cats[c]} | {CATEGORY_HELP[c]} |")
    md += [
        f"| **total** | {'-' if not before else sum(before['categories'].values())} | {sum(cats.values())} | |",
        "",
        (
            "A zero-valued OFF field counts as read only if a zero sits on a row of that nutrient. "
            "Multi-language blobs with 20+ languages (labels the parser has no synonyms for) land in "
            "`synonym`; they are out of scope."
        ),
        "",
        "## Per nutrient",
        "",
        "| Nutrient | correct | wrong | missing |",
        "|---|---|---|---|",
    ]
    md += [f"| {k} | {c['correct']} | {c['wrong']} | {c['missing']} |" for k, c in by_key.items()]
    bad = [(r, k, f) for r in ok_rows for k, f in r["fields"].items() if f["outcome"] == "wrong"]
    if bad:
        md += [
            "",
            "## Wrong values (parsed, outside tolerance)",
            "",
            "| Barcode | Lang | Nutrient | OFF | Parsed |",
            "|---|---|---|---|---|",
        ]
        md += [
            f"| {r['barcode']} | {r['lang']} | {k} | {f['want']} | {f['got']} |" for r, k, f in bad
        ]
    (REPORTS / "score.md").write_text("\n".join(md) + "\n")

    print(
        f"{len(ok_rows)} images, carbs {overall['carbs_accuracy']}, fields {overall['field_accuracy']} "
        f"({overall['correct']}/{overall['fields']}), looped {summary['looped']}, errors {errors} -> reports/score.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
