"""Net carbs, log entries, and guessing a product name from the front of a pack."""

import pytest

from app import diary
from app.naming import guess_product_name


def test_net_carbs_is_carbohydrate_minus_fibre():
    assert diary.net_carbs({"carbohydrates_g": 27, "fiber_g": 4}) == (23.0, True)


def test_net_carbs_without_fibre_is_the_total_and_says_so():
    assert diary.net_carbs({"carbohydrates_g": 27}) == (27.0, False)


def test_net_carbs_never_goes_below_zero_and_needs_a_carbohydrate_figure():
    assert diary.net_carbs({"carbohydrates_g": 3, "fiber_g": 9}) == (0.0, True)
    assert diary.net_carbs({"fiber_g": 4}) == (None, False)
    assert diary.net_carbs({}) == (None, False)


@pytest.mark.parametrize(
    "day,ok", [("2026-11-06", True), ("2026-02-30", False), ("06-11-2026", False), ("", False)]
)
def test_day_must_be_a_real_calendar_date(day, ok):
    assert diary.is_valid_day(day) is ok


def test_entry_scales_by_portions_and_omits_what_was_not_read():
    label = {"id": "l1", "nutrients": {"carbohydrates_g": 10.0}}
    entry = diary.entry_from_label(label, 0.5, "2026-11-06")
    assert entry["net_carbs_g"] == 5.0 and entry["fiber_read"] is False
    assert "calories_kcal" not in entry  # no energy was read: not a silent zero
    assert entry["edited"] is False


def test_entry_records_when_the_numbers_were_edited_by_hand():
    label = {
        "id": "l1",
        "nutrients": {"carbohydrates_g": 10.0},
        "edited_fields": ["carbohydrates_g"],
    }
    assert diary.entry_from_label(label, 1, "2026-11-06")["edited"] is True


@pytest.mark.parametrize(
    "markdown,name",
    [
        ("# Chobani Greek Yogurt\n\nNet Wt 500 g", "Chobani Greek Yogurt"),
        ("**Nutella**\n\nHazelnut spread with cocoa", "Nutella"),
        ("500 g\n\nBarilla Pesto alla Genovese", "Barilla Pesto alla Genovese"),
        ("<p>Skyr nature 0%</p>", "Skyr nature 0%"),
        ("12\n\n!!\n\n", None),
        ("", None),
    ],
)
def test_guess_product_name_takes_the_first_readable_line(markdown, name):
    assert guess_product_name(markdown) == name


def test_guess_product_name_is_capped():
    assert len(guess_product_name("A" * 200)) <= 60
