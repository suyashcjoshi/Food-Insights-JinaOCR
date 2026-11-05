"""Side-by-side of two prompt runs on the same images: error categories, read accuracy, loops,
tokens, latency, cost. Reads reports/score_official.json and reports/score_table.json;
writes reports/prompt_comparison.md.

    uv run python scripts/compare_prompts.py [--a score_official.json --b score_table.json]

The choice between prompts is NOT taken on total correct fields: those mix what the prompt controls
(does the model put the number in the text) with what the parser controls (can we find it).
Model-side rows decide; parser-side category counts are shown because a prompt whose output shape
keeps costing the parser fields is a tie-break, not a verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
PARSER_SIDE = ["shift", "column", "synonym", "unit", "comma"]
HEAD = ["| | official | table | better |", "|---|---|---|---|"]


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x:.1%}"


class Table:
    """Rows of (label, shown a, shown b, winner). `tie` is the gap treated as noise."""

    def __init__(self) -> None:
        self.rows: list[str] = []

    def add(self, label, shown_a, shown_b, a=None, b=None, *, low_is_good=False, tie=0.0) -> None:
        if a is None or b is None or abs(a - b) <= tie:
            winner = "="
        else:
            winner = "official" if (a < b) == low_is_good else "table"
        self.rows.append(f"| {label} | {shown_a} | {shown_b} | {winner} |")

    def render(self) -> list[str]:
        return [*HEAD, *self.rows]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, default=REPORTS / "score_official.json")
    ap.add_argument("--b", type=Path, default=REPORTS / "score_table.json")
    ap.add_argument("--out", type=Path, default=REPORTS / "prompt_comparison.md")
    args = ap.parse_args()

    A, B = (json.loads(p.read_text()) for p in (args.a, args.b))
    sa, sb = A["summary"], B["summary"]
    ra = {r["barcode"]: r for r in A["rows"] if r["status"] == 200}
    rb = {r["barcode"]: r for r in B["rows"] if r["status"] == 200}
    common = sorted(set(ra) & set(rb))

    only_a = only_b = fields = (
        0  # paired: the OFF value is in one prompt's text but not the other's
    )
    for bc in common:
        for k, fa in ra[bc]["fields"].items():
            x, y = fa["model_read_accuracy"], rb[bc]["fields"][k]["model_read_accuracy"]
            fields += 1
            only_a += x and not y
            only_b += y and not x

    ca, cb = sa["categories"], sb["categories"]
    rta, rtb = sa["read_after_triage"], sb["read_after_triage"]

    model = Table()
    model.add("Model read accuracy (OFF value is in the text)", pct(sa["model_read_accuracy"]), pct(sb["model_read_accuracy"]),
              sa["model_read_accuracy"], sb["model_read_accuracy"], tie=0.01)  # fmt: skip
    model.add("Read accuracy after triage", pct(rta["read_after"]), pct(rtb["read_after"]),
              rta["read_after"], rtb["read_after"], tie=0.01)  # fmt: skip
    model.add("`model` misses (value not in the text)", ca["model"], cb["model"], ca["model"], cb["model"], low_is_good=True, tie=2)  # fmt: skip
    model.add("`truth_disagreement` (panel slightly off OFF)", ca["truth_disagreement"], cb["truth_disagreement"],
              ca["truth_disagreement"], cb["truth_disagreement"], low_is_good=True, tie=2)  # fmt: skip
    model.add(
        "Looped outputs", sa["looped"], sb["looped"], sa["looped"], sb["looped"], low_is_good=True
    )
    model.add("Outputs with `<table>`", sa["table_outputs"], sb["table_outputs"])

    speed = Table()
    for label, key, tie in (
        ("Prompt tokens", "tokens_in", 20),
        ("Completion tokens", "tokens_out", 30),
        ("Latency ms", "ms", 250),
    ):
        speed.add(f"{label} p50 / p95", f"{sa[key]['p50']} / {sa[key]['p95']}", f"{sb[key]['p50']} / {sb[key]['p95']}",
                  sa[key]["p50"], sb[key]["p50"], low_is_good=True, tie=tie)  # fmt: skip
    speed.add("Cost for the run (USD)", f"{sa['cost_est_total']:.4f}", f"{sb['cost_est_total']:.4f}",
              sa["cost_est_total"], sb["cost_est_total"], low_is_good=True, tie=0.002)  # fmt: skip

    parser = Table()
    for c in PARSER_SIDE:
        parser.add(f"`{c}`", ca[c], cb[c], ca[c], cb[c], low_is_good=True, tie=1)
    pa, pb = sum(ca[c] for c in PARSER_SIDE), sum(cb[c] for c in PARSER_SIDE)
    parser.add("**parser-side total**", pa, pb, pa, pb, low_is_good=True, tie=3)

    oa, ob = sa["overall"], sb["overall"]
    ref = Table()
    ref.add("Fields correct", f"{oa['correct']}/{oa['fields']} ({pct(oa['field_accuracy'])})",
            f"{ob['correct']}/{ob['fields']} ({pct(ob['field_accuracy'])})", oa["correct"], ob["correct"], tie=5)  # fmt: skip
    ref.add("Carbs correct", pct(oa["carbs_accuracy"]), pct(ob["carbs_accuracy"]), oa["carbs_accuracy"], ob["carbs_accuracy"], tie=0.03)  # fmt: skip
    ref.add("Images verified / accuracy among them", f"{sa['verified']['images']} / {pct(sa['verified']['field_accuracy'])}",
            f"{sb['verified']['images']} / {pct(sb['verified']['field_accuracy'])}")  # fmt: skip

    intro = (
        f"Same {len(common)} OFF images, temperature 0, same parser. `official` = "
        '"Convert the document to markdown."; `table` = "Convert the document to markdown. '
        'Render nutrition tables as HTML tables."'
    )
    paired = (
        f"Paired over {fields} fields: the OFF value is in the `official` text only for "
        f"**{only_a}** fields and in the `table` text only for **{only_b}**."
    )
    noise = (
        '"better" is "=" when the gap is inside the noise for 50 images (read accuracy 1 point, '
        "model misses 2 fields, tokens 20 / 30, latency 250 ms, cost $0.002, parser-side total 3)."
    )
    parser_note = (
        "Fields lost to the parser, by cause. Fixable in `app/parse.py`; they say nothing about the "
        "prompt unless one output shape keeps producing more of them."
    )
    out = [
        "# Prompt comparison: official vs table", "", intro, "",
        "## Model side (what the prompt controls)", "", *model.render(), "", paired, "",
        "## Cost and speed", "", *speed.render(), "",
        "## Parser side (what code can fix)", "", parser_note, "", *parser.render(), "",
        "## For reference only (not a decision criterion)", "", *ref.render(), "", noise,
    ]  # fmt: skip
    args.out.write_text("\n".join(out) + "\n")
    print(
        f"official vs table: read {pct(sa['model_read_accuracy'])} vs {pct(sb['model_read_accuracy'])}, "
        f"model misses {ca['model']} vs {cb['model']}, loops {sa['looped']} vs {sb['looped']}, "
        f"paired reads {only_a} vs {only_b} -> {args.out.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
