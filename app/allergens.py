"""The 14 EU-regulated allergens (Regulation 1169/2011, Annex II), named in en, fr, es, pt, de, it.

`find_allergens(text)` returns `{name, kind}` for every allergen WORD that appears in the text, with
kind `may_contain` when every occurrence sits in a clause introduced by a "may contain" phrase (en,
fr, es, pt, de, it) and `contains` otherwise. A clause runs from the phrase to the next full stop,
semicolon or line break, so a wrapped line can only ever over-report an allergen as `contains`, never
downgrade one. An allergen named both ways is `contains`.

It is a keyword match on text the model read, nothing more: it cannot see what the frame cut off,
an invented word is matched like a real one, and "free from milk" would match milk. The UI therefore
labels the result "as read" and never presents it as a verified allergen list.
"""

from __future__ import annotations

import re

from app.parse import fold

# canonical key -> terms in en / fr / es / pt / de / it. Lower case, accents ignored (folded).
# A term matches as a whole word; a trailing `*` also allows a plural ending, a trailing `+` any
# ending (German compounds: `weizen+` matches Weizenmehl). Butter is left out on purpose: cocoa,
# shea and peanut butter are not milk, and a keyword match cannot tell them apart.
# fmt: off
ALLERGENS: dict[str, tuple[str, ...]] = {
    "gluten": (
        "gluten", "wheat*", "rye", "barley", "oats", "spelt", "kamut", "durum",
        "ble", "seigle", "orge", "avoine", "epeautre", "froment",
        "trigo", "centeno", "cebada", "avena", "espelta",
        "centeio", "cevada", "aveia",
        "weizen+", "roggen+", "gerste+", "hafer+", "dinkel+",
        "frumento", "grano", "segale", "orzo", "farro",
    ),
    "crustaceans": (
        "crustacean*", "shrimp*", "prawn*", "crab*", "lobster*", "crayfish",
        "crustaces", "crevette*", "crabe*", "homard*", "langoustine*",
        "crustaceo*", "gamba*", "camaron*", "cangrejo*", "langosta*",
        "camarao", "camaroes", "lagosta*", "caranguejo*",
        "krebstier*", "krabbe*", "garnele*", "hummer",
        "crostacei", "gambero", "gamberi", "granchio", "aragosta",
    ),
    "eggs": ("egg*", "oeuf*", "œuf*", "huevo*", "ovo*", "ei", "eier+", "eigelb", "uovo", "uova"),
    "fish": (
        "fish", "salmon", "tuna", "cod", "anchovy", "anchovies", "haddock",
        "poisson*", "saumon", "thon", "morue", "anchois",
        "pescado*", "atun", "bacalao", "anchoa*",
        "peixe*", "atum", "bacalhau", "anchova*",
        "fisch+", "lachs", "thunfisch", "kabeljau", "sardelle*",
        "pesce", "pesci", "tonno", "merluzzo", "acciughe",
    ),
    "peanuts": (
        "peanut*", "groundnut*", "arachide*", "cacahuete*", "cacahuate*", "amendoim", "amendoins",
        "erdnuss+", "erdnusse", "erdnuesse", "arachidi",
    ),
    "soybeans": ("soy", "soya", "soybean*", "soja+", "soia"),
    "milk": (
        "milk", "cream", "cheese", "whey", "lactose", "casein*", "yogurt", "yoghurt",
        "lait", "creme", "fromage", "lactoserum", "caseine*", "yaourt",
        "leche", "nata", "queso", "suero de leche", "lactosuero", "caseina*", "yogur",
        "leite", "natas", "queijo", "soro de leite", "iogurte",
        "milch+", "sahne+", "kase", "molke", "laktose", "joghurt",
        "latte", "panna", "formaggio", "siero di latte", "lattosio",
    ),
    "tree_nuts": (
        "almond*", "hazelnut*", "walnut*", "cashew*", "pecan*", "pistachio*", "macadamia*",
        "brazil nut*", "tree nut*", "nuts",
        "amande*", "noisette*", "noix", "cajou", "pistache*", "fruits a coque",
        "almendra*", "avellana*", "nuez", "nueces", "anacardo*", "pistacho*", "frutos de cascara",
        "amendoa*", "avela*", "noz", "nozes", "caju", "pistacio*", "frutos de casca rija",
        "mandel*", "haselnuss+", "haselnusse", "walnuss+", "walnusse", "pistazie*",
        "schalenfruchte", "nusse",
        "mandorla*", "mandorle", "nocciola*", "noce", "noci", "anacardi", "pistacchio*",
        "frutta a guscio",
    ),
    "celery": ("celery", "celeriac", "celeri", "apio", "aipo", "sellerie+", "sedano"),
    "mustard": ("mustard", "moutarde", "mostaza", "mostarda", "senf+", "senape"),
    "sesame": ("sesame", "sesam+", "sesamo", "gergelim", "ajonjoli"),
    "sulphites": (
        "sulphite*", "sulfite*", "sulphur dioxide", "sulfur dioxide", "sulfito*",
        "dioxyde de soufre", "anhydride sulfureux", "dioxido de azufre", "dioxido de enxofre",
        "schwefeldioxid", "diossido di zolfo", "anidride solforosa", "so2",
        "e220", "e221", "e222", "e223", "e224", "e226", "e227", "e228",
    ),
    "lupin": ("lupin*", "lupine", "altramuz*", "altramuces", "tremoco*", "lupini"),
    "molluscs": (
        "mollusc*", "mollusk*", "mussel*", "oyster*", "squid", "clam*", "snail*", "scallop*",
        "mollusque*", "moule*", "huitre*", "calmar*", "escargot*",
        "molusco*", "mejillon*", "mejillones", "ostra*", "calamar*", "almeja*",
        "mexilhao", "mexilhoes", "amejoa*", "lula*",
        "weichtier*", "muschel*", "auster*", "tintenfisch*",
        "molluschi", "cozze", "cozza", "ostrica", "ostriche", "calamari", "vongole",
    ),
}
# fmt: on

