"""Triage the "model" misses of a score run: OFF value is not on that nutrient's row of the OCR text.

    uv run python scripts/triage_model_misses.py [--score reports/score_official.json] [--cache data/off/ocr_cache]

Writes reports/triage_model_misses.md with one row per miss and a blank `confirmed_cause` column
for a human to fill in after looking at the photo. `suggested_cause` is a heuristic, in this order:

  basis_mismatch  one serving size s found in the text (x 100/s or x s/100) explains the OFF values of
                  >= 3 fields of the image, or the text shows a serving basis and no 100 g / 100 ml
  rounding_lt05   the closest number in the text is within 0.5 (5 kcal for energy) of OFF
  revision        >= 2 fields of this image have a text number within 15% of OFF but outside
                  tolerance: the pack differs a little from OFF everywhere (recipe change)
  multilang_blob  the text carries nutrient words from 4 or more languages
  misread         none of the above (the model misread it, dropped the row, or it is not that label)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.ocr import strip_regions
from app.parse import fold

NUM = re.compile(r"(?<![\d.,])\d+(?:[.,]\d+)?(?![\d])(?!\s*%)")
BASIS = {
    "100 g": r"100\s*gr?(?![a-z])",
    "100 ml": r"100\s*ml(?![a-z])",
    "per serving": r"per\s+serving|serving\s+size",
    "per portion": r"per\s+portion|por\s+portion|par\s+portion|per\s+bar|per\s+piece",
    "par portion": r"par\s+portion",
    "pro Portion": r"pro\s+portion|je\s+portion|pro\s+stuck",
    "por porção": r"por\s+por[cç][aã]o|por\s+ra[cç][aã]o|por\s+unidade",
    "por porción": r"por\s+porci[oó]n|por\s+raci[oó]n",
}
SERVING = re.compile(r"(?<![\d.,])(\d{1,3}(?:[.,]\d+)?)\s*(?:g|ml)(?![a-z])", re.IGNORECASE)
LANG_WORDS = {  # one nutrient word per language, accent-folded, lower case
    "en": "carbohydrate", "fr": "glucides", "de": "kohlenhydrate", "es": "hidratos de carbono",
    "pt": "carboidratos|hidratos de carbono", "it": "carboidrati", "nl": "koolhydraten",
    "sv": "kolhydrat", "da": "kulhydrat", "fi": "hiilihydraatit", "pl": "weglowodany",
    "cs": "sacharidy", "hu": "szenhidrat", "el": "υδατάνθρακες", "et": "susivesikud",
    "lv": "oglhidrati", "lt": "angliavandeniai", "sl": "ogljikovi hidrati", "ro": "glucide",
    "bg": "въглехидрати", "hr": "ugljikohidrati",
}  # fmt: skip


def tol(key: str) -> float:
    return 5.0 if key == "energy_kcal" else 0.5


def numbers(text: str) -> list[float]:
    plain = re.sub(r"<[^>]+>", " ", text)
    vals = {float(n.replace(",", ".")) for n in NUM.findall(plain)}
    return sorted(vals)


def closest(want: float, vals: list[float], k: int = 3) -> list[float]:
    return sorted(vals, key=lambda v: (abs(v - want), v))[:k]


def basis_indicators(text: str) -> list[str]:
    plain = fold(re.sub(r"<[^>]+>", " ", text)).lower()
    return [name for name, rx in BASIS.items() if re.search(fold(rx), plain)]


def language_count(text: str) -> int:
    plain = fold(text).lower()
    return sum(bool(re.search(fold(rx), plain)) for rx in LANG_WORDS.values())


def scale_hits(truth: dict[str, float], vals: list[float], text: str) -> set[str]:
    """Nutrients explained by ONE serving size: for some size s every one of >= 3 OFF values equals a
    number in the text scaled by 100/s (text per serving, OFF per 100) or s/100 (the reverse).
    One match proves nothing (a panel has ~30 numbers); three on the same scale factor do."""
    sizes = {float(m.replace(",", ".")) for m in SERVING.findall(text)} - {100.0}
    best: set[str] = set()
    for size in (s for s in sizes if 5 <= s <= 600):
        for scale in (100 / size, size / 100):
            hit = {
                k
                for k, want in truth.items()
                if want and any(abs(v * scale - want) <= max(0.05, 0.015 * want) for v in vals)
            }
            if len(hit) >= 3 and len(hit) > len(best):
                best = hit
    return best


def serving_only(basis: list[str]) -> bool:
    serving = {
        "per serving",
        "per portion",
        "par portion",
        "pro Portion",
        "por porção",
        "por porción",
    }
    return bool(serving & set(basis)) and "100 g" not in basis and "100 ml" not in basis


def suggest(
    row: dict, near_misses: int, vals: list[float], text: str, basis: list[str], scaled: set[str]
) -> str:
    key, want = row["nutrient"], row["off"]
    langs = language_count(text)
    if want:
        if key in scaled or serving_only(basis):
            return "basis_mismatch"
        near = closest(want, vals, 1)
        if near and abs(near[0] - want) < (5 if key == "energy_kcal" else 0.5):
            return "rounding_lt05"
        if near and abs(near[0] - want) <= 0.15 * want and near_misses >= 2:
            return "revision"
    return "multilang_blob" if langs >= 4 else "misread"


CAUSES = ["basis_mismatch", "rounding_lt05", "revision", "multilang_blob", "misread"]
# the model read what is on the pack; OFF (or its basis) differs. misread / multilang_blob did not.
READ_OK = {"basis_mismatch", "rounding_lt05", "revision"}
TRIAGE_MD = ROOT / "reports" / "triage_model_misses.md"


def build_rows(score_rows: list[dict], cache: Path) -> list[dict]:
    """One dict per `model` miss of a score run, with its suggested_cause."""
    out_rows = []
    for r in score_rows:
        if r["status"] != 200:
            continue
        text = strip_regions(json.loads((cache / f"{r['barcode']}.json").read_text())["text"])
        vals = numbers(text)
        basis = basis_indicators(text)
        scaled = scale_hits({k: f["want"] for k, f in r["fields"].items()}, vals, text)
        near = sum(
            1
            for k, f in r["fields"].items()
            if f["want"]
            and (c := closest(f["want"], vals, 1))
            and tol(k) < abs(c[0] - f["want"]) <= 0.15 * f["want"]
        )
        for key, f in r["fields"].items():
            if f["category"] != "model":
                continue
            row = {
                "barcode": r["barcode"],
                "image": f"data/off/{r['barcode']}.jpg",
                "lang": r["lang"],
                "nutrient": key,
                "off": f["want"],
                "closest": closest(f["want"], vals),
                "basis": basis,
                "outcome": f["outcome"],
                "got": f["got"],
            }
            row["suggested"] = suggest(row, near, vals, text, basis, scaled)
            out_rows.append(row)
    return out_rows


def load_confirmed(path: Path = TRIAGE_MD) -> dict[tuple[str, str], str]:
    """`confirmed_cause` values a human filled in, keyed by (barcode, nutrient). Blank cells skipped."""
    found: dict[tuple[str, str], str] = {}
    if not path.exists():
        return found
    for ln in path.read_text().splitlines():
        cells = [c.strip() for c in ln.strip().strip("|").split("|")]
        if len(cells) == 9 and cells[0].startswith("data/off/") and cells[8]:
            found[(Path(cells[0]).stem, cells[2])] = cells[8]
    return found


def cause_of(row: dict, confirmed: dict[tuple[str, str], str]) -> tuple[str, str]:
    """(cause, source): confirmed_cause when it names a known cause, else suggested_cause."""
    c = confirmed.get((row["barcode"], row["nutrient"]), "").lower().replace(" ", "_")
    return (c, "confirmed") if c in CAUSES else (row["suggested"], "suggested")


def read_after_triage(
    score_rows: list[dict], cache: Path, confirmed: dict[tuple[str, str], str]
) -> dict:
    """Model read accuracy once triaged `model` misses are counted by their cause.

    A field counts as read if the OFF value is in the OCR text (the plain model_read_accuracy) or it
    is a `model` miss whose cause is basis_mismatch / rounding_lt05 / revision (the model read the
    pack correctly and OFF or its basis differs). confirmed_cause wins over suggested_cause.
    """
    ok = [r for r in score_rows if r["status"] == 200]
    total = sum(len(r["fields"]) for r in ok)
    reads = sum(f["model_read_accuracy"] for r in ok for f in r["fields"].values())
    rows = build_rows(score_rows, cache)
    causes = [cause_of(x, confirmed) for x in rows]
    reclassified = sum(c in READ_OK for c, _ in causes)
    return {
        "read_before": round(reads / total, 3) if total else None,
        "read_after": round((reads + reclassified) / total, 3) if total else None,
        "model_misses": len(rows),
        "reclassified_as_read": reclassified,
        "confirmed": sum(src == "confirmed" for _, src in causes),
        "suggested": sum(src == "suggested" for _, src in causes),
        "by_cause": {c: sum(cc == c for cc, _ in causes) for c in CAUSES},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--score", type=Path, default=ROOT / "reports" / "score_official.json")
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "off" / "ocr_cache")
    ap.add_argument("--out", type=Path, default=TRIAGE_MD)
    args = ap.parse_args()

    confirmed = load_confirmed(args.out)  # a human's confirmed_cause survives regeneration
    out_rows = build_rows(json.loads(args.score.read_text())["rows"], args.cache)
    counts = Counter(x["suggested"] for x in out_rows)
    kept = sum((x["barcode"], x["nutrient"]) in confirmed for x in out_rows)
    md = [
        '# Triage: "model" misses',
        "",
        (
            f"{len(out_rows)} fields where the OFF value is not on that nutrient's row of the OCR text "
            f"(source: `{args.score.relative_to(ROOT)}`). `suggested_cause` is a heuristic from the "
            "script's docstring; fill `confirmed_cause` (one of the five causes) after looking at the "
            "photo. Re-running the script keeps what you filled in. `scripts/score.py` uses "
            "`confirmed_cause` when present and `suggested_cause` otherwise."
        ),
        "",
        "| suggested_cause | count |",
        "|---|---|",
        *[f"| {c} | {counts.get(c, 0)} |" for c in CAUSES],
        f"| **total** | {len(out_rows)} |",
        "",
        (
            "`closest 3` are the three numbers in the OCR text nearest the OFF value (HTML tags and "
            "`%` values excluded). `got` is what the parser produced ('-' = missing). An OFF value of 0 "
            "means the model dropped that nutrient's row or never read a zero for it."
        ),
        "",
        "| image | lang | nutrient | OFF | closest 3 | basis indicators | got | suggested_cause | confirmed_cause |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for x in sorted(
        out_rows, key=lambda x: (CAUSES.index(x["suggested"]), x["image"], x["nutrient"])
    ):
        closest3 = ", ".join(f"{v:g}" for v in x["closest"]) or "-"
        got = "-" if x["got"] is None else f"{x['got']:g}"
        md.append(
            f"| {x['image']} | {x['lang']} | {x['nutrient']} | {x['off']:g} | {closest3} | "
            f"{', '.join(x['basis']) or '-'} | {got} | {x['suggested']} | "
            f"{confirmed.get((x['barcode'], x['nutrient']), '')} |"
        )
    args.out.write_text("\n".join(md) + "\n")
    print(
        f"{len(out_rows)} misses ({kept} confirmed kept): "
        + ", ".join(f"{c} {counts.get(c, 0)}" for c in CAUSES)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
