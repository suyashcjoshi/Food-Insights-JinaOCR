"""Score OCR + parser against the Open Food Facts sample.

    uv run python scripts/score.py              # OCR every image (cached), then score
    uv run python scripts/score.py --rescore    # score from cached OCR only, no API calls
    uv run python scripts/score.py --limit 10

Only `panel.nutrients` (per 100 g) is compared; nothing under `secondary` is ever scored.
Tolerance: +-0.5 g (or mg/mcg) and +-5 kcal. A field is correct, wrong (parsed, outside tolerance)
or missing (not parsed). Scores are against OFF, which can disagree with the pack.
Every wrong or missing field is classified by likely cause (see `classify`), and
`model_read_accuracy` says whether the OFF value appears anywhere in the raw OCR text.
`--freeze-baseline OLD_SCORE.json` re-annotates the rows of a score.json made by an older parser
and stores them in _notes/reports/baseline/score_before.json; every later run prints a before/after table
against it (same classifier on both sides, so the categories are comparable).
Writes _notes/reports/score.md/.json; raw reader output is cached in data/off/ocr_cache_reader/.

Layout: OCR cache -> matching an OFF value inside the OCR text -> why a field is wrong (`classify`)
-> scoring one image -> tallies -> the summary dict -> the Markdown report -> `main`.
"""

from __future__ import annotations

import argparse
import json
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
CACHE = OFF / "ocr_cache_reader"
REPORTS = ROOT / "_notes" / "reports"  # git-ignored: results are local notes, not part of the repo
BASELINE = REPORTS / "baseline" / "score_before.json"

WORKERS = 4
TOL = {"energy_kcal": 5.0}
DEFAULT_TOL = 0.5
MIN_CHART_N = 5  # a language with fewer images is shown with its n but kept out of the chart data
KJ_PER_KCAL = 4.184
ZERO_RE = re.compile(r"(?<![\d.,])0(?:[.,]0+)?(?![\d])")
KJ_NUMBER_RE = re.compile(r"(?<![\d.,])\d{3,4}(?![\d.,])")  # a 3-4 digit number: maybe kJ
SAME_NUTRIENT_TOL = {"energy_kcal": 1.0}  # tight equality: "this is another nutrient's number"
DEFAULT_SAME_TOL = 0.06
SMALL_RATIO_TOL = 0.15  # `similar_small_ratio`: every parsed field is this close to OFF

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


# --- the OCR cache -----------------------------------------------------------------------------


def ocr(entry: dict, use_api: bool) -> dict | None:
    """Cached OCR record for one manifest entry; calls the API only if allowed and not cached."""
    cache = CACHE / f"{entry['barcode']}.json"
    if cache.exists():
        return json.loads(cache.read_text())
    if not use_api:
        return None
    call = eis.read(to_data_url(prepare(OFF / entry["image"])))
    rec = {
        "status": call.status,
        "ms": call.ms,
        "text": call.text,
        "error": None if call.ok else call.raw[:300],
    }
    if call.ok:  # never cache a failure, so a rerun retries it
        cache.write_text(json.dumps(rec, ensure_ascii=False))
    return rec


# --- is the OFF value written anywhere in the OCR text? ----------------------------------------


def _forms(want: float) -> set[str]:
    return {f"{want:g}", f"{want:.1f}", f"{want:.2f}", f"{want:.3f}"}


def _pattern(forms: set[str]) -> re.Pattern:
    return re.compile("|".join(rf"(?<![\d.,]){re.escape(f)}(?![\d])" for f in sorted(forms)))


def _written_forms(want: float, key: str) -> set[str]:
    """Every way the value can be printed: dot or comma, trailing zeros, a whole kcal."""
    forms = _forms(want)
    forms |= {f.replace(".", ",") for f in forms}
    if key == "energy_kcal":
        forms |= {str(round(want))}
    return forms


def _kj_in_text(want_kcal: float, text: str) -> bool:
    """The kJ equivalent of a kcal value (within 1 %) is printed somewhere."""
    kj = want_kcal * KJ_PER_KCAL
    return any(abs(int(n) - kj) <= 0.01 * kj for n in KJ_NUMBER_RE.findall(text))


