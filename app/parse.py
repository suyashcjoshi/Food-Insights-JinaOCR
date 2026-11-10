"""Nutrient parser for jina-ocr-v1 Markdown.

Only the Nutrition Facts panel becomes fields. Ingredients, allergens and claims are returned as
`unverified_text` and never parsed (the model invents text where the frame cuts the label off).

Approach: normalise Markdown / HTML-table output to lines (one table row per line), then scan each
line for nutrient labels. A value is the first number after a label and before the next label, with
the unit either after it (`27g`) or before it (`g 12`, German tables). That one rule covers
one-line-per-nutrient panels, table rows, glued single-line blobs (`Lípidos48 g- de las cuales ...`)
and prose lines (`エネルギー43kcal、たんぱく質4.1g`). Gram/mg values must carry a unit; a bare number
is never accepted (it is usually a calories or %DV column). Labels: EN/ES/DE/FR/IT/PT/JA.

Labels are matched case- and accent-insensitively (`fold`). Decimal commas are decimals (`1,7` is
1.7); nutrient values never use a thousands separator. When a row has several value columns the
one under the `100 g` / `100 ml` header wins (`ParseResult.column`, `.basis`). `parse_suspect`
flags a panel whose numbers contradict each other (kcal vs 4C+4P+9F, sugars > carbs, saturates >
fat); `verified` requires it to be clear.

Column choice: the `100 g` / `100 ml` header fixes the value column. A merged row of k labels with W
value columns arrives as k*W stacked values (`7,0 g<br>1,3 g | 2,8 g<br>0,5 g`), read column-major.
A header whose cell order contradicts the data's scale (250 ml values 2.5x the 100 ml ones) is
swapped (`column_swapped`).

Merged label rows (`Fat of which saturates | 30.9`) make the model drop a value and shift every row
below it. `_align` fixes this for EU-ordered panels: it lines the labels up with the values in
order, tries every way of leaving out the surplus labels (or trailing unlabelled values), and keeps
the assignment that satisfies sat <= fat, sugars <= carbs and the Atwater check.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from itertools import combinations
from statistics import median, multimode

# --- constants: units, labels, patterns, thresholds ----------------------------------------

# target unit of each key: kcal, g, mg or mcg
UNITS = {
    "energy_kcal": "kcal",
    "fat_g": "g",
    "saturated_fat_g": "g",
    "trans_fat_g": "g",
    "cholesterol_mg": "mg",
    "sodium_mg": "mg",
    "carbohydrates_g": "g",
    "fiber_g": "g",
    "sugars_g": "g",
    "added_sugars_g": "g",
    "protein_g": "g",
    "salt_g": "g",
    "vitamin_d_mcg": "mcg",
    "calcium_mg": "mg",
    "iron_mg": "mg",
    "potassium_mg": "mg",
    "vitamin_a_mcg": "mcg",
}

# Label synonyms as regex alternations. Order matters: a key listed first wins where labels overlap
# (saturated fat before fat). Matched as whole words, case-insensitively.
LABELS: dict[str, str] = {
    "energy_kcal": (
        r"energy|energ[ií]a|energie|[eé]nergie|valor energ\w+tico|valeurs? [eé]nerg\w+tiques?|"
        r"brennwert|valor[ei] energ\w+tic\w+|valori energ\w+tici|"
        r"calories(?!\s*from)|calorias|calorie|熱量|エネルギー"
    ),
    "saturated_fat_g": (
        r"saturated fat|saturates|saturated|acides gras satur\w+|gras satur\w+|satur\w+|"
        r"ges\w+ttigte fetts\w+ure\w*|ges\w+ttigte|[aá]cidos grasos saturados|"
        r"grasas saturadas|gorduras? satur\w+|l[ií]pidos satur\w+|saturadas|saturados|"
        r"grassi saturi|acidi grassi saturi|saturi|飽和脂肪酸|飽和脂肪"
    ),
    "trans_fat_g": r"trans fat|trans",
    "fat_g": (
        r"total fat|fat|lipides|graisses?|mati\w+res? grasses?|fett|grasas?|grassi|"
        r"gorduras?|l[ií]pidos|lipidi|脂質"
    ),
    "cholesterol_mg": r"cholesterol|cholest\w+rol|colesterol",
    "sodium_mg": r"sodium|sodio|natrium|ナトリウム",
    "salt_g": r"salt|sel|salz|sal|sale|食塩相当量",
    "carbohydrates_g": (
        r"total carbohydrates?|carbohydrates?|carbs|hidratos? (?:de )?carbono|hidratos|carbohidratos|"
        r"kohlenhydrate|gl[ua]cides|gl[uú]cidos|carboidrati|炭水化物"
    ),
    "fiber_g": (
        r"dietary fib(?:er|re)s?|fib(?:er|re)s?|ballaststoffe|fibras?|"
        r"fibre alimentari|fibres alimentaires|食物繊維"
    ),
    "sugars_g": (
        r"total sugars|sugars|sugar|sucres|zucker|az[uú]cares|a[cç][uú]cares|zuccheri|糖質|糖類"
    ),
    "protein_g": r"proteins?|prot\w*?[iï]nes?|eiwei\w+|prote[ií]nas?|proteine|たんぱく質|タンパク質",
    "vitamin_d_mcg": r"vitamin d|vitamine d|vitamina d",
    "calcium_mg": r"calcium|calcio|c\w+lcio",
    "iron_mg": r"iron|fer|eisen|hierro|ferro",
    "potassium_mg": r"potassium|kalium|potasio|pot\w+ssio",
    "vitamin_a_mcg": r"vitamin a|vitamine a|vitamina a",
}
LABELS = {k: v.replace(r"\w", r"[^\W\d_]") for k, v in LABELS.items()}
# A label is a whole word, or (for glued OCR text) an Uppercase label glued onto a lowercase/digit.
LABEL_RE = re.compile(
    r"(?:(?<![A-Za-zÀ-ɏ])|(?-i:(?<=[a-z\d])(?=[A-ZÀ-Þ])))"
    + "(?:"
    + "|".join(f"(?P<{key}>{alt})" for key, alt in LABELS.items())
    + r")(?![A-Za-zÀ-ɏ])",
    re.IGNORECASE,
)
UNIT = r"mcg|µg|μg|ug|mg|kcal|kj|g"
G = r"(?:mcg|µg|μg|ug|mg|g)"  # gram-type units; `g3,5` (glued to the number) must not follow a letter
TOKEN_RE = re.compile(
    rf"(?:(?P<u1>[-–]?\s*(?:(?<![A-Za-z]){G}(?=\d)|{G}(?=\s)|kcal|kj))\s*)?(?P<num>\d+(?:[.,]\d+)?)"
    rf"(?:\s*(?P<u2>{UNIT})(?:(?![a-z])|(?=(?:de|di|dos|dont|davon|of)\b))|(?!\d)(?!\s*%))",
    re.IGNORECASE,
)
# `Fat (g) 31.8 4.8`: the unit sits in the label and the values are bare
LABEL_UNIT_RE = re.compile(r"^\s*[(\[]\s*(?P<unit>mcg|µg|μg|ug|mg|g)\s*[)\]]\s*:?", re.IGNORECASE)
ADDED_SUGARS_RES = (
    re.compile(
        r"incl(?:udes|\.)?\s*(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>g|mg)?\s*added sugars?",
        re.IGNORECASE,
    ),
    re.compile(r"added sugars?\D{0,15}(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>g|mg)?", re.IGNORECASE),
    re.compile(r"sucres? ajout\w+\D{0,15}(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>g)?", re.IGNORECASE),
)
TO_GRAMS = {"g": 1.0, "mg": 1e-3, "mcg": 1e-6, "µg": 1e-6, "μg": 1e-6, "ug": 1e-6}
KCAL_PER_KJ = 4.184
MAX_KCAL = 2500  # a larger "calorie" number is glued digits or a different column
UNVERIFIED_START = re.compile(
    r"^\W*(?:ingredients?|ingr[eé]dients?|zutaten|ingredientes|ingredienti|allergens?|"
    r"contains|may contain|contient|peut contenir|enth[aä]lt|原材料名?|アレルゲン|アレルギー)",
    re.IGNORECASE,
)
PER_100 = re.compile(
    r"(?:per|pour|pro|por|para|f[uü]r)\s*100\s*(?:g|ml)|(?:^|\n)\s*(?:g|ml)\s+100\b|"
    r"\[100\s*(?:g|ml)|100\s*(?:g|ml)\s*(?:当たり|あたり)",
    re.IGNORECASE,
)
PER_SERVING = re.compile(
    r"serving|portion|por[cç][aã]o|ra[cç][aã]o|raci[oó]n|cup|tasse", re.IGNORECASE
)
SERVING_RE = re.compile(r"serving size\s*:?\s*(.+)$", re.IGNORECASE)
# the per-100 column header, and the value-column headers that can stand left of it
COL100_RE = re.compile(r"(?<![\d.,])100\s*(?:g|gr|ml)(?![a-z])", re.IGNORECASE)
COLUMN_HEADER_RE = re.compile(
    r"\b(?:serving|portion|porcion|porcao|racao|bar|piece|cup|tasse)\b\s*\(?\s*"
    r"(?:\d+(?:[.,]\d+)?\s*(?:g|ml)\)?)?|(?<![\d.,])\d+(?:[.,]\d+)?\s*(?:g|ml)(?![a-z])",
    re.IGNORECASE,
)
# consistency check (4C + 4P + 9F vs the printed kcal): 20 % and at least 5 kcal apart is suspect
KCAL_TOLERANCE = 0.20
KCAL_NOISE = 5.0
ROUNDING_SLACK_G = 0.05  # "sugars <= carbs" and friends tolerate rounding on the pack
ATWATER_UNKNOWN = 0.3  # alignment error when kcal or a macro is missing, so the check cannot rank
MAX_G_PER_100 = 100.5  # no nutrient exceeds 100 g per 100 g
MAX_MACROS_PER_100 = 105  # fat + carbs + protein per 100 g, with slack
# a bare kJ/kcal pair (`2252 539`): ratio of the two numbers, whatever their order
KJ_KCAL_RATIO = (3.9, 4.4)
MAX_BARE_ENERGY_DIGITS = 4  # a longer bare number is not an energy value
SCALE_TOLERANCE = 0.2  # how closely the data must follow a header's `250 ml` / `100 ml` ratio
MAX_HEADER_LINE = 60  # a wrapped label ("davon: gesättigte") is short
MAX_ALIGN_GAP = 3  # labels vs values may differ by this many before alignment gives up

# words between labels that make one run (`Fat of which saturates`, `Hidratos de carbono / Carboidrati`)
CONNECTORS = re.compile(
    r"^(?:\s|[/:,.\-]|dont|davon|of which|whereof|di cui|de los cuales|de las cuales|dos quais|das quais|"
    r"including|incl|うち|内)*$",
    re.IGNORECASE,
)
# two unit words in a row (`kJ kcal`, `(Kj/Kcal)`) are a column header, not units of the number
_UNIT_PAIR_RE = re.compile(r"\(?\b(?:kj|kcal)\b[\s/]*\b(?:kj|kcal)\b\)?", re.IGNORECASE)

# order-aware alignment: the EU panel order, and what it costs to leave a label without a value
EU_ORDER = (
    "fat_g",
    "saturated_fat_g",
    "carbohydrates_g",
    "sugars_g",
    "fiber_g",
    "protein_g",
    "salt_g",
)
# the "of which" rows are what merged labels usually lose, so leaving them out is free
SKIP_COST = {"saturated_fat_g": 0, "sugars_g": 0, "fiber_g": 0}
VALUE_ONLY_NOISE = re.compile(r"\b(?:mcg|µg|mg|kcal|kj|g|lt|gt)\b|&lt;|&gt;", re.IGNORECASE)


@dataclass
class ParseResult:
    nutrients: dict[str, float] = field(default_factory=dict)
    energy_kj: float | None = None
    serving_text: str | None = None
    per: str = "serving"
    basis: str = "unknown"  # 100g | 100ml | serving | unknown
    column: int | None = None  # index of the 100 g / 100 ml value column, None if no such header
    width: int | None = None  # value columns named in the header
    col_sizes: list[float | None] = field(default_factory=list)  # size of each, None: no size
    column_swapped: bool = False  # header order contradicted the data's scale
    unverified_text: str = ""
    edge_cutoff_suspected: bool = False
    energy_from_kj: bool = False  # kcal was derived from kJ; an explicit kcal row replaces it
    suspect_reasons: list[str] = field(default_factory=list)
    aligned: bool = False  # values were re-assigned by order-aware alignment
    # Does the printed "carbohydrate" already include fibre? US / Canada "Total Carbohydrate": yes.
    # EU / UK "Carbohydrate" (per 100 g): no, fibre is listed separately. None: cannot tell.
    carb_includes_fibre: bool | None = None

    @property
    def panel_found(self) -> bool:
        return "carbohydrates_g" in self.nutrients or "energy_kcal" in self.nutrients

    @property
    def energy_converted(self) -> bool:
        return self.energy_from_kj and "energy_kcal" in self.nutrients

    @property
    def parse_suspect(self) -> bool:
        return bool(self.suspect_reasons)

    @property
    def flags(self) -> list[str]:
        out = ["edge_cutoff_suspected"] if self.edge_cutoff_suspected else []
        out += ["energy_converted"] if self.energy_converted else []
        out += ["no_panel"] if not self.panel_found else []
        out += ["aligned"] if self.aligned else []
        out += ["column_swapped"] if self.column_swapped else []
        return out + (["parse_suspect", *self.suspect_reasons] if self.parse_suspect else [])

    @property
    def verified(self) -> bool:
        """Panel parsed, nothing cut off, numbers consistent. Benchmark scripts only; the app does not show it."""
        return self.panel_found and not self.edge_cutoff_suspected and not self.parse_suspect


@dataclass
class _Row:
    keys: list[str]  # nutrient labels on this row, in text order (empty: a row with no label)
    toks: list[float | None]  # every value token after the labels, in grams (None: no unit)
    last_in_line: bool = True  # may carry extra unlabelled rows when tokens come glued together


# --- text helpers ------------------------------------------------------------------------------


def _to_float(s: str) -> float:
    """A comma in a nutrient value is always a decimal comma (`1,7` is 1.7)."""
    return float(s.replace(",", "."))


def fold(s: str) -> str:
    """Strip Latin accents (`énergie` -> `energie`), leave kana/kanji and `ß`/`ø` alone."""
    out = []
    for ch in s:
        if ord(ch) < 0x250:
            ch = "".join(
                c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c)
            )
        out.append(ch)
    return "".join(out)


def normalize(md: str) -> list[str]:
    """Markdown or HTML table to plain lines: one table row per line, markup removed."""
    text = md or ""

    def row(m: re.Match) -> str:
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", m.group(1), re.DOTALL | re.IGNORECASE)
        return " ".join(re.sub(r"<[^>]+>", " ", c).strip() for c in cells) + "\n"

    text = re.sub(r"<tr[^>]*>(.*?)</tr>", row, text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    lines = []
    for ln in text.splitlines():
        ln = ln.replace("|", " ").replace("*", " ").replace("#", " ").replace(" ", " ")
        ln = re.sub(r"^\s*[-:]{2,}[\s:-]*$", "", ln)  # markdown table rule rows
        ln = re.sub(r"\s+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return lines


def _convert(value: float, unit: str, key: str) -> float:
    target = UNITS[key]
    grams = value * TO_GRAMS[unit.lower().lstrip("-– ")]
    return round(grams / TO_GRAMS[target], 4)


def _cutoff(lines: list[str], raw: str) -> bool:
    if "[…]" in raw or "[...]" in raw:
        return True
    return any(ln.endswith("-") or ln.count("(") > ln.count(")") for ln in lines)


# --- energy ------------------------------------------------------------------------------------


def _energy_numbers(seg: str, col: int) -> tuple[list[float], list[float], list[float]]:
    """kcal numbers, kJ numbers and unitless numbers found in an energy segment."""
    kcals: list[float] = []
    kjs: list[float] = []
    bare: list[float] = []
    for m in TOKEN_RE.finditer(seg):
        u1, u2 = ((m.group(g) or "").lower().lstrip("-– ") for g in ("u1", "u2"))
        # `kJ2030kcal 492`: a different unit glued after the number is the next number's header
        unit = u1 if u1 and u2 and u1 != u2 else (u2 or u1)
        val = _to_float(m.group("num"))
        if unit == "kcal":
            kcals.append(val)
        elif unit == "kj":
            kjs.append(val)
        elif (
            not unit and len(m.group("num")) <= MAX_BARE_ENERGY_DIGITS and len(bare) < 2 * (col + 1)
        ):
            bare.append(val)
    return kcals, kjs, bare


def _pick_energy(
    seg: str, kcals: list[float], kjs: list[float], bare: list[float], col: int
) -> tuple[float | None, float | None]:
    """The kcal and kJ values of column `col`, deciding what unitless numbers mean."""
    kcal = kcals[col] if col < len(kcals) else None
    kj = kjs[col] if col < len(kjs) else None
    if kcal is None and kj is None and len(bare) >= 2 * (col + 1):
        pair = bare[2 * col : 2 * col + 2]
        if min(pair) > 0 and KJ_KCAL_RATIO[0] <= max(pair) / min(pair) <= KJ_KCAL_RATIO[1]:
            return min(pair), max(pair)  # a kJ/kcal pair, whichever order it is printed in
    if kcal is None and bare and col == 0:
        lower = seg.lower()
        if "kj" in lower and "kcal" not in lower and "cal" not in lower:
            kj = kj if kj is not None else bare[0]  # the text only mentions kJ
        else:
            kcal = bare[0]
    return kcal, kj


def _energy(seg: str, res: ParseResult) -> None:
    """`1890 kJ / 448 kcal`, `kJ 1360`, `Calories 150`, and unitless pairs (`2252 539`, `188/45`).

    kcal wins, kJ is stored separately and only converts (/ 4.184, flag `energy_converted`) when no
    kcal is present. A bare number is kcal unless the text only mentions kJ. Two bare numbers whose
    ratio is ~4.184 are a kJ/kcal pair whatever their order. With several columns the one under
    the 100 g / 100 ml header is read (`res.column`).
    """
    col = res.column or 0
    # two unit words in a row (`kJ kcal`, `(Kj/Kcal)`) are a column header, not units of the number
    seg = _UNIT_PAIR_RE.sub(" ", seg)
    kcal, kj = _pick_energy(seg, *_energy_numbers(seg, col), col)
    if kj is not None and res.energy_kj is None:
        res.energy_kj = kj
    value, derived = kcal, False
    if value is None and kj is not None:
        value, derived = round(kj / KCAL_PER_KJ), True
    already = "energy_kcal" in res.nutrients
    # a kcal row replaces a value that was only derived from kJ
    if (
        value is not None
        and value <= MAX_KCAL
        and (not already or (res.energy_from_kj and not derived))
    ):
        res.nutrients["energy_kcal"] = value
        res.energy_from_kj = derived


# --- one line: labels and their values ---------------------------------------------------------


def _run_end(matches: list[re.Match], ln: str, i: int) -> int:
    """Index of the last label of a run naming one nutrient in several languages
    (`Hidratos de carbono / Carboidrati`): same key, only connectors between."""
    while (
        i + 1 < len(matches)
        and matches[i + 1].lastgroup == matches[i].lastgroup
        and CONNECTORS.match(ln[matches[i].end() : matches[i + 1].start()])
    ):
        i += 1
    return i


def _token_unit(toks: list[re.Match], idx: int, label_tail: str) -> str:
    """Unit of toks[idx]: its own, else the first printed earlier in the row (`g 30.9 4.6`), else
    the one in the label (`Fat (g) 31.8`)."""

    def own(t: re.Match) -> str:
        return (t.group("u2") or t.group("u1") or "").lower().lstrip("-– ")

    unit = own(toks[idx]) or next((u for t in toks[:idx] if (u := own(t))), "")
    if not unit and (lu := LABEL_UNIT_RE.match(label_tail)):
        unit = lu.group("unit").lower()
    return unit


def _next_label_start(matches: list[re.Match], i: int, ln: str) -> int:
    """Where the text belonging to label `i` ends: the next label, or the end of the line."""
    return matches[i + 1].start() if i + 1 < len(matches) else len(ln)


def _values_of_label(
    ln: str, matches: list[re.Match], i: int
) -> tuple[list[str], list[re.Match], int]:
    """Labels sharing one value run, their value tokens, and where those tokens start in `ln`.

    `Fat of which saturates | 30.9`: labels with no value between them form a chain, and the values
    after the last one are theirs.
    """
    first = matches[i]
    toks = list(TOKEN_RE.finditer(ln[first.end() : _next_label_start(matches, i, ln)]))
    offset = first.end()
    chain = [first.lastgroup]
    last = _run_end(matches, ln, i)
    while (
        not toks
        and last + 1 < len(matches)
        and matches[last + 1].lastgroup != "energy_kcal"
        and CONNECTORS.match(ln[matches[last].end() : matches[last + 1].start()])
    ):
        last = _run_end(matches, ln, last + 1)
        if matches[last].lastgroup not in chain:
            chain.append(matches[last].lastgroup)
        offset = matches[last].end()
        toks = list(TOKEN_RE.finditer(ln[offset : _next_label_start(matches, last, ln)]))
    return chain, toks, offset


def _pick_columns(chain: list[str], toks: list[re.Match], res: ParseResult) -> dict[str, int]:
    """Which token index belongs to which label of the chain ({} when the column has no value)."""
    col = res.column or 0
    k = len(chain)
    if k > 1 and res.width and len(toks) == k * res.width:
        return {name: col * k + j for j, name in enumerate(chain)}  # stacked cells: column-major
    if len(toks) > col:
        return {chain[0]: col}  # a merged row with one value per column: the first label owns it
    return {}  # no value in the per-100 column: never fall back to another one


def _scan_line(ln: str, res: ParseResult) -> None:
    """Read every labelled value on one (folded) line into `res.nutrients`."""
    matches = list(LABEL_RE.finditer(ln))
    claimed: set[int] = set()  # start offsets of tokens already given to a label
    for i, m in enumerate(matches):
        if m.lastgroup == "energy_kcal":
            _energy(ln[m.end() : _next_label_start(matches, i, ln)], res)
            continue
        chain, toks, offset = _values_of_label(ln, matches, i)
        for name, idx in _pick_columns(chain, toks, res).items():
            if name in res.nutrients or (pos := offset + toks[idx].start()) in claimed:
                continue
            unit = _token_unit(toks, idx, ln[m.end() :])
            if unit in TO_GRAMS:  # gram/mg values always print a unit; skip a bare number
                res.nutrients[name] = _convert(_to_float(toks[idx].group("num")), unit, name)
                claimed.add(pos)


def _ends_with_label(ln: str) -> bool:
    """A line with no digits whose last words are a label (`davon: gesättigte`): values follow."""
    if re.search(r"\d", ln) or len(ln) > MAX_HEADER_LINE:
        return False
    last = None
    for m in LABEL_RE.finditer(ln):
        last = m
    return last is not None and len(ln) - last.end() <= 3


# --- the value column (the `100 g` header) -----------------------------------------------------


def _is_ri_column(text: str, start: int) -> bool:
    """A `%RI` / `% daily value` column sits right after a percent sign, not a value column."""
    return "%" in text[max(0, start - 12) : start]


def _header_columns(ln: str, hm: re.Match) -> tuple[list[float | None], int]:
    """Sizes of the value columns named in the header and the index of the per-100 one."""
    head = ln
    for lm in LABEL_RE.finditer(ln):
        if lm.start() > hm.start():
            head = ln[: lm.start()]  # a glued blob continues into the rows: the header ends here
            break
    sizes: list[float | None] = []
    idx100 = None
    for m in COLUMN_HEADER_RE.finditer(head):
        if _is_ri_column(head, m.start()):
            continue
        num = re.search(r"\d+(?:[.,]\d+)?", m.group())
        sizes.append(_to_float(num.group()) if num else None)
        if idx100 is None and COL100_RE.search(m.group()):
            idx100 = len(sizes) - 1
    if idx100 is None:  # the header was cut before its own 100 marker: count the columns left of it
        idx100 = sum(
            1
            for m in COLUMN_HEADER_RE.finditer(ln[: hm.start()])
            if not _is_ri_column(ln, m.start())
        )
        sizes = [*sizes, *[None] * (idx100 + 1 - len(sizes))][: max(len(sizes), idx100 + 1)]
        sizes[idx100] = 100.0
    return sizes, idx100


def _find_column(ln: str, res: ParseResult, forced: int | None = None) -> None:
    """The first `100 g` / `100 ml` header fixes which value column to read in every row.

    Also records how many value columns the header names (`width`) and the size of each, which the
    stacked-cell rule and the scale check need.
    """
    hm = COL100_RE.search(ln)
    if hm is None or res.column is not None:
        return
    sizes, idx100 = _header_columns(ln, hm)
    res.column = forced if forced is not None else idx100
    res.col_sizes = sizes
    res.width = len(sizes)
    res.basis = "100ml" if "ml" in hm.group().lower() else "100g"


def _scale_swap(rows: list[_Row], res: ParseResult) -> int | None:
    """Column to read instead of the header's 100 g one, if the numbers prove the header is misordered.

    Headers `250 ml | 100 ml` over values `10.6 | 27` (27 / 10.6 = 2.5): the smaller numbers are the
    100 ml ones. Needs one clean row with both values; a consistent header returns None.
    """
    sizes, c = res.col_sizes, res.column
    if c is None or c >= len(sizes) or len(sizes) < 2 or sizes[c] != 100:
        return None
    for j, size in enumerate(sizes):
        if j == c or not size or size == 100:
            continue
        ratios = [
            r.toks[j] / r.toks[c]
            for r in rows
            if len(r.keys) == 1 and len(r.toks) == len(sizes) and r.toks[c] and r.toks[j]
        ]
        if not ratios:
            continue
        median_ratio, expected = median(ratios), size / 100
        if abs(median_ratio / expected - 1) <= SCALE_TOLERANCE:
            return None  # header and data agree
        if abs(median_ratio * expected - 1) <= SCALE_TOLERANCE:
            return j
    return None


# --- order-aware alignment ---------------------------------------------------------------------


def _gram_tokens(seg: str) -> list[float | None]:
    lu = LABEL_UNIT_RE.match(seg)
    unit = lu.group("unit").lower() if lu else None
    out: list[float | None] = []
    for t in TOKEN_RE.finditer(seg):
        u = (t.group("u2") or t.group("u1") or "").lower().lstrip("-– ")
        if u in TO_GRAMS:
            unit = u
        use = u or unit
        out.append(_to_float(t.group("num")) * TO_GRAMS[use] if use in TO_GRAMS else None)
    return out


def _label_runs(ln: str, matches: list[re.Match]) -> list[tuple[int, int]]:
    """(first, last) match indexes of labels that share one row: no value sits between them."""
    runs = []
    i = 0
    while i < len(matches):
        j = i
        while j + 1 < len(matches) and not TOKEN_RE.search(
            ln[matches[j].end() : matches[j + 1].start()]
        ):
            j += 1
        runs.append((i, j))
        i = j + 1
    return runs


def _collect_rows(ln: str, rows: list[_Row]) -> None:
    """Add the label rows of one (folded) line: labels with no value between them share a row."""
    matches = list(LABEL_RE.finditer(ln))
    if not matches:
        label_free = not re.search(r"[^\W\d_]", VALUE_ONLY_NOISE.sub("", ln))
        if rows and label_free and (toks := _gram_tokens(ln)):
            rows.append(_Row([], toks))  # `g 0.107 0.016 0%`: a row whose label cell is empty
        return
    made: list[_Row] = []
    for first, last in _label_runs(ln, matches):
        keys: list[str] = []
        for k in range(first, last + 1):
            key = matches[k].lastgroup
            if key != "energy_kcal" and key not in keys:
                keys.append(key)
        if keys:
            end = _next_label_start(matches, last, ln)
            made.append(_Row(keys, _gram_tokens(ln[matches[last].end() : end]), last_in_line=False))
    if made:
        made[-1].last_in_line = True
        rows.extend(made)


def _row_values(r: _Row, column: int, width: int, header_width: int | None) -> list[float]:
    """The value(s) of one row in the chosen column. A glued row can carry extra unlabelled rows."""
    k = len(r.keys)
    if k > 1 and header_width and len(r.toks) == k * header_width:  # stacked cells, column-major
        return [v for v in r.toks[column * k : (column + 1) * k] if v is not None]
    chunks = [r.toks[i : i + width] for i in range(0, len(r.toks), width)]
    values = []
    if chunks and len(chunks[0]) > column and chunks[0][column] is not None:
        values.append(chunks[0][column])
    if r.keys and r.last_in_line and len(r.toks) % width == 0:
        values += [c[column] for c in chunks[1:] if len(c) > column and c[column] is not None]
    return values


def _flatten(
    rows: list[_Row], column: int, header_width: int | None = None
) -> tuple[list[str], list[float]] | None:
    """Ordered keys and ordered values of the table, or None if it is not an EU-ordered panel."""
    counts = [len(r.toks) for r in rows if r.keys and r.toks]
    if not counts:
        return None
    width = min(multimode(counts))  # value columns per row
    keys: list[str] = []
    values: list[float] = []
    for r in rows:
        if r.keys and all(k in keys for k in r.keys):
            continue  # the same nutrient named again (a footnote)
        values += _row_values(r, column, width, header_width)
        keys += [k for k in r.keys if k not in keys]
    if len(keys) < 3 or any(k not in EU_ORDER for k in keys):
        return None
    positions = [EU_ORDER.index(k) for k in keys]
    return (keys, values) if positions == sorted(set(positions)) else None


def _kcal_disagrees(kcal: float, carbs: float, protein: float, fat: float) -> tuple[bool, float]:
    """Does the printed kcal differ from 4C + 4P + 9F by more than noise and tolerance? Plus the gap."""
    estimate = 4 * carbs + 4 * protein + 9 * fat
    diff = abs(kcal - estimate)
    return diff > KCAL_NOISE and diff > KCAL_TOLERANCE * estimate, diff / max(estimate, 1.0)


def _violations(a: dict[str, float], res: ParseResult) -> tuple[int, float]:
    """Number of broken rules and the Atwater error (`ATWATER_UNKNOWN` when it cannot be evaluated)."""
    sat, fat, sug, carb, fib = (
        a.get(k) for k in ("saturated_fat_g", "fat_g", "sugars_g", "carbohydrates_g", "fiber_g")
    )
    bad = 0
    bad += sat is not None and fat is not None and sat > fat + ROUNDING_SLACK_G
    bad += sug is not None and carb is not None and sug > carb + ROUNDING_SLACK_G
    bad += fib is not None and carb is not None and fib > carb + ROUNDING_SLACK_G
    if res.basis.startswith("100"):
        bad += any(v > MAX_G_PER_100 for v in a.values())
        macros = [a.get(k) for k in ("fat_g", "carbohydrates_g", "protein_g")]
        bad += sum(m for m in macros if m is not None) > MAX_MACROS_PER_100
    kcal, protein = res.nutrients.get("energy_kcal"), a.get("protein_g")
    if None in (kcal, fat, carb, protein):
        return bad, ATWATER_UNKNOWN
    disagrees, gap = _kcal_disagrees(kcal, carb, protein, fat)
    return bad + disagrees, gap


def _candidates(keys: list[str], values: list[float]) -> list[tuple[tuple[int, ...], dict, int]]:
    """Every way to pair labels with values: (skipped indexes, {label: value}, skip cost)."""
    n, m = len(keys), len(values)
    out = []
    if n >= m:  # a value was lost: leave some labels without one
        for skip in combinations(range(n), n - m):
            kept = [k for i, k in enumerate(keys) if i not in skip]
            cost = sum(SKIP_COST.get(keys[i], 1) for i in skip)
            out.append((skip, dict(zip(kept, values, strict=True)), cost))
    else:  # a spare value: an unlabelled row (cheap if trailing, as in a glued last row)
        for skip in combinations(range(m), m - n):
            kept = [v for i, v in enumerate(values) if i not in skip]
            cost = sum(0 if i >= n else 1 for i in skip)
            out.append((skip, dict(zip(keys, kept, strict=True)), cost))
    return out


def _align(rows: list[_Row], res: ParseResult) -> None:
    """Re-assign values to labels by row order when the rules say a value was dropped or spare."""
    flat = _flatten(rows, res.column or 0, res.width)
    if flat is None:
        return
    keys, values = flat
    if len(values) < 2 or abs(len(keys) - len(values)) > MAX_ALIGN_GAP:
        return
    best: tuple | None = None
    for skip, assign, cost in _candidates(keys, values):
        broken, err = _violations(assign, res)
        # later labels are the casualties of merged rows, so prefer leaving those out
        rank = (broken, cost, round(err, 2), tuple(-i for i in sorted(skip, reverse=True)))
        if best is None or rank < best[0]:
            best = (rank, assign)
    if best is None or best[0][0] != 0:
        return  # never force an assignment that breaks the rules
    assign = {k: round(v, 4) for k, v in best[1].items()}
    before = {k: res.nutrients[k] for k in keys if k in res.nutrients}
    res.nutrients = {**{k: v for k, v in res.nutrients.items() if k not in keys}, **assign}
    res.aligned = before != assign


# --- unverified text, consistency and the entry point ------------------------------------------


def _ingredient_like_tail(md: str) -> str:
    """Ingredient or allergen text after the panel, for when the model garbled its headings.

    The usual rule (`UNVERIFIED_START`) looks for an INGREDIENTS / CONTAINS heading. A model that
    reads a small photo can return `IMPORTANT:` for INGREDIENTS and `DATING` for CONTAINS, and then
    nothing matches. So: take the text after the panel (after the last `</table>`, or after the last
    row that has a nutrient label and a number) and keep only the paragraphs that look like a list:
    at least three commas and a recognised allergen word. Footnotes, addresses and reference-intake
    lines do not qualify, so a panel-only photo still has no unverified text.
    """
    from app.allergens import find_allergens  # allergens imports this module: import late

    end = md.lower().rfind("</table>")
    if end >= 0:
        tail = md[end + len("</table>") :]
    else:
        lines = md.splitlines()
        last = -1
        for i, ln in enumerate(lines):
            norm = fold(" ".join(normalize(ln)))
            if LABEL_RE.search(norm) and TOKEN_RE.search(norm):
                last = i
        tail = "\n".join(lines[last + 1 :]) if last >= 0 else ""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", tail) if p.strip()]
    return "\n\n".join(p for p in paragraphs if p.count(",") >= 3 and find_allergens(p))


def _check_consistency(res: ParseResult) -> None:
    """Record why a parsed panel looks wrong (`parse_suspect`): numbers that contradict each other."""
    n = res.nutrients
    kcal, carbs, protein, fat = (
        n.get(k) for k in ("energy_kcal", "carbohydrates_g", "protein_g", "fat_g")
    )
    if None not in (kcal, carbs, protein, fat) and _kcal_disagrees(kcal, carbs, protein, fat)[0]:
        res.suspect_reasons.append("kcal_mismatch")
    if None not in (n.get("sugars_g"), carbs) and n["sugars_g"] > carbs + ROUNDING_SLACK_G:
        res.suspect_reasons.append("sugars_gt_carbs")
    if (
        None not in (n.get("saturated_fat_g"), fat)
        and n["saturated_fat_g"] > fat + ROUNDING_SLACK_G
    ):
        res.suspect_reasons.append("saturates_gt_fat")


def _find_unverified_text(md: str) -> str:
    """Everything from the first ingredients / allergen line on, kept verbatim."""
    raw_lines = md.splitlines()
    for i, ln in enumerate(raw_lines):
        if UNVERIFIED_START.match(re.sub(r"<[^>]+>|[|*#]", " ", ln)):
            return "\n".join(raw_lines[i:]).strip()
    return ""


def _sort_lines(
    lines: list[str], res: ParseResult, force_column: int | None
) -> tuple[list[tuple[str, str]], list[_Row]]:
    """One pass over the panel lines: find the column header, join wrapped labels, and decide how
    each line is read later. Returns ([(kind, line)], label rows); kind is kcal, added or scan."""
    pending = ""
    rows: list[_Row] = []
    todo: list[tuple[str, str]] = []  # in text order; run once the column count is known
    collecting = True  # label rows are only read until the ingredients paragraph starts
    for ln in lines:
        if UNVERIFIED_START.match(ln):  # the ingredients paragraph is never parsed
            pending = ""
            collecting = False
            continue
        if res.serving_text is None and (m := SERVING_RE.search(ln)):
            res.serving_text = m.group(1).strip()
        ln = fold(ln)
        _find_column(ln, res, force_column)
        if pending:
            ln, pending = f"{pending} {ln}", ""
        if _ends_with_label(ln):
            pending = ln  # label wrapped onto the next row: join them
            continue
        if re.match(r"^kcal\s*\d", ln, re.IGNORECASE):
            todo.append(("kcal", ln))  # German tables: `Energie kJ 1360` / `kcal 329` on two rows
        elif "added sugar" in ln.lower():
            todo.append(("added", ln))
        else:
            todo.append(("scan", ln))
            if collecting:
                _collect_rows(ln, rows)
    return todo, rows


def _scan_added_sugars(ln: str, res: ParseResult) -> None:
    """`Includes 1g Added Sugars`: read the figure, then scan what is left of the line."""
    rest = ln
    for rx in ADDED_SUGARS_RES:
        if m := rx.search(ln):
            if "added_sugars_g" not in res.nutrients:
                res.nutrients["added_sugars_g"] = _convert(
                    _to_float(m.group("num")), m.group("unit") or "g", "added_sugars_g"
                )
            # a merged table row can carry other nutrients on the same line (`Cholesterol
            # <5mg 0% Includes 1g Added Sugars 38%`): scan what is left once the phrase is out
            rest = f"{ln[: m.start()]} {ln[m.end() :]}"
            break
    _scan_line(rest, res)


def _set_basis(res: ParseResult, md: str) -> None:
    """Per 100 g / ml or per serving, from the wording when no column header said so."""
    if res.column is None:
        first_100, first_serving = PER_100.search(md), PER_SERVING.search(md)
        if first_100 and (not first_serving or first_100.start() < first_serving.start()):
            res.basis = "100ml" if "ml" in first_100.group().lower() else "100g"
        elif first_serving:
            res.basis = "serving"
    res.per = "100g" if res.basis.startswith("100") else "serving"


# US / Canada panels print "Total Carbohydrate" with "Dietary Fiber" inside it.
US_STYLE_RE = re.compile(
    r"total\s+carbohydrate|dietary\s+fib(?:er|re)|nutrition\s+facts|total\s+carb\b", re.IGNORECASE
)


def _carb_includes_fibre(md: str, basis: str) -> bool | None:
    """True for a US-style panel; False for an EU / UK per-100 g panel (EU rules count carbohydrate
    without fibre, and list fibre on its own row); None when the format cannot be told."""
    if US_STYLE_RE.search(md):
        return True
    if basis in ("100g", "100ml"):
        return False
    return None


def parse(md: str, *, force_column: int | None = None) -> ParseResult:
    """Markdown / HTML table text of a label photo to nutrient fields plus `unverified_text`."""
    md = md or ""
    lines = normalize(md)
    res = ParseResult(edge_cutoff_suspected=_cutoff(lines, md))
    res.unverified_text = _find_unverified_text(md)

    todo, rows = _sort_lines(lines, res, force_column)
    # How many value columns? The rows know better than the header: a header that names `100 g`
    # alone over rows that all carry two values is a two-column table.
    counts = [len(r.toks) for r in rows if len(r.keys) == 1 and r.toks]
    if counts:
        res.width = min(multimode(counts))
    for kind, ln in todo:
        if kind == "kcal":
            _energy(ln, res)
        elif kind == "added":
            _scan_added_sugars(ln, res)
        else:
            _scan_line(ln, res)

    if not res.unverified_text:
        # no panel in frame: all of it is unverified; with a panel, only a list-like tail is
        res.unverified_text = _ingredient_like_tail(md) if res.panel_found else md.strip()

    if force_column is None and (swap := _scale_swap(rows, res)) is not None:
        swapped = parse(md, force_column=swap)  # the data say the 100 g column is another one
        swapped.column_swapped = True
        return swapped

    _set_basis(res, md)
    res.carb_includes_fibre = _carb_includes_fibre(md, res.basis)
    _align(rows, res)
    _check_consistency(res)
    return res
