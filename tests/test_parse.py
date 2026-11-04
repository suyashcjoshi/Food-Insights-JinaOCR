import json
from pathlib import Path

import pytest

from app.parse import parse

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).parent / "fixtures"
TRUTH = json.loads((ROOT / "data" / "kitchen" / "yogurt.truth.json").read_text())


@pytest.mark.parametrize("fixture", ["yogurt_official.md", "yogurt_grounded.md"])
def test_yogurt_panel_matches_truth(fixture):
    """One-line output and HTML-table output both give every panel value in the truth file."""
    res = parse((FIX / fixture).read_text())
    assert res.nutrients == TRUTH["panel"]["nutrients"]
    assert res.per == TRUTH["panel"]["per"]
    assert res.serving_text == "6 oz (170g)"
    assert res.verified


def test_yogurt_ingredients_are_unverified_text_not_fields():
    res = parse((FIX / "yogurt_official.md").read_text())
    assert res.unverified_text.startswith("INGREDIENTS")
    assert "MAY CONTAIN" in res.unverified_text
    assert not any("ingredient" in k or "allergen" in k for k in res.nutrients)


def test_percent_is_not_read_as_grams():
    res = parse("Total Fat 3%\nTotal Carbohydrate 27g 10%")
    assert "fat_g" not in res.nutrients
    assert res.nutrients["carbohydrates_g"] == 27


def test_energy_kj_and_kcal():
    res = parse("Energy 1890 kJ / 448 kcal")
    assert res.nutrients["energy_kcal"] == 448
    assert res.energy_kj == 1890


def test_energy_from_kj_only():
    assert parse("Energie 1000 kJ").nutrients["energy_kcal"] == 239


def test_calories_from_fat_is_ignored():
    res = parse("Calories 240 Calories from Fat 35")
    assert res.nutrients["energy_kcal"] == 240


def test_incl_added_sugars_number_before_label():
    res = parse("Total Sugars 20g\nIncl. 18g Added Sugars 36%")
    assert res.nutrients["sugars_g"] == 20
    assert res.nutrients["added_sugars_g"] == 18


@pytest.mark.parametrize(
    ("line", "key", "value"),
    [
        ("Hidratos de carbono 72 g", "carbohydrates_g", 72),
        ("Kohlenhydrate 12,5 g", "carbohydrates_g", 12.5),
        ("Glucides 8 g", "carbohydrates_g", 8),
        ("Carboidrati 30 g", "carbohydrates_g", 30),
        ("Hidratos de carbono 7,1 g", "carbohydrates_g", 7.1),
        ("Eiweiß 4,2 g", "protein_g", 4.2),
        ("Protéines 14 g", "protein_g", 14),
        ("Salz 1,1 g", "salt_g", 1.1),
        ("davon Zucker 5 g", "sugars_g", 5),
        ("dont sucres 3 g", "sugars_g", 3),
        ("Gordura saturada 2 g", "saturated_fat_g", 2),
        ("Matières grasses 9 g", "fat_g", 9),
    ],
)
def test_multilingual_synonyms(line, key, value):
    assert parse(line).nutrients[key] == value


def test_unit_normalisation():
    res = parse("Sodium 0.29 g\nCalcium 1200 mcg\nVitamin D 2 µg\nCholesterol 10 mg")
    assert res.nutrients["sodium_mg"] == 290
    assert res.nutrients["calcium_mg"] == 1.2
    assert res.nutrients["vitamin_d_mcg"] == 2
    assert res.nutrients["cholesterol_mg"] == 10


def test_html_table_fallback():
    html = (
        "<table><tr><th>Energy</th><th>1890 kJ / 448 kcal</th></tr>"
        "<tr><td>Carbohydrate</td><td>72 g</td></tr>"
        "<tr><td>Protein</td><td>6 g</td></tr></table>"
    )
    res = parse(html)
    assert res.nutrients == {"energy_kcal": 448, "carbohydrates_g": 72, "protein_g": 6}


def test_per_100g_detected():
    assert parse("Nutrition per 100 g\nCarbohydrate 72 g").per == "100g"
    assert parse("Amount per serving\nCarbohydrate 27 g").per == "serving"


@pytest.mark.parametrize(
    "text",
    ["Carbohydrate 27 g\n[…] cut", "INGREDIENTS: MILK, SUGAR, MODIFIED CORN-", "Sugar (from fruit"],
)
def test_edge_cutoff_flag(text):
    assert parse(text).edge_cutoff_suspected


def test_not_verified_without_panel_or_when_cut_off():
    assert not parse("INGREDIENTS: MILK").verified
    assert not parse("Carbohydrate 27 g\n[…]").verified
    assert parse("Carbohydrate 27 g").verified


def test_no_panel_returns_empty():
    res = parse("Just a photo of a cat.")
    assert res.nutrients == {}
    assert not res.panel_found


def test_glued_panel_blob_is_split_by_label():
    blob = (
        "<table><td>Children Under 4 Amount Per Serving 100 150 80 Calories152010 Total Fat 2g*3%3%1.5g"
        "Saturated Fat 0.5g3%3%0g Cholesterol 0mg0%1%0mg Sodium 140mg6%8%105mg "
        "Total Carbohydrate 20g7%9%1.5g Dietary Fiber 3g11%11%1.5g Sugars 1g2g Protein 3g1.5g</table>"
    )
    res = parse(blob)
    assert res.nutrients["carbohydrates_g"] == 20
    assert res.nutrients["sodium_mg"] == 140
    assert res.nutrients["fat_g"] == 2
    assert "energy_kcal" not in res.nutrients  # "152010" is not a calorie count


def test_bare_number_for_gram_nutrient_is_not_accepted():
    """`Total Fat 120` is a calories column, not 120 g; gram values always carry a unit."""
    assert "fat_g" not in parse("Total Fat 120").nutrients


def test_japanese_labels():
    res = parse("熱量 120kcal\nたんぱく質 3.0g\n脂質 1.0g\n炭水化物 22.0g\n食塩相当量 0.1g")
    assert res.nutrients == {
        "energy_kcal": 120,
        "protein_g": 3.0,
        "fat_g": 1.0,
        "carbohydrates_g": 22.0,
        "salt_g": 0.1,
    }


def test_no_panel_keeps_all_text_as_unverified():
    res = parse("原材料名：オート麦、ライ麦フレーク")
    assert res.nutrients == {}
    assert res.unverified_text.startswith("原材料名")


OFF = json.loads((FIX / "off_samples.json").read_text())


@pytest.mark.parametrize("code", sorted(OFF))
def test_off_samples_parse_to_what_the_label_says(code):
    """Real jina-ocr-v1 output for three OFF photos: German table (unit before number, wrapped
    label), Spanish/Portuguese glued blob, Japanese prose line. Tolerance as in score.py."""
    res = parse((FIX / f"off_{code}.md").read_text())
    for key, want in OFF[code]["expected"].items():
        tol = 5 if key == "energy_kcal" else 0.5
        assert key in res.nutrients, f"{key} not parsed"
        assert abs(res.nutrients[key] - want) <= tol, f"{key}: {res.nutrients[key]} vs {want}"
    assert res.per == "100g"


def test_explicit_kcal_row_beats_kj_conversion():
    res = parse("Energie kJ 1360\nkcal 329")
    assert res.nutrients["energy_kcal"] == 329
    assert res.energy_kj == 1360


def test_digits_glued_to_a_label_are_not_part_of_the_label():
    assert parse("Sal0,05 g").nutrients["salt_g"] == 0.05
    assert parse("dos quais saturados29 g").nutrients["saturated_fat_g"] == 29
