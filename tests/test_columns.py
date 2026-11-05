"""Column choice in multi-column rows: the 100 g / 100 ml header, stacked cells, glued units,
header order vs the data's scale. `table_<barcode>.md` are real outputs of the table prompt (HTML
tables), `score_<barcode>.md` of the official prompt."""

from pathlib import Path

from app.parse import parse

FIX = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return parse((FIX / f"{name}.md").read_text())


# --- stacked cells: k labels x W columns arrive as k*W values, column-major -------------------------


def test_stacked_cells_two_columns_20003166():
    """`Grasas de las cuales, saturadas 7,0 g 1,3 g 2,8 g 0,5 g`: 100 g = 7,0 / 1,3; 40 g = 2,8 / 0,5."""
    res = fixture("table_20003166")
    assert (res.column, res.width, res.basis) == (0, 2, "100g")
    assert res.nutrients["fat_g"] == 7.0
    assert res.nutrients["saturated_fat_g"] == 1.3
    assert res.nutrients["sugars_g"] == 0.7  # `58,7 g 0,7 g 23,5 g 0,3 g`: carbs/sugars per 100 g


def test_stacked_cells_one_column_5411188112709():
    """`Fat of which Saturates | 1.1 g<br>0 g` under a single `per 100 ml` column."""
    res = fixture("table_5411188112709")
    assert (res.column, res.width, res.basis) == (0, 1, "100ml")
    assert res.nutrients["fat_g"] == 1.1
    assert res.nutrients["saturated_fat_g"] == 0.0
    assert res.nutrients["sugars_g"] == 0.0


def test_stacked_cells_carbs_and_sugars_20047238():
    res = fixture("table_20047238")
    assert res.nutrients["carbohydrates_g"] == 6.4
    assert res.nutrients["sugars_g"] == 4.2  # not the 30 g column's 1,3


def test_stacked_inline():
    res = parse("per 100 g per serving 40 g\nFat of which saturates 7,0 g 1,3 g 2,8 g 0,5 g")
    assert (res.nutrients["fat_g"], res.nutrients["saturated_fat_g"]) == (7.0, 1.3)


def test_two_labels_two_values_is_one_label_in_two_columns():
    """Nutella: `Fat of which saturates g 30.9 4.6` is fat per 100 g and per serving, saturates lost."""
    res = parse(
        "Pour 100 g Par portion 15 g\nMatières grasses dont acides gras saturés g 30.9 4.6 7%\n"
        "Protéines g 6.3 0.9"
    )
    assert res.nutrients["fat_g"] == 30.9
    assert "saturated_fat_g" not in res.nutrients


def test_data_column_count_beats_the_header_8076809573252():
    """The header names `100 g` alone but every row has two values: a wrapped `Proteinas` label
    must not turn `0,750 g 0,070 g` into protein 0,75 and salt 0,07."""
    res = fixture("score_8076809573252")
    assert res.width == 2
    assert res.nutrients["salt_g"] == 0.75
    assert "protein_g" not in res.nutrients or res.nutrients["protein_g"] != 0.75


# --- a unit glued in front of the number -----------------------------------------------------------


def test_unit_glued_before_the_number_6111242106949():
    """`<th>g3,5</th>` cells: Glucides g3,5 / Protéines g8 / Sel g0,46."""
    res = fixture("table_6111242106949")
    assert res.nutrients["carbohydrates_g"] == 3.5
    assert res.nutrients["protein_g"] == 8
    assert res.nutrients["salt_g"] == 0.46


def test_glued_unit_does_not_come_from_the_end_of_a_word():
    assert "fat_g" not in parse("Fat Omega3 5%").nutrients
    assert parse("Glucides g3,5").nutrients["carbohydrates_g"] == 3.5
    assert parse("Fett - Vetteng 47").nutrients["fat_g"] == 47  # unit glued to a word, then a space


# --- header order vs the data's scale --------------------------------------------------------------


def test_header_order_contradicted_by_the_data_is_swapped_5449000054227():
    """Header `250 ml | 100 ml`, values `10.6 g | 27 g` (27 / 10.6 = 2.5): the first column is 100 ml."""
    res = fixture("table_5449000054227")
    assert res.column_swapped and "column_swapped" in res.flags
    assert res.column == 0
    assert res.nutrients["carbohydrates_g"] == 10.6  # not the 250 ml column's 27
    assert res.basis == "100ml"


def test_header_and_data_in_agreement_is_not_swapped():
    res = parse("250 ml 100 ml\nCarbohydrate 27 g 10.6 g\nFat 0.5 g 0.2 g")
    assert not res.column_swapped
    assert (res.column, res.nutrients["carbohydrates_g"]) == (1, 10.6)


def test_inline_swap():
    res = parse("250 ml 100 ml\nCarbohydrate 10.6 g 27 g\nProtein 2 g 5 g")
    assert res.column_swapped
    assert res.nutrients["carbohydrates_g"] == 10.6


def test_a_serving_column_without_a_size_is_never_swapped():
    res = parse("per serving per 100 g\nCarbohydrate 27 g 90 g")
    assert not res.column_swapped
    assert res.nutrients["carbohydrates_g"] == 90


def test_header_ends_where_the_rows_start_in_a_glued_blob():
    """`Information nutritionnelle100 g1 (20 g)% / (20 g)Energie...Matières grasses17 g3,5 g`: the
    `17 g` and `3,5 g` of the rows are not column headers."""
    blob = (
        "Information nutritionnelle100 g1 (20 g)% / (20 g)Energie1962 kJ 467 kcal392 kJ 93 kcal5 %"
        "Matières grasses dont acides gras saturés17 g3,5 g5 %Glucides dont sucres69 g14 g5 %"
    )
    res = parse(blob)
    assert (res.column, res.width) == (0, 2)
    assert res.nutrients["fat_g"] == 17
