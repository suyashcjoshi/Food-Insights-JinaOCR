"""Parser rules from the accuracy review: decimal commas, kcal vs kJ, synonyms, column choice,
consistency flags. `score_<barcode>.md` fixtures are real jina-ocr-v1 output for OFF products."""

from pathlib import Path

import pytest

from app.parse import fold, parse

FIX = Path(__file__).parent / "fixtures"


def fixture(code: str):
    return parse((FIX / f"score_{code}.md").read_text())


# --- decimal commas ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "key", "value"),
    [
        ("Salz 1,7 g", "salt_g", 1.7),
        ("Fett 0,107 g", "fat_g", 0.107),
        ("Kohlenhydrate 1,234 g", "carbohydrates_g", 1.234),  # a comma is never a thousands mark
        ("Proteínas 12,5 g", "protein_g", 12.5),
    ],
)
def test_decimal_comma_is_a_decimal(text, key, value):
    assert parse(text).nutrients[key] == value


def test_decimal_commas_in_a_portuguese_table_5411188116592():
    res = fixture("5411188116592")
    # `Lípidos / Grassi dos quais / di cui saturados | 0,8 g` is a merged row: first label gets it
    assert res.nutrients["fat_g"] == 0.8
    assert (
        res.nutrients["carbohydrates_g"] == 2.7
    )  # `Hidratos / Carboidrati dos quais ... açúcares`
    assert res.nutrients["salt_g"] == 0.13
    assert res.nutrients["protein_g"] == 0.1


# --- energy -----------------------------------------------------------------------------------


def test_kcal_wins_and_kj_is_stored_separately_5449000000996():
    res = fixture("5449000000996")
    assert res.nutrients["energy_kcal"] == 42
    assert res.energy_kj == 180
    assert not res.energy_converted
    assert "energy_converted" not in res.flags


def test_kj_only_is_converted_and_flagged():
    res = parse("Energy 1000 kJ")
    assert res.nutrients["energy_kcal"] == 239  # 1000 / 4.184
    assert res.energy_kj == 1000
    assert res.energy_converted
    assert "energy_converted" in res.flags


def test_unit_glued_after_the_number_belongs_to_the_next_number_8076809513753():
    """`EnergiekJ2030kcal 492`: 2030 is the kJ, 492 the kcal (it used to read 2030 kcal)."""
    res = fixture("8076809513753")
    assert res.nutrients["energy_kcal"] == 492
    assert res.energy_kj == 2030
    assert not res.parse_suspect


@pytest.mark.parametrize(
    "text", ["Energie kJ 1360 kcal 329", "Energy 2030 kJ 492 kcal", "Energy 2030 kJ / 492 kcal"]
)
def test_kj_kcal_orders(text):
    res = parse(text)
    assert res.nutrients["energy_kcal"] in (329, 492)
    assert not res.energy_converted


# --- synonyms: of-which forms, accents, case ---------------------------------------------------


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (  # fr
            (
                "Matières grasses 10 g\ndont acides gras saturés 3 g\nGlucides 20 g\ndont sucres 5 g\n"
                "Protéines 6 g\nSel 1,2 g\nÉnergie 250 kcal"
            ),
            {"fat_g": 10, "saturated_fat_g": 3, "carbohydrates_g": 20, "sugars_g": 5},
        ),
        (  # es
            (
                "Grasas 10 g\nde las cuales saturadas 3 g\nHidratos de carbono 20 g\n"
                "de los cuales azúcares 5 g\nProteínas 6 g\nSal 1,2 g\nValor energético 250 kcal"
            ),
            {"fat_g": 10, "saturated_fat_g": 3, "carbohydrates_g": 20, "sugars_g": 5},
        ),
        (  # pt
            (
                "Lípidos 10 g\ndos quais saturados 3 g\nHidratos de carbono 20 g\n"
                "dos quais açúcares 5 g\nProteínas 6 g\nSal 1,2 g\nEnergia 250 kcal"
            ),
            {"fat_g": 10, "saturated_fat_g": 3, "carbohydrates_g": 20, "sugars_g": 5},
        ),
        (  # de
            (
                "Fett 10 g\ndavon gesättigte Fettsäuren 3 g\nKohlenhydrate 20 g\ndavon Zucker 5 g\n"
                "Eiweiß 6 g\nSalz 1,2 g\nBrennwert 250 kcal"
            ),
            {"fat_g": 10, "saturated_fat_g": 3, "carbohydrates_g": 20, "sugars_g": 5},
        ),
        (  # it
            (
                "Grassi 10 g\ndi cui acidi grassi saturi 3 g\nCarboidrati 20 g\ndi cui zuccheri 5 g\n"
                "Proteine 6 g\nSale 1,2 g\nValore energetico 250 kcal"
            ),
            {"fat_g": 10, "saturated_fat_g": 3, "carbohydrates_g": 20, "sugars_g": 5},
        ),
        (  # ja
            (
                "エネルギー 250kcal\nたんぱく質 6.0g\n脂質 10.0g\nうち飽和脂肪酸 3.0g\n炭水化物 20.0g\n"
                "うち糖質 5.0g\n食塩相当量 1.2g"
            ),
            {"fat_g": 10, "saturated_fat_g": 3, "carbohydrates_g": 20, "sugars_g": 5},
        ),
    ],
    ids=["fr", "es", "pt", "de", "it", "ja"],
)
def test_synonyms_and_of_which_forms(text, want):
    res = parse(text)
    for key, value in want.items():
        assert res.nutrients[key] == value, key
    assert res.nutrients["protein_g"] == 6
    assert res.nutrients["salt_g"] in (1.2,)
    assert res.nutrients["energy_kcal"] == 250


