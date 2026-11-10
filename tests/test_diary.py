"""Net carbs, log entries, and guessing a product name from the front of a pack."""

from pathlib import Path

import pytest

from app import diary
from app.naming import guess_product_name
from app.parse import parse

US = {"carb_includes_fibre": True}
EU = {"carb_includes_fibre": False}


def test_us_style_net_carbs_is_total_carbohydrate_minus_fibre():
    assert diary.net_carbs({"carbohydrates_g": 27, "fiber_g": 4, **US}) == (23.0, "minus_fibre")


def test_eu_style_carbohydrate_already_excludes_fibre_so_nothing_is_subtracted():
    # EU / UK panels list fibre separately: subtracting it again would undercount
    assert diary.net_carbs({"carbohydrates_g": 27, "fiber_g": 4, **EU}) == (
        27.0,
        "already_excludes_fibre",
    )


def test_us_style_without_a_fibre_figure_counts_the_full_carbohydrate_and_says_so():
    assert diary.net_carbs({"carbohydrates_g": 27, **US}) == (27.0, "fibre_not_read")


def test_unknown_format_counts_the_full_carbohydrate_never_a_lower_number():
    assert diary.net_carbs({"carbohydrates_g": 27, "fiber_g": 4}) == (27.0, "format_unknown")


def test_net_carbs_never_goes_below_zero_and_needs_a_carbohydrate_figure():
    assert diary.net_carbs({"carbohydrates_g": 3, "fiber_g": 9, **US}) == (0.0, "minus_fibre")
    assert diary.net_carbs({"fiber_g": 4, **US}) == (None, None)
    assert diary.net_carbs({}) == (None, None)


def test_a_portion_says_what_it_is_so_it_is_not_mistaken_for_one_bar():
    assert diary.portion_unit({"basis": "100g"}) == ("100 g", 100.0)
    assert diary.portion_unit({"basis": "100ml"}) == ("100 ml", 100.0)
    assert diary.portion_unit({"basis": "serving", "serving_text": "6 oz (170g)"}) == (
        "serving (6 oz (170g))",
        None,
    )
    assert diary.portion_unit({})[0] == "the panel as printed"


@pytest.mark.parametrize(
    "day,ok", [("2026-11-06", True), ("2026-02-30", False), ("06-11-2026", False), ("", False)]
)
def test_day_must_be_a_real_calendar_date(day, ok):
    assert diary.is_valid_day(day) is ok


def test_entry_scales_by_portions_and_omits_what_was_not_read():
    label = {"id": "l1", "nutrients": {"carbohydrates_g": 10.0, "basis": "100g", **EU}}
    entry = diary.entry_from_label(label, 1.5, "2026-11-06")
    assert entry["net_carbs_g"] == 15.0 and entry["net_method"] == "already_excludes_fibre"
    assert (
        entry["unit_text"] == "100 g" and entry["amount_text"] == "150 g"
    )  # 1.5 x 100 g, said plainly
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


# --- which label format is it? (decides whether fibre is subtracted) -----------------------------

FIX = Path(__file__).parent / "fixtures"


def test_a_us_panel_is_recognised_as_including_fibre():
    assert parse((FIX / "nutella_us_jar.md").read_text()).carb_includes_fibre is True
    assert parse((FIX / "yogurt_official.md").read_text()).carb_includes_fibre is True


def test_an_eu_per_100g_panel_is_recognised_as_excluding_fibre():
    assert parse((FIX / "table_20003166.md").read_text()).carb_includes_fibre is False


def test_text_with_no_panel_is_unknown():
    assert parse("Fresh apples, 1 kg, grown in Kent.").carb_includes_fibre is None