def in_text(want: float, text: str, key: str = "") -> bool:
    """Is the OFF value (normalised) written anywhere in the OCR text? Normalised: decimal comma or
    dot, trailing zeros, and for energy a whole kcal or the kJ equivalent (within 1 %). If not, a
    miss is not the parser's fault: the model misread it, the photo is not that label, or OFF is
    wrong. Zero is "read" by definition (it is everywhere), so it never hides a parser miss."""
    if want == 0:
        return True
    if key == "energy_kcal" and _kj_in_text(want, text):
        return True
    return bool(_pattern(_written_forms(want, key)).search(text))


def _comma_only(want: float, text: str) -> bool:
    """The value is written with a decimal comma and never with a dot."""
    if want == int(want):
        return False
    dots = _forms(want)
    commas = {f.replace(".", ",") for f in dots}
    return bool(_pattern(commas).search(text)) and not _pattern(dots).search(text)


# --- why is a field wrong or missing? ----------------------------------------------------------


def _same(a: float, b: float, key: str) -> bool:
    """Tight equality used to recognise 'this is another nutrient's number'."""
    return abs(a - b) <= SAME_NUTRIENT_TOL.get(key, DEFAULT_SAME_TOL)


def similar_small_ratio(fields: dict) -> bool:
    """Every parsed field is within 15 % of OFF, at least 3 are parsed, and at least 2 are outside
    tolerance: the whole panel is a little off (a different recipe or revision), not misread."""
    ratios = [f["got"] / f["want"] for f in fields.values() if f["got"] is not None and f["want"]]
    wrong = sum(f["outcome"] == "wrong" for f in fields.values())
    return len(ratios) >= 3 and wrong >= 2 and all(abs(r - 1) <= SMALL_RATIO_TOL for r in ratios)


def _keys_on(line: str) -> set[str]:
    return {m.lastgroup for m in LABEL_RE.finditer(line)}


def _is_unit_error(key: str, f: dict, text: str) -> bool:
    """kJ read as kcal, x1000 or /1000, salt vs sodium, or only the kJ figure is in the text."""
    want, got = f["want"], f["got"]
    if got is not None and want:
        r = got / want
        if key == "energy_kcal" and abs(r - KJ_PER_KCAL) <= 0.03 * KJ_PER_KCAL:
            return True
        if abs(r - 1000) <= 20 or abs(r - 0.001) <= 0.00002:
            return True
        if key == "salt_g" and (abs(r - 2.5) <= 0.1 or abs(r - 0.4) <= 0.02):
            return True
    if key == "energy_kcal" and got is None and want:
        return _kj_in_text(want, text) and not _pattern({str(round(want))}).search(text)
    return False


def _is_shift(key: str, fields: dict) -> bool:
    """The parsed value is another nutrient's OFF value, or this OFF value went to another nutrient."""
    want, got = fields[key]["want"], fields[key]["got"]
    for other, o in fields.items():
        if other == key:
            continue
        if got and o["want"] and _same(got, o["want"], key):
            return True
        if want and o["got"] and _same(o["got"], want, key):
            return True
    return False


def _is_glued_comma(f: dict, text: str) -> bool:
    """Written `1,7` and parsed as 17, 1 or 0.17: the comma was dropped."""
    want, got = f["want"], f["got"]
    if got is None or not want or not _comma_only(want, text):
        return False
    digits = float(f"{want:g}".replace(".", ""))
    return got in {digits, float(int(want)), digits / 10}


def _zero_cause(key: str, text: str) -> str:
    """ "0" is on every label, so only a zero on a row of this nutrient counts as read."""
    lines = [fold(ln) for ln in normalize(text)]
    rows = [i for i, ln in enumerate(lines) if ZERO_RE.search(ln)]
    return "column" if any(key in _keys_on(lines[i]) for i in rows) else "model"


def _row_cause(key: str, want: float, text: str) -> str:
    """The value is in the text: on this nutrient's row (`column`), on a row with no known label
    (`synonym`), or only on other nutrients' rows (`shift`)."""
    rx = _pattern(_written_forms(want, key))
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
    if _is_unit_error(key, f, text):
        return "unit"
    if _is_shift(key, fields):
        return "shift"
    if _is_glued_comma(f, text):
        return "comma"
    if f["want"] == 0:
        return _zero_cause(key, text)
    if not f["in_text"]:
        wrong_and_close = f["outcome"] == "wrong" and similar_small_ratio(fields)
        return "truth_disagreement" if wrong_and_close else "model"
    return _row_cause(key, f["want"], text)


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


