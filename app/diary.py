"""Net carbs and the daily log: pure functions, no network.

A log entry is a snapshot taken when you tap "Add to today": the numbers on the label (as read, or as
you corrected them) times the portions you ate. Later edits to the label do not change past entries.
The app only reports totals; the limits belong to the person and live in the browser.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

MIN_PORTIONS = 0.5  # the page's stepper (web/js/result.js) starts here too: keep them equal
MAX_PORTIONS = 20.0
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def round_half_up(value: float, digits: int = 0) -> float:
    """Round like JavaScript's Math.round (halves go up); Python's round() takes exact halves to even,
    so 2.25 would save as 2.2 while the page shows 2.3. Mirrors `round1` in web/js/util.js."""
    rounded = Decimal(str(value)).quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else float(rounded)


def is_valid_day(value: str) -> bool:
    """A calendar date like 2026-11-06 (the person's local day, sent by the page)."""
    if not DAY_RE.match(value or ""):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


# How a net carbs figure was worked out (stored on each log entry, shown on screen).
MINUS_FIBRE = (
    "minus_fibre"  # US-style panel: total carbohydrate includes fibre, so fibre is subtracted
)
ALREADY_NET = "already_excludes_fibre"  # EU / UK panel: carbohydrate already excludes fibre
FIBRE_NOT_READ = (
    "fibre_not_read"  # US-style panel but no fibre figure: the full carbohydrate counts
)
FORMAT_UNKNOWN = "format_unknown"  # cannot tell the format: the full carbohydrate counts


def net_carbs(nutrients: dict) -> tuple[float | None, str | None]:
    """(net carbs in g, how it was worked out).

    Net carbs = carbohydrate - fibre ONLY when the printed carbohydrate includes fibre (a US or Canada
    "Total Carbohydrate"). EU / UK panels already exclude fibre, so subtracting it again would undercount.
    When the format is unknown the full carbohydrate counts: a figure that is too high is safer than one
    that is too low against a limit. No carbohydrate read -> (None, None)."""
    carbs = nutrients.get("carbohydrates_g")
    if carbs is None:
        return None, None
    includes_fibre = nutrients.get("carb_includes_fibre")
    if includes_fibre is False:
        return round_half_up(carbs, 1), ALREADY_NET
    if includes_fibre is None:
        return round_half_up(carbs, 1), FORMAT_UNKNOWN
    fiber = nutrients.get("fiber_g")
    if fiber is None:
        return round_half_up(carbs, 1), FIBRE_NOT_READ
    return round_half_up(max(carbs - fiber, 0.0), 1), MINUS_FIBRE


def portion_unit(nutrients: dict) -> tuple[str, float | None]:
    """(what one portion is, its size in g or ml when the panel is per 100 g / 100 ml, else None).

    The panel as printed is one portion: per 100 g, per serving, or unknown. Saying so on screen stops
    "1 portion" being mistaken for "1 bar"."""
    basis = nutrients.get("basis")
    if basis == "100g":
        return "100 g", 100.0
    if basis == "100ml":
        return "100 ml", 100.0
    if basis == "serving":
        serving = nutrients.get("serving_text")
        return (f"serving ({serving})" if serving else "serving"), None
    return "the panel as printed", None


def entry_from_label(label: dict, portions: float, day: str) -> dict:
    """The log entry for eating `portions` of a stored label on `day`."""
    nutrients = label.get("nutrients") or {}
    net, method = net_carbs(nutrients)
    unit_text, unit_size = portion_unit(nutrients)
    kcal = nutrients.get("energy_kcal")
    entry = {
        "id": uuid.uuid4().hex,
        "label_id": label["id"],
        "product_name": label.get("product_name"),
        "image_path": label.get("image_path"),
        "day": day,
        "eaten_at": datetime.now(UTC).isoformat(),
        "portions": portions,
        "basis": nutrients.get("basis"),
        "net_carbs_g": None if net is None else round_half_up(net * portions, 1),
        "calories_kcal": None if kcal is None else round_half_up(kcal * portions),
        "net_method": method,
        "unit_text": unit_text,
        "amount_text": None
        if unit_size is None
        else f"{round_half_up(unit_size * portions):g} {unit_text.split()[-1]}",
        "edited": bool(label.get("edited_fields")),
    }
    return {k: v for k, v in entry.items() if v is not None}