NAMES = {  # English display names for the UI
    "gluten": "Cereals containing gluten",
    "crustaceans": "Crustaceans",
    "eggs": "Eggs",
    "fish": "Fish",
    "peanuts": "Peanuts",
    "soybeans": "Soybeans",
    "milk": "Milk",
    "tree_nuts": "Tree nuts",
    "celery": "Celery",
    "mustard": "Mustard",
    "sesame": "Sesame",
    "sulphites": "Sulphur dioxide / sulphites",
    "lupin": "Lupin",
    "molluscs": "Molluscs",
}


def _pattern(term: str) -> str:
    stem = fold(term).lower()
    tail = {"*": "(?:s|es)?", "+": "[^\\W\\d_]*"}.get(stem[-1], "")
    stem = re.escape(stem.rstrip("*+")).replace(r"\ ", r"\s+")
    return stem + tail


# Phrases that introduce a precautionary clause, accent-folded and lower case. German puts the
# allergen between "kann" and "enthalten", so the clause starts at "kann".
MAY_CONTAIN_PATTERNS = [
    r"\b(?:may|might|can|could)\s+(?:also\s+)?contain\b",
    r"\btraces?\s+of\b|\btrace\s+amounts?\s+of\b",
    (
        r"\b(?:made|produced|manufactured|processed|packed)\s+(?:in|on)\s+(?:a\s+|an\s+|the\s+|shared\s+)?"
        r"(?:facility|factory|plant|premises|equipment|line)\b[^.;\n]*?\b(?:process|handle|use|contain)\w*"
    ),
    r"\bpeu(?:t|vent)\s+contenir\b",
    r"\btraces?\s+(?:eventuelles?\s+)?(?:de|d')",
    r"\bfabrique\w*\s+dans\s+un\s+(?:atelier|etablissement|site)\b",
    r"\bpuede[n]?\s+contener\b|\btrazas?\s+de\b",
    r"\belaborado\s+en\s+(?:una\s+)?(?:instalacion|fabrica|planta)\w*",
    r"\bpode[m]?\s+conter\b|\bvestigios\s+de\b|\btracos\s+de\b",
    r"\bkann\b[^.;\n]*?\benthalten\b|\bkonnen\b[^.;\n]*?\benthalten\b|\bspuren\s+von\b",
    r"\bhergestellt\s+in\s+einem\s+betrieb\b",
    r"\bpuo\s+contenere\b|\bpossono\s+contenere\b|\btracce\s+di\b|\bpossibile\s+presenza\s+di\b",
    r"\bprodotto\s+in\s+uno\s+stabilimento\b",
]
MAY_CONTAIN = re.compile("|".join(MAY_CONTAIN_PATTERNS))
CLAUSE_END = re.compile(r"[.;\n]")

_RX = {
    key: re.compile(
        r"(?<![^\W\d_])(?:" + "|".join(_pattern(t) for t in terms) + r")(?![^\W\d_])", re.IGNORECASE
    )
    for key, terms in ALLERGENS.items()
}


def _clauses(plain: str) -> list[tuple[int, int]]:
    """Spans of precautionary clauses: from a trigger phrase to the next `.`, `;` or line break."""
    spans = []
    for m in MAY_CONTAIN.finditer(plain):
        end = CLAUSE_END.search(plain, m.end())
        spans.append((m.start(), end.start() if end else len(plain)))
    return spans


def find_allergens(text: str) -> list[dict[str, str]]:
    """`{name, kind}` for each allergen named in `text`, in the EU list's order (one entry each)."""
    plain = fold(re.sub(r"<[^>]+>", " ", text or "")).lower()
    spans = _clauses(plain)
    found = []
    for key, rx in _RX.items():
        starts = [m.start() for m in rx.finditer(plain)]
        if starts:
            inside = [any(a <= p < b for a, b in spans) for p in starts]
            found.append({"name": key, "kind": "may_contain" if all(inside) else "contains"})
    return found
