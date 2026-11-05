"""Order-aware alignment of labels to values (merged label rows drop a value and shift the table)."""

from pathlib import Path

from app.parse import parse

FIX = Path(__file__).parent / "fixtures"


def fixture(code: str):
    return parse((FIX / f"score_{code}.md").read_text())


def test_nutella_3017620425035_merged_rows_realigned():
    """`Matières grasses dont saturés | 30.9`, `Glucides dont sucres | 10.6`, `Protéines | 57.5`,
    `Sel | 6.3`, then a row with no label `0.107`: the model lost the sugars, so every value after
    the fat sat one label too high. Skipping the sugars satisfies the Atwater check (533 vs 539)."""
    res = fixture("3017620425035")
    assert res.nutrients == {
        "energy_kcal": 539,
        "fat_g": 30.9,
        "saturated_fat_g": 10.6,
        "carbohydrates_g": 57.5,
        "protein_g": 6.3,
        "salt_g": 0.107,
    }
    assert res.aligned and "aligned" in res.flags


def test_french_glued_blob_7622210449283_saturates_lost_by_the_model():
    """Fat+saturates share a row with one value, sugars sit on the fibre row, the salt on a
    trailing unlabelled row. Only 'skip the saturates' keeps sat <= fat."""
    res = fixture("7622210449283")
    assert res.nutrients["fat_g"] == 17
    assert "saturated_fat_g" not in res.nutrients
    assert res.nutrients["carbohydrates_g"] == 69
    assert res.nutrients["sugars_g"] == 32
    assert res.nutrients["protein_g"] == 6.3
    assert res.nutrients["salt_g"] == 0.49
    assert res.aligned and not res.parse_suspect


def test_portuguese_table_20005733_duplicated_value_row():
    """Two label rows carry the same 6.8 (the model repeated it). The saturates get it, the fibre
    row is left out; the Atwater check (711 vs 712 kcal) confirms fat/protein/salt."""
    res = fixture("20005733")
    assert res.nutrients["fat_g"] == 69.1
    assert res.nutrients["saturated_fat_g"] == 6.8
    assert res.nutrients["protein_g"] == 15.5
    assert res.nutrients["salt_g"] == 0.02
    assert res.aligned and not res.parse_suspect


def test_consistent_panel_is_left_alone():
    res = parse(
        "Energy 250 kcal\nFat 10 g\nof which saturates 3 g\nCarbohydrate 20 g\nProtein 20 g"
    )
    assert res.nutrients["saturated_fat_g"] == 3
    assert not res.aligned


def test_only_the_alignment_that_satisfies_the_rules_is_taken():
    """Three labels, two values: 3 g cannot be the fat if the saturates must be <= fat."""
    res = parse("Fat of which saturates 10 g\nCarbohydrate of which sugars 3 g\nProtein 6 g")
    assert res.nutrients["fat_g"] == 10
    assert res.nutrients.get("carbohydrates_g") == 3
    assert "sugars_g" not in res.nutrients


def test_us_order_panels_are_not_realigned():
    """Sodium / cholesterol rows mean a US panel: one row per nutrient, nothing to realign."""
    res = parse("Total Fat 3 g\nSodium 140 mg\nTotal Carbohydrate 20 g\nProtein 3 g")
    assert not res.aligned
    assert res.nutrients["sodium_mg"] == 140


def test_alignment_never_forces_an_assignment_that_breaks_the_rules():
    """Sugars > carbs in every possible alignment: keep what the row scan found, flag it."""
    res = parse("Carbohydrate 5 g\nof which sugars 40 g\nProtein 2 g")
    assert not res.aligned
    assert "sugars_gt_carbs" in res.suspect_reasons
