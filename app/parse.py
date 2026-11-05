"""Nutrient parser for jina-ocr-v1 Markdown (BRIEF 7.5).

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
        out += ["aligned"] if self.aligned else []
        out += ["column_swapped"] if self.column_swapped else []
        return out + (["parse_suspect", *self.suspect_reasons] if self.parse_suspect else [])

    @property
    def verified(self) -> bool:
        """Panel parsed, nothing cut off, numbers consistent (index field `nutrients_verified`)."""
        return self.panel_found and not self.edge_cutoff_suspected and not self.parse_suspect


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


def _energy(seg: str, res: ParseResult) -> None:
    """`1890 kJ / 448 kcal`, `kJ 1360`, `Calories 150`, and unitless pairs (`2252 539`, `188/45`).

    kcal wins, kJ is stored separately and only converts (/ 4.184, flag `energy_converted`) when no
    kcal is present. A bare number is kcal unless the text only mentions kJ. Two bare numbers whose
    ratio is ~4.184 are a kJ/kcal pair whatever their order. With several columns the one under
    the 100 g / 100 ml header is read (`res.column`).
    """
    col = res.column or 0
    kcals: list[float] = []
    kjs: list[float] = []
    bare: list[float] = []
    # two unit words in a row (`kJ kcal`, `(Kj/Kcal)`) are a column header, not units of the number
    seg = re.sub(r"\(?\b(?:kj|kcal)\b[\s/]*\b(?:kj|kcal)\b\)?", " ", seg, flags=re.IGNORECASE)
    for m in TOKEN_RE.finditer(seg):
        u1, u2 = ((m.group(g) or "").lower().lstrip("-– ") for g in ("u1", "u2"))
        # `kJ2030kcal 492`: a different unit glued after the number is the next number's header
        unit = u1 if u1 and u2 and u1 != u2 else (u2 or u1)
        val = _to_float(m.group("num"))
        if unit == "kcal":
            kcals.append(val)
        elif unit == "kj":
            kjs.append(val)
        elif not unit and len(m.group("num")) <= 4 and len(bare) < 2 * (col + 1):
            bare.append(val)
    kcal = kcals[col] if col < len(kcals) else None
    kj = kjs[col] if col < len(kjs) else None
    if kcal is None and kj is None and len(bare) >= 2 * (col + 1):
        pair = bare[2 * col : 2 * col + 2]
        if min(pair) > 0 and 3.9 <= max(pair) / min(pair) <= 4.4:
            kj, kcal = max(pair), min(pair)
            bare = []
    if kcal is None and bare and col == 0:
        lower = seg.lower()
        if "kj" in lower and "kcal" not in lower and "cal" not in lower:
            kj = kj if kj is not None else bare[0]
        else:
            kcal = bare[0]
    if kj is not None and res.energy_kj is None:
        res.energy_kj = kj
    value, derived = kcal, False
    if value is None and kj is not None:
        value, derived = round(kj / KCAL_PER_KJ), True
    have = "energy_kcal" in res.nutrients
    if (
        value is not None
        and value <= MAX_KCAL
        and (not have or (res.energy_from_kj and not derived))
    ):
        res.nutrients["energy_kcal"] = value
        res.energy_from_kj = derived


CONNECTORS = re.compile(
    r"^(?:\s|[/:,.\-]|dont|davon|of which|whereof|di cui|de los cuales|de las cuales|dos quais|das quais|"
    r"including|incl|うち|内)*$",
    re.IGNORECASE,
)


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


def _scan_line(ln: str, res: ParseResult) -> None:
    matches = list(LABEL_RE.finditer(ln))
    claimed: set[int] = set()  # start offsets of tokens already given to a label
    for i, m in enumerate(matches):
        key = m.lastgroup
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ln)
        seg = ln[m.end() : end]
        if key == "energy_kcal":
            _energy(seg, res)
            continue
        toks = list(TOKEN_RE.finditer(seg))
        offset = m.end()
        chain = [key]  # `Fat of which saturates | 30.9`: labels with no value between them
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
            nend = matches[last + 1].start() if last + 1 < len(matches) else len(ln)
            offset = matches[last].end()
            toks = list(TOKEN_RE.finditer(ln[offset:nend]))
        col = res.column or 0
        k = len(chain)
        if k > 1 and res.width and len(toks) == k * res.width:
            picks = {
                name: col * k + j for j, name in enumerate(chain)
            }  # stacked cells: column-major
        elif len(toks) > col:
            picks = {
                key: col
            }  # a merged row with one value per column: it belongs to the first label
        else:
            continue  # no value in the per-100 column: never fall back to another one
        for name, idx in picks.items():
            if name in res.nutrients or (pos := offset + toks[idx].start()) in claimed:
                continue
            unit = _token_unit(toks, idx, ln[m.end() :])
            if unit in TO_GRAMS:  # gram/mg values always print a unit; skip a bare number
                res.nutrients[name] = _convert(_to_float(toks[idx].group("num")), unit, name)
                claimed.add(pos)


def _ends_with_label(ln: str) -> bool:
    """A line with no digits whose last words are a label (`davon: gesättigte`): values follow."""
    if re.search(r"\d", ln) or len(ln) > 60:
        return False
    last = None
    for m in LABEL_RE.finditer(ln):
        last = m
    return last is not None and len(ln) - last.end() <= 3


def _find_column(ln: str, res: ParseResult, forced: int | None = None) -> None:
    """The first `100 g` / `100 ml` header fixes which value column to read in every row.

    Also records how many value columns the header names (`width`) and the size of each, which the
    stacked-cell rule and the scale check need. Only the header part of the line counts: a glued
    blob continues into the rows, so the header ends at the first nutrient label after a marker.
    """
    hm = COL100_RE.search(ln)
    if hm is None or res.column is not None:
        return
    head = ln
    for lm in LABEL_RE.finditer(ln):
        if lm.start() > hm.start():
            head = ln[: lm.start()]
            break
    sizes: list[float | None] = []
    idx100 = None
    for m in COLUMN_HEADER_RE.finditer(head):
        if "%" in head[max(0, m.start() - 12) : m.start()]:
            continue  # a %RI column, not a value column
        num = re.search(r"\d+(?:[.,]\d+)?", m.group())
        sizes.append(_to_float(num.group()) if num else None)
        if idx100 is None and COL100_RE.search(m.group()):
            idx100 = len(sizes) - 1
    if idx100 is None:  # the header was cut before its own 100 marker: count the columns left of it
        idx100 = sum(
            1
            for m in COLUMN_HEADER_RE.finditer(ln[: hm.start()])
            if "%" not in ln[max(0, m.start() - 12) : m.start()]
        )
        sizes = [*sizes, *[None] * (idx100 + 1 - len(sizes))][: max(len(sizes), idx100 + 1)]
        sizes[idx100] = 100.0
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
        med, expected = median(ratios), size / 100
        if abs(med / expected - 1) <= 0.2:
            return None  # header and data agree
        if abs(med * expected - 1) <= 0.2:
            return j
    return None


# --- order-aware alignment ------------------------------------------------------------------------

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
class _Row:
    keys: list[str]  # nutrient labels on this row, in text order (empty: a row with no label)
    toks: list[float | None]  # every value token after the labels, in grams (None: no unit)
    last_in_line: bool = True  # may carry extra unlabelled rows when tokens come glued together


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


def _collect_rows(ln: str, rows: list[_Row]) -> None:
    """Add the label rows of one (folded) line: labels with no value between them share a row."""
    matches = list(LABEL_RE.finditer(ln))
    if not matches:
        label_free = not re.search(r"[^\W\d_]", VALUE_ONLY_NOISE.sub("", ln))
        if rows and label_free and (toks := _gram_tokens(ln)):
            rows.append(_Row([], toks))  # `g 0.107 0.016 0%`: a row whose label cell is empty
        return
    made: list[_Row] = []
    i = 0
    while i < len(matches):
        j = i
        while j + 1 < len(matches) and not TOKEN_RE.search(
            ln[matches[j].end() : matches[j + 1].start()]
        ):
            j += 1
        keys: list[str] = []
        for k in range(i, j + 1):
            key = matches[k].lastgroup
            if key != "energy_kcal" and key not in keys:
                keys.append(key)
        end = matches[j + 1].start() if j + 1 < len(matches) else len(ln)
        if keys:
            made.append(_Row(keys, _gram_tokens(ln[matches[j].end() : end]), last_in_line=False))
        i = j + 1
    if made:
        made[-1].last_in_line = True
        rows.extend(made)


def _flatten(
    rows: list[_Row], column: int, hdr_width: int | None = None
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
        k = len(r.keys)
        if k > 1 and hdr_width and len(r.toks) == k * hdr_width:  # stacked cells, column-major
            stack = r.toks[column * k : (column + 1) * k]
            keys += [x for x in r.keys if x not in keys]
            values += [v for v in stack if v is not None]
            continue
        chunks = [r.toks[i : i + width] for i in range(0, len(r.toks), width)]
        if chunks and len(chunks[0]) > column and chunks[0][column] is not None:
            values.append(chunks[0][column])
        keys += [k for k in r.keys if k not in keys]
        if r.keys and r.last_in_line and len(r.toks) % width == 0:
            values += [c[column] for c in chunks[1:] if len(c) > column and c[column] is not None]
    if len(keys) < 3 or any(k not in EU_ORDER for k in keys):
        return None
    if [EU_ORDER.index(k) for k in keys] != sorted({EU_ORDER.index(k) for k in keys}):
        return None
    return keys, values


def _violations(a: dict[str, float], res: ParseResult) -> tuple[int, float]:
    """Number of broken rules and the Atwater error (0.3 when it cannot be evaluated)."""
    bad = 0
    sat, fat, sug, carb = (
        a.get(k) for k in ("saturated_fat_g", "fat_g", "sugars_g", "carbohydrates_g")
    )
    bad += sat is not None and fat is not None and sat > fat + 0.05
    bad += sug is not None and carb is not None and sug > carb + 0.05
    fib = a.get("fiber_g")
    bad += fib is not None and carb is not None and fib > carb + 0.05
    if res.basis.startswith("100"):
        bad += any(v > 100.5 for v in a.values())
        macros = [a.get(k) for k in ("fat_g", "carbohydrates_g", "protein_g")]
        bad += sum(m for m in macros if m is not None) > 105
    kcal, protein = res.nutrients.get("energy_kcal"), a.get("protein_g")
    if None in (kcal, fat, carb, protein):
        return bad, 0.3
    est = 4 * carb + 4 * protein + 9 * fat
    diff = abs(kcal - est)
    bad += diff > KCAL_NOISE and diff > KCAL_TOLERANCE * est
    return bad, diff / max(est, 1.0)


def _align(rows: list[_Row], res: ParseResult) -> None:
    flat = _flatten(rows, res.column or 0, res.width)
    if flat is None:
        return
    keys, values = flat
    n, m = len(keys), len(values)
    if m < 2 or abs(n - m) > 3:
        return
    best: tuple | None = None
    if n >= m:  # a value was lost: leave some labels without one
        options = [
            (skip, dict(zip([k for i, k in enumerate(keys) if i not in skip], values, strict=True)))
            for skip in combinations(range(n), n - m)
        ]
        costs = [sum(SKIP_COST.get(keys[i], 1) for i in skip) for skip, _ in options]
    else:  # a spare value: an unlabelled row (cheap if trailing, as in a glued last row)
        options = [
            (skip, dict(zip(keys, [v for i, v in enumerate(values) if i not in skip], strict=True)))
            for skip in combinations(range(m), m - n)
        ]
        costs = [sum(0 if i >= n else 1 for i in skip) for skip, _ in options]
    for (skip, assign), cost in zip(options, costs, strict=True):
        bad, err = _violations(assign, res)
        # later labels are the casualties of merged rows, so prefer leaving those out
        rank = (bad, cost, round(err, 2), tuple(-i for i in sorted(skip, reverse=True)))
        if best is None or rank < best[0]:
            best = (rank, assign)
    if best is None or best[0][0] != 0:
        return
    assign = {k: round(v, 4) for k, v in best[1].items()}
    new = {**{k: v for k, v in res.nutrients.items() if k not in keys}, **assign}
    if {k: res.nutrients.get(k) for k in keys if k in res.nutrients} != assign:
        res.aligned = True
    res.nutrients = new


def _check_consistency(res: ParseResult) -> None:
    n = res.nutrients
    kcal, carbs, protein, fat = (
        n.get(k) for k in ("energy_kcal", "carbohydrates_g", "protein_g", "fat_g")
    )
    if None not in (kcal, carbs, protein, fat):
        est = 4 * carbs + 4 * protein + 9 * fat
        diff = abs(kcal - est)
        if diff > KCAL_NOISE and diff > KCAL_TOLERANCE * est:
            res.suspect_reasons.append("kcal_mismatch")
    if None not in (n.get("sugars_g"), carbs) and n["sugars_g"] > carbs + 0.05:
        res.suspect_reasons.append("sugars_gt_carbs")
    if None not in (n.get("saturated_fat_g"), fat) and n["saturated_fat_g"] > fat + 0.05:
        res.suspect_reasons.append("saturates_gt_fat")


def parse(md: str, *, _force_column: int | None = None) -> ParseResult:
    lines = normalize(md)
    res = ParseResult(edge_cutoff_suspected=_cutoff(lines, md or ""))

    # unverified text: everything from the first ingredients/allergen line, kept verbatim
    raw_lines = (md or "").splitlines()
    for i, ln in enumerate(raw_lines):
        if UNVERIFIED_START.match(re.sub(r"<[^>]+>|[|*#]", " ", ln)):
            res.unverified_text = "\n".join(raw_lines[i:]).strip()
            break

    pending = ""
    rows: list[_Row] = []
    todo: list[
        tuple[str, str]
    ] = []  # (kind, line) in text order, run once the column count is known
    collecting = True  # label rows are only read until the ingredients paragraph starts
    for ln in lines:
        if UNVERIFIED_START.match(ln):  # the ingredients paragraph is never parsed
            pending = ""
            collecting = False
            continue
        if res.serving_text is None and (m := SERVING_RE.search(ln)):
            res.serving_text = m.group(1).strip()
        ln = fold(ln)
        _find_column(ln, res, _force_column)
        if pending:
            ln, pending = f"{pending} {ln}", ""
        if _ends_with_label(ln):
            pending = ln  # label wrapped onto the next row: join them
            continue
        if re.match(r"^kcal\s*\d", ln, re.IGNORECASE):
            todo.append(("kcal", ln))  # German tables: `Energie kJ 1360` / `kcal 329` on two rows
            continue
        if "added sugar" in ln.lower():
            todo.append(("added", ln))
            continue
        todo.append(("scan", ln))
        if collecting:
            _collect_rows(ln, rows)

    # How many value columns? The rows know better than the header: a header that names `100 g`
    # alone over rows that all carry two values is a two-column table.
    counts = [len(r.toks) for r in rows if len(r.keys) == 1 and r.toks]
    if counts:
        res.width = min(multimode(counts))
    for kind, ln in todo:
        if kind == "kcal":
            _energy(ln, res)
        elif kind == "added":
            for rx in ADDED_SUGARS_RES:
                if (m := rx.search(ln)) and "added_sugars_g" not in res.nutrients:
                    res.nutrients["added_sugars_g"] = _convert(
                        _to_float(m.group("num")), m.group("unit") or "g", "added_sugars_g"
                    )
                    break
        else:
            _scan_line(ln, res)

    if not res.unverified_text and not res.panel_found:
        res.unverified_text = (md or "").strip()  # no panel in frame: all of it is unverified

    if _force_column is None and (swap := _scale_swap(rows, res)) is not None:
        swapped = parse(md, _force_column=swap)  # the data say the 100 g column is another one
        swapped.column_swapped = True
        return swapped

    if res.column is None:
        first_100, first_serv = PER_100.search(md or ""), PER_SERVING.search(md or "")
        if first_100 and (not first_serv or first_100.start() < first_serv.start()):
            res.basis = "100ml" if "ml" in first_100.group().lower() else "100g"
        elif first_serv:
            res.basis = "serving"
    res.per = "100g" if res.basis.startswith("100") else "serving"
    _align(rows, res)
    _check_consistency(res)
    return res