@pytest.mark.parametrize(
    "text",
    [
        "ENERGÍA 250 kcal\nGRASAS 10 G",
        "Energia 250 kcal\nGrasas 10 g",
        "energía 250 KCAL\ngrasas 10 g",
    ],
)
def test_labels_are_case_and_accent_insensitive(text):
    res = parse(text)
    assert res.nutrients["energy_kcal"] == 250
    assert res.nutrients["fat_g"] == 10


def test_fold_strips_latin_accents_but_not_kana():
    assert fold("Énergie Fettsäuren Açúcares") == "Energie Fettsauren Acucares"
    assert fold("ガ脂質ナトリウム") == "ガ脂質ナトリウム"


# --- column choice and basis -------------------------------------------------------------------


def test_per_100_ml_column_beats_the_330_ml_column_5449000000996():
    res = fixture("5449000000996")
    assert res.nutrients["carbohydrates_g"] == 10.6  # not the 35 g of the 330 ml column
    assert res.basis == "100ml"
    assert res.column == 0


def test_100_g_column_is_chosen_when_it_is_not_the_first():
    res = parse(
        "Per serving (30 g) Per 100 g\nEnergy 150 kcal 500 kcal\nFat 3 g 10 g\n"
        "Carbohydrate 6 g 20 g\nProtein 1,5 g 5 g"
    )
    assert res.column == 1
    assert res.basis == "100g"
    assert res.nutrients == {
        "energy_kcal": 500,
        "fat_g": 10,
        "carbohydrates_g": 20,
        "protein_g": 5,
    }


def test_unit_printed_once_applies_to_the_later_column():
    res = parse("Per serving Per 100 g\nFat g 3.0 10.0\nSalt g 0.1 0.4")
    assert (res.nutrients["fat_g"], res.nutrients["salt_g"]) == (10.0, 0.4)


def test_row_without_a_value_in_the_100_column_is_skipped_not_guessed():
    res = parse("Per serving Per 100 g\nFat 3 g")
    assert "fat_g" not in res.nutrients


def test_basis_without_a_column_header():
    assert parse("Nutrition per 100 g\nCarbohydrate 72 g").basis == "100g"
    assert parse("Amount per serving\nCarbohydrate 27 g").basis == "serving"
    assert parse("Carbohydrate 27 g").basis == "unknown"


def test_header_word_inside_another_word_is_not_a_column():
    """`Declaração` contains `ração`; it must not count as a per-ration column."""
    res = fixture("5411188116592")
    assert res.column == 0
    assert res.nutrients["energy_kcal"] == 20


# --- consistency check -------------------------------------------------------------------------


def test_consistent_panel_is_verified():
    res = parse("Energy 250 kcal\nFat 10 g\nCarbohydrate 20 g\nProtein 20 g")  # 90+80+80 = 250
    assert not res.parse_suspect and res.verified


def test_kcal_off_by_more_than_20_percent_is_suspect_6902007505264():
    res = parse((FIX / "off_6902007505264.md").read_text())  # 43 kcal vs 4*1.5 + 4*4.1 = 22
    assert "kcal_mismatch" in res.suspect_reasons
    assert res.parse_suspect and not res.verified
    assert "parse_suspect" in res.flags


def test_sugars_above_carbs_is_suspect():
    res = parse("Carbohydrate 10 g\nof which sugars 20 g\nProtein 2 g")
    assert "sugars_gt_carbs" in res.suspect_reasons
    assert not res.verified


def test_saturates_above_fat_is_suspect():
    res = parse("Fat 3 g\nof which saturates 8 g\nCarbohydrate 5 g")
    assert res.suspect_reasons == ["saturates_gt_fat"]
    assert not res.verified


def test_small_absolute_kcal_gap_is_not_suspect():
    assert not parse("Energy 24 kcal\nFat 0 g\nCarbohydrate 5 g\nProtein 0.5 g").parse_suspect
