"""Unverified text when the model garbles the headings. `nutella_us_jar.md` is real output of the
table prompt for a US Nutella jar: `INGREDIENTS:` came back as `IMPORTANT:` and `CONTAINS` as
`DATING`, so no heading matched and `unverified_text` used to be empty."""

from pathlib import Path

from app.allergens import find_allergens
from app.parse import parse

FIX = Path(__file__).parent / "fixtures"
JAR = (FIX / "nutella_us_jar.md").read_text()


def test_ingredient_paragraphs_are_kept_when_the_headings_are_garbled():
    res = parse(JAR)
    assert res.panel_found
    assert res.unverified_text.startswith("IMPORTANT: SUGAR, PALM OIL, HAZELNUTS")
    assert "DATING TREE NUTS (HAZELNUTS), MILK, SOY" in res.unverified_text
    assert "<table" not in res.unverified_text  # the panel is not part of it
    assert "NUTELLA" not in res.unverified_text  # nor the unrelated footer lines


def test_allergens_follow_from_the_recovered_text():
    kinds = {a["name"]: a["kind"] for a in find_allergens(parse(JAR).unverified_text)}
    assert kinds == {"tree_nuts": "contains", "milk": "contains", "soybeans": "contains"}


def test_the_parser_reads_what_the_model_wrote_not_what_the_label_says():
    """The pack says Total Sugars 21 g and Added Sugars 19 g; the model wrote `2g` and `1g` from a
    360 px photo. That is a model misread: the parser must not invent the missing digit, and the
    numbers still add up, so the panel is 'verified'. (That flag never meant 'correct'.)"""
    res = parse(JAR)
    assert res.nutrients["sugars_g"] == 2.0
    assert res.nutrients["added_sugars_g"] == 1.0
    assert res.nutrients["carbohydrates_g"] == 22.0 and res.nutrients["energy_kcal"] == 200.0
    assert res.verified


def test_footnotes_and_addresses_are_not_promoted_to_unverified_text():
    """Reference-intake footnotes follow most panels; they are not ingredients."""
    assert parse((FIX / "score_20005733.md").read_text()).unverified_text == ""
    assert parse((FIX / "score_3017620425035.md").read_text()).unverified_text == ""


def test_plain_text_panels_work_the_same_way():
    text = "Total Fat 11g\nTotal Carbohydrate 22g\nProtein 2g\n\nSUGAR, PALM OIL, HAZELNUTS, SKIM MILK, COCOA.\n\nMADE IN CHINA"
    res = parse(text)
    assert res.unverified_text == "SUGAR, PALM OIL, HAZELNUTS, SKIM MILK, COCOA."


def test_a_list_with_no_allergen_word_is_left_alone():
    """Conservative on purpose: without a heading or an allergen word we do not guess."""
    text = "Total Fat 11g\nTotal Carbohydrate 22g\n\nSUGAR, PALM OIL, COCOA, VANILLIN, SALT."
    assert parse(text).unverified_text == ""


def test_a_real_heading_still_wins():
    res = parse((FIX / "yogurt_official.md").read_text())
    assert res.unverified_text.startswith("INGREDIENTS")


def test_a_nutrient_sharing_a_row_with_added_sugars_is_not_lost():
    """The model merged cells: `Cholesterol <5mg 0% Includes 1g Added Sugars 38%` is one row. The
    added-sugars branch used to drop the rest of the line, so the cholesterol vanished."""
    res = parse("Cholesterol <5mg 0% Includes 1g Added Sugars 38%")
    assert res.nutrients == {
        "cholesterol_mg": 5.0,
        "added_sugars_g": 1.0,
    }  # not sugars_g: 38% is a %DV
    assert parse(JAR).nutrients["cholesterol_mg"] == 5.0
    assert parse("Incl. 18g Added Sugars 36%").nutrients == {
        "added_sugars_g": 18.0
    }  # alone, as before
