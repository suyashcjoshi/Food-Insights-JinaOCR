"""Nutrient parser for jina-ocr-v1 Markdown (BRIEF 7.5).

Only the Nutrition Facts panel becomes fields. Ingredients, allergens and claims are returned as
`unverified_text` and never parsed (the model invents text where the frame cuts the label off).

Approach: normalise Markdown / HTML-table output to lines (one table row per line), then scan each
line for nutrient labels. A value is the first number after a label and before the next label, with
the unit either after it (`27g`) or before it (`g 12`, German tables). That one rule covers
one-line-per-nutrient panels, table rows, glued single-line blobs (`Lípidos48 g- de las cuales ...`)
and prose lines (`エネルギー43kcal、たんぱく質4.1g`). Gram/mg values must carry a unit; a bare number
is never accepted (it is usually a calories or %DV column). Labels: EN/ES/DE/FR/IT/PT/JA.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

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
        r"energy|energ[ií]a|energie|[eé]nergie|valor energ\w+tico|valeur [eé]nerg\w+tique|"
        r"brennwert|calories(?!\s*from)|calorias|calorie|熱量|エネルギー"
    ),
    "saturated_fat_g": (
        r"saturated fat|saturates|saturated|acides gras satur\w+|gras satur\w+|satur\w+|"
        r"ges\w+ttigte fetts\w+ure\w*|ges\w+ttigte|[aá]cidos grasos saturados|"
        r"grasas saturadas|gorduras? satur\w+|l[ií]pidos satur\w+|saturadas|saturados|"
        r"grassi saturi|acidi grassi saturi|saturi"
    ),
    "trans_fat_g": r"trans fat|trans",
    "fat_g": (
        r"total fat|fat|lipides|graisses|mati\w+res grasses|fett|grasas?|grassi|"
        r"gorduras?|l[ií]pidos|lipidi|脂質"
    ),
    "cholesterol_mg": r"cholesterol|cholest\w+rol|colesterol",
    "sodium_mg": r"sodium|sodio|natrium|ナトリウム",
    "salt_g": r"salt|sel|salz|sal|sale|食塩相当量",
    "carbohydrates_g": (
        r"total carbohydrates?|carbohydrates?|carbs|hidratos de carbono|hidratos|carbohidratos|"
        r"kohlenhydrate|glucides|gl[uú]cidos|carboidrati|炭水化物"
    ),
    "fiber_g": (
        r"dietary fib(?:er|re)s?|fib(?:er|re)s?|ballaststoffe|fibras?|"
        r"fibre alimentari|fibres alimentaires|食物繊維"
    ),
    "sugars_g": (
        r"total sugars|sugars|sugar|sucres|zucker|az[uú]cares|a[cç][uú]cares|zuccheri|糖質|糖類"
    ),
    "protein_g": r"proteins?|prot\w+ines?|eiwei\w+|prote[ií]nas?|proteine|たんぱく質|タンパク質",
    "vitamin_d_mcg": r"vitamin d|vitamine d|vitamina d",
    "calcium_mg": r"calcium|calcio|c\w+lcio",
    "iron_mg": r"iron|fer|eisen|hierro|ferro",
    "potassium_mg": r"potassium|kalium|potasio|pot\w+ssio",
    "vitamin_a_mcg": r"vitamin a|vitamine a|vitamina a",
}
LABELS = {k: v.replace(r"\w", r"[^\W\d_]") for k, v in LABELS.items()}
# A label is a whole word, or (for glued OCR text) an Uppercase label glued onto a lowercase/digit.
LABEL_RE = re.compile(
    r"(?:(?<![^\W\d_])|(?-i:(?<=[a-z\d])(?=[A-ZÀ-Þ])))"
    + "(?:"
    + "|".join(f"(?P<{key}>{alt})" for key, alt in LABELS.items())
    + r")(?![^\W\d_])",
    re.IGNORECASE,
)
UNIT = r"mcg|µg|μg|ug|mg|kcal|kj|g"
TOKEN_RE = re.compile(
    rf"(?:(?P<u1>[-–]?\s*(?:{UNIT}))\s+)?(?P<num>\d+(?:[.,]\d+)?)"
    rf"(?:\s*(?P<u2>{UNIT})(?![a-z])|(?!\d)(?!\s*%))",
    re.IGNORECASE,
)
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


@dataclass
class ParseResult:
    nutrients: dict[str, float] = field(default_factory=dict)
    energy_kj: float | None = None
    serving_text: str | None = None
    per: str = "serving"
    unverified_text: str = ""
    edge_cutoff_suspected: bool = False
    energy_from_kj: bool = False  # kcal was derived from kJ; an explicit kcal row replaces it

    @property
    def panel_found(self) -> bool:
        return "carbohydrates_g" in self.nutrients or "energy_kcal" in self.nutrients

    @property
    def verified(self) -> bool:
        """Parsed from a panel AND no edge cut-off flag (index field `nutrients_verified`)."""
        return self.panel_found and not self.edge_cutoff_suspected


def _to_float(s: str) -> float:
    return float(s.replace(",", "."))


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


def _first_token(seg: str) -> tuple[float, str | None] | None:
    m = TOKEN_RE.search(seg)
    if not m:
        return None
    unit = m.group("u2") or m.group("u1")
    return _to_float(m.group("num")), (unit.lower().lstrip("-– ") if unit else None)


def _energy(seg: str, res: ParseResult) -> None:
    """`1890 kJ / 448 kcal`, `kJ 1360`, `Calories 150`: kcal wins, kJ converts, bare number = kcal."""
    kcal = kj = bare = None
    for m in TOKEN_RE.finditer(seg):
        unit = (m.group("u2") or m.group("u1") or "").lower().lstrip("-– ")
        val = _to_float(m.group("num"))
        if unit == "kcal":
            kcal = kcal if kcal is not None else val
        elif unit == "kj":
            kj = kj if kj is not None else val
        elif not unit and bare is None and len(m.group("num")) <= 4:
            bare = val
    if kj is not None and res.energy_kj is None:
        res.energy_kj = kj
    value, derived = (kcal if kcal is not None else bare), False
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


def _scan_line(ln: str, res: ParseResult) -> None:
    matches = list(LABEL_RE.finditer(ln))
    for i, m in enumerate(matches):
        key = m.lastgroup
        end = matches[i + 1].start() if i + 1 < len(matches) else len(ln)
        seg = ln[m.end() : end]
        if key == "energy_kcal":
            _energy(seg, res)
            continue
        if key in res.nutrients:
            continue
        tok = _first_token(seg)
        if tok and tok[1] in TO_GRAMS:  # gram/mg values always print a unit; skip a bare number
            res.nutrients[key] = _convert(tok[0], tok[1], key)


def _ends_with_label(ln: str) -> bool:
    """A line with no digits whose last words are a label (`davon: gesättigte`): values follow."""
    if re.search(r"\d", ln) or len(ln) > 60:
        return False
    last = None
    for m in LABEL_RE.finditer(ln):
        last = m
    return last is not None and len(ln) - last.end() <= 3


def parse(md: str) -> ParseResult:
    lines = normalize(md)
    res = ParseResult(edge_cutoff_suspected=_cutoff(lines, md or ""))

    # unverified text: everything from the first ingredients/allergen line, kept verbatim
    raw_lines = (md or "").splitlines()
    for i, ln in enumerate(raw_lines):
        if UNVERIFIED_START.match(re.sub(r"<[^>]+>|[|*#]", " ", ln)):
            res.unverified_text = "\n".join(raw_lines[i:]).strip()
            break

    pending = ""
    for ln in lines:
        if UNVERIFIED_START.match(ln):  # the ingredients paragraph is never parsed
            pending = ""
            continue
        if res.serving_text is None and (m := SERVING_RE.search(ln)):
            res.serving_text = m.group(1).strip()
        if pending:
            ln, pending = f"{pending} {ln}", ""
        if _ends_with_label(ln):
            pending = ln  # label wrapped onto the next row: join them
            continue
        if re.match(r"^kcal\s*\d", ln, re.IGNORECASE):
            _energy(ln, res)  # German tables: `Energie kJ 1360` / `kcal 329` on separate rows
            continue
        if "added sugar" in ln.lower():
            for rx in ADDED_SUGARS_RES:
                if (m := rx.search(ln)) and "added_sugars_g" not in res.nutrients:
                    res.nutrients["added_sugars_g"] = _convert(
                        _to_float(m.group("num")), m.group("unit") or "g", "added_sugars_g"
                    )
                    break
            continue
        _scan_line(ln, res)

    if not res.unverified_text and not res.panel_found:
        res.unverified_text = (md or "").strip()  # no panel in frame: all of it is unverified

    first_100, first_serv = PER_100.search(md or ""), PER_SERVING.search(md or "")
    if first_100 and (not first_serv or first_100.start() < first_serv.start()):
        res.per = "100g"
    return res