# --- scoring one image -------------------------------------------------------------------------


def _outcome(key: str, want: float, got: float | None) -> str:
    if got is None:
        return "missing"
    return "correct" if abs(got - want) <= TOL.get(key, DEFAULT_TOL) else "wrong"


def _compare(truth: dict[str, float], parsed: dict[str, float]) -> dict[str, dict]:
    """Per nutrient: the OFF value, what the parser read, and whether it is within tolerance."""
    fields = {}
    for key, want in truth.items():
        got = parsed.get(key)
        fields[key] = {"want": want, "got": got, "outcome": _outcome(key, want, got)}
    return fields


def score_entry(entry: dict, rec: dict) -> dict:
    row = {
        "barcode": entry["barcode"],
        "lang": entry["lang"],
        "name": entry["name"],
        "status": rec["status"],
        "ms": rec["ms"],
    }
    if rec["status"] != 200:
        return {**row, "error": rec.get("error"), "fields": {}}
    md = strip_regions(rec["text"])
    looped, _ = is_looped(md)
    res = parse(md)
    out = {
        **row,
        "looped": looped,
        "edge_cutoff_suspected": res.edge_cutoff_suspected,
        "parse_suspect": res.parse_suspect,
        "flags": res.flags,
        "verified": res.verified and not looped,
        "per_parsed": res.per,
        "basis": res.basis,
        "fields": _compare(entry["panel"]["nutrients"], res.nutrients),
    }
    annotate(out, md)
    return out


def score_all(entries: list[dict], recs: list[dict | None]) -> tuple[list[dict], int]:
    """Score every image that has OCR; returns (rows, number without a cached OCR record)."""
    rows = [score_entry(e, r) for e, r in zip(entries, recs, strict=True) if r is not None]
    return rows, len(entries) - len(rows)


# --- tallies -----------------------------------------------------------------------------------


def _outcome_counts() -> dict[str, int]:
    return {"correct": 0, "wrong": 0, "missing": 0}


def tally(rows: list[dict]) -> dict:
    counts, carbs = _outcome_counts(), _outcome_counts()
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


# --- the summary (what score.json holds) -------------------------------------------------------


def _chart_row(language: str, t: dict) -> dict:
    return {
        "language": language,
        "images": t["images"],
        "field_accuracy": t["field_accuracy"],
        "carbs_accuracy": t["carbs_accuracy"],
    }


def _per_nutrient(ok_rows: list[dict]) -> dict[str, dict]:
    by_key: dict[str, dict] = {}
    for r in ok_rows:
        for key, f in r["fields"].items():
            by_key.setdefault(key, _outcome_counts())[f["outcome"]] += 1
    return by_key


def build_summary(rows: list[dict], recs: list[dict | None], skipped: int) -> tuple[dict, dict]:
    """Everything score.json reports, plus the `digest` of this run (the report's "after")."""
    ok_rows = [r for r in rows if r["status"] == 200]
    by_lang: dict[str, list[dict]] = defaultdict(list)
    for r in ok_rows:
        by_lang[r["lang"]].append(r)
    overall = tally(ok_rows)
    per_language = {k: tally(v) for k, v in sorted(by_lang.items())}
    verified = [r for r in ok_rows if r["verified"]]
    misses = [f for r in ok_rows for f in r["fields"].values() if f["outcome"] != "correct"]
    after = digest(rows)
    summary = {
        "overall": overall,
        "per_language": per_language,
        "verified": {
            **tally(verified),
            "share_of_images": round(len(verified) / max(1, len(ok_rows)), 3),
        },
        "looped": sum(r["looped"] for r in ok_rows),
        "errors": len(rows) - len(ok_rows),
        "not_cached": skipped,
        "ms": {
            "p50": pct([r["ms"] for r in ok_rows], 0.5),
            "p95": pct([r["ms"] for r in ok_rows], 0.95),
        },
        "misses": {
            "total": len(misses),
            "value_in_ocr_text": sum(bool(f["in_text"]) for f in misses),
            "value_not_in_ocr_text": sum(not f["in_text"] for f in misses),
        },
        "model_read_accuracy": after["model_read_accuracy"],
        "categories": after["categories"],
        "parse_suspect_images": sum(r["parse_suspect"] for r in ok_rows),
        "chart": [
            _chart_row(lang, t) for lang, t in per_language.items() if t["images"] >= MIN_CHART_N
        ]
        + [_chart_row("all", overall)],
        "excluded_from_chart": {
            lang: t["images"] for lang, t in per_language.items() if t["images"] < MIN_CHART_N
        },
        "table_outputs": sum(
            "<table" in (r["text"] or "").lower() for r in recs if r and r["status"] == 200
        ),
    }
    if BASELINE.exists():
        base_rows = json.loads(BASELINE.read_text())["rows"]
        keep = {r["barcode"] for r in rows}  # same images on both sides
        summary["before"] = digest([r for r in base_rows if r["barcode"] in keep])
    summary["per_nutrient"] = _per_nutrient(ok_rows)
    return summary, after


