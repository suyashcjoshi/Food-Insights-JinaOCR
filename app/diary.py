"""Net carbs and the daily log: pure functions, no network.

A log entry is a snapshot taken when you tap "Add to today": the numbers on the label (as read, or as
you corrected them) times the portions you ate. Later edits to the label do not change past entries.
The app only reports totals; the limits belong to the person and live in the browser.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime

MIN_PORTIONS = 0.25
MAX_PORTIONS = 20.0
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_valid_day(value: str) -> bool:
    """A calendar date like 2026-11-06 (the person's local day, sent by the page)."""
    if not DAY_RE.match(value or ""):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def net_carbs(nutrients: dict) -> tuple[float | None, bool]:
    """(net carbs in g, fiber_was_read). Net = carbohydrate - fiber, never below zero.

    No carbohydrate read -> (None, False). Carbohydrate but no fiber -> the total carbohydrate with
    fiber_was_read False, so a missing fiber figure never makes the number look lower than it is."""
    carbs = nutrients.get("carbohydrates_g")
    if carbs is None:
        return None, False
    fiber = nutrients.get("fiber_g")
    return round(max(carbs - (fiber or 0.0), 0.0), 1), fiber is not None


def entry_from_label(label: dict, portions: float, day: str) -> dict:
    """The log entry for eating `portions` of a stored label on `day`."""
    nutrients = label.get("nutrients") or {}
    net, fiber_read = net_carbs(nutrients)
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
        "net_carbs_g": None if net is None else round(net * portions, 1),
        "calories_kcal": None if kcal is None else round(kcal * portions),
        "fiber_read": fiber_read,
        "edited": bool(label.get("edited_fields")),
    }
    return {k: v for k, v in entry.items() if v is not None}