# --- the Markdown report -----------------------------------------------------------------------


def ratio(a: float | None) -> str:
    return "-" if a is None else f"{a:.0%}"


def _count(t: dict) -> str:
    return f"{ratio(t['field_accuracy'])} ({t['correct']}/{t['fields']})"


def _language_table(summary: dict) -> list[str]:
    md = [
        "# OFF score",
        "",
        "Per 100 g, tolerance ±0.5 g (±5 kcal). Truth is Open Food Facts, which can disagree with the pack.",
        "",
        "| Language | Images | Carbs correct | Fields correct | wrong | missing |",
        "|---|---|---|---|---|---|",
    ]
    for lang, t in {**summary["per_language"], "**all**": summary["overall"]}.items():
        if lang in summary["excluded_from_chart"]:
            lang = f"{lang} (n={t['images']})"
        md.append(
            f"| {lang} | {t['images']} | {ratio(t['carbs_accuracy'])} | {_count(t)} | {t['wrong']} | {t['missing']} |"
        )
    return md


def _status_lines(summary: dict, n_ok: int) -> list[str]:
    v, m = summary["verified"], summary["misses"]
    return [
        "",
        (
            f"- Verified (panel parsed, no cut-off flag, not looped): {v['images']} of {n_ok} images; "
            f"field accuracy among them {ratio(v['field_accuracy'])}, carbs {ratio(v['carbs_accuracy'])}"
        ),
        f"- Looped outputs: {summary['looped']}; API errors: {summary['errors']}; not cached: {summary['not_cached']}",
        f"- Latency ms p50/p95: {summary['ms']['p50']}/{summary['ms']['p95']}",
        (
            f"- Of {m['total']} wrong or missing fields, {m['value_in_ocr_text']} have the OFF value "
            f"somewhere in the OCR text (parser or column choice may be at fault) and "
            f"{m['value_not_in_ocr_text']} do not (model misread, photo is not that label, or OFF is wrong)"
        ),
        (
            f"- Model read accuracy (OFF value appears in the OCR text, normalised): "
            f"{ratio(summary['model_read_accuracy'])}"
        ),
        f"- Panels flagged parse_suspect: {summary['parse_suspect_images']}",
        f"- {summary['table_outputs']} of {n_ok} outputs contain `<table>`",
    ]


def _before_after(before: dict, after: dict) -> list[str]:
    b, a = before, after
    md = [
        "",
        "## Before / after the parser changes",
        "",
        (
            "Before = the parser as of the first full score (frozen in `baseline/` next to this report); same 50 images, "
            "same cached OCR text, same classifier on both sides."
        ),
        "",
        "| | before | after |",
        "|---|---|---|",
        f"| Carbs correct | {ratio(b['carbs_accuracy'])} | {ratio(a['carbs_accuracy'])} |",
        f"| Fields correct | {_count(b)} | {_count(a)} |",
        f"| Wrong | {b['wrong']} | {a['wrong']} |",
        f"| Missing | {b['missing']} | {a['missing']} |",
        f"| Model read accuracy | {ratio(b['model_read_accuracy'])} | {ratio(a['model_read_accuracy'])} |",
        f"| Images verified | {b['verified']['images']} | {a['verified']['images']} |",
        f"| Field accuracy among verified | {_count(b['verified'])} | {_count(a['verified'])} |",
        "",
        "| Language | before | after |",
        "|---|---|---|",
    ]
    for lang in a["per_language"]:
        bl, al = b["per_language"].get(lang, {}), a["per_language"][lang]
        md.append(
            f"| {lang} | {ratio(bl.get('field_accuracy'))} ({bl.get('correct')}/{bl.get('fields')}) | "
            f"{_count(al)} |"
        )
    return md


def _excluded_note(excluded: dict[str, int]) -> list[str]:
    ex = ", ".join(f"{k} (n={v})" for k, v in excluded.items())
    return [
        "",
        (
            f"Languages with fewer than {MIN_CHART_N} images are listed with their n but left out of "
            f"`chart` in the JSON (chart data): {ex}. Their percentages move 50 points per image."
        ),
    ]


def _causes_table(summary: dict) -> list[str]:
    before, cats = summary.get("before"), summary["categories"]
    md = [
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
    before_total = "-" if not before else sum(before["categories"].values())
    md += [
        f"| **total** | {before_total} | {sum(cats.values())} | |",
        "",
        (
            "A zero-valued OFF field counts as read only if a zero sits on a row of that nutrient. "
            "Multi-language blobs with 20+ languages (labels the parser has no synonyms for) land in "
            "`synonym`; they are out of scope."
        ),
    ]
    return md


def _per_nutrient_table(by_key: dict[str, dict]) -> list[str]:
    md = [
        "",
        "## Per nutrient",
        "",
        "| Nutrient | correct | wrong | missing |",
        "|---|---|---|---|",
    ]
    return md + [
        f"| {k} | {c['correct']} | {c['wrong']} | {c['missing']} |" for k, c in by_key.items()
    ]


def _wrong_values_table(ok_rows: list[dict]) -> list[str]:
    bad = [(r, k, f) for r in ok_rows for k, f in r["fields"].items() if f["outcome"] == "wrong"]
    if not bad:
        return []
    md = [
        "",
        "## Wrong values (parsed, outside tolerance)",
        "",
        "| Barcode | Lang | Nutrient | OFF | Parsed |",
        "|---|---|---|---|---|",
    ]
    return md + [
        f"| {r['barcode']} | {r['lang']} | {k} | {f['want']} | {f['got']} |" for r, k, f in bad
    ]


def render_report(summary: dict, after: dict, ok_rows: list[dict]) -> str:
    md = _language_table(summary) + _status_lines(summary, len(ok_rows))
    if "before" in summary:
        md += _before_after(summary["before"], after)
    if summary["excluded_from_chart"]:
        md += _excluded_note(summary["excluded_from_chart"])
    md += _causes_table(summary)
    md += _per_nutrient_table(summary["per_nutrient"])
    md += _wrong_values_table(ok_rows)
    return "\n".join(md) + "\n"


# --- entry point -------------------------------------------------------------------------------


def load_entries(limit: int | None) -> list[dict]:
    entries = [json.loads(ln) for ln in (OFF / "manifest.jsonl").read_text().splitlines()]
    return entries[:limit] if limit else entries


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rescore", action="store_true", help="use cached OCR only, no API calls")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--freeze-baseline", type=Path, help="score.json from the old parser")
    args = ap.parse_args()

    entries = load_entries(args.limit)
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

    rows, skipped = score_all(entries, recs)
    ok_rows = [r for r in rows if r["status"] == 200]
    summary, after = build_summary(rows, recs, skipped)

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "score.json").write_text(
        json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False)
    )
    (REPORTS / "score.md").write_text(render_report(summary, after, ok_rows))

    overall = summary["overall"]
    print(
        f"{len(ok_rows)} images, carbs {overall['carbs_accuracy']}, fields {overall['field_accuracy']} "
        f"({overall['correct']}/{overall['fields']}), looped {summary['looped']}, "
        f"errors {summary['errors']} -> {REPORTS.relative_to(ROOT)}/score.md"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
