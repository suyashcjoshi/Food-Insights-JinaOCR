"""Scoring: normalised model reads and the cause of every wrong or missing field."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import score

FIX = Path(__file__).parent / "fixtures"
SAMPLES = json.loads((FIX / "score_samples.json").read_text())


def scored(code: str, text: str | None = None, truth: dict | None = None) -> dict:
    """Run one fixture through the real score_entry path."""
    s = SAMPLES.get(code, {"name": code, "lang": "xx", "truth": {}})
    entry = {
        "barcode": code,
        "name": s["name"],
        "lang": s["lang"],
        "panel": {"nutrients": truth or s["truth"]},
    }
    rec = {
        "status": 200,
        "ms": 1,
        "usage": {},
        "finish_reason": "stop",
        "text": text if text is not None else (FIX / f"score_{code}.md").read_text(),
    }
    return score.score_entry(entry, rec)["fields"]


# --- model_read_accuracy ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("want", "text", "key", "read"),
    [
        (1.7, "Salz 1,7 g", "salt_g", True),  # decimal comma
        (1.7, "Salz 1.70 g", "salt_g", True),  # trailing zero
        (0.107, "Sel 0,107 g", "salt_g", True),
        (42.4, "Energie 180 kJ / 42 kcal", "energy_kcal", True),  # whole kcal
        (42.4, "Energie 177 kJ", "energy_kcal", True),  # kJ equivalent (within 1 %)
        (42.4, "Energie 90 kJ", "energy_kcal", False),
        (6.3, "Protein 16.3 g", "protein_g", False),  # not a substring match
        (0.0, "anything", "fat_g", True),
    ],
)
def test_in_text_is_normalised(want, text, key, read):
    assert score.in_text(want, text, key) is read


def test_model_read_accuracy_is_true_when_value_is_in_the_text_even_if_parse_is_wrong():
    fields = scored("3017620425035")
    assert fields["carbohydrates_g"]["outcome"] == "wrong"
    assert fields["carbohydrates_g"]["model_read_accuracy"] is True  # 57.5 is in the text
    assert fields["sugars_g"]["model_read_accuracy"] is False  # 56.3 is nowhere in it


# --- categories, one per bug class --------------------------------------------------------------


def test_shift_merged_two_line_labels_3017620425035():
    """Nutella: `Glucides dont sucres 10.6` is really the saturates; every row below shifts."""
    fields = scored("3017620425035")
    assert fields["carbohydrates_g"]["got"] == 10.6  # the saturates value
    assert fields["carbohydrates_g"]["category"] == "shift"
    assert fields["protein_g"]["category"] == "shift"  # got the carbs value
    assert fields["salt_g"]["category"] == "shift"  # got the protein value


def test_unit_kj_taken_as_kcal():
    fields = scored("x", "Energy 2030 kcal", {"energy_kcal": 492.0})
    assert fields["energy_kcal"]["category"] == "unit"


def test_unit_sodium_taken_as_salt_and_mg_as_g():
    assert scored("x", "Salt 1.0 g", {"salt_g": 2.5})["salt_g"]["category"] == "unit"
    assert scored("x", "Fat 12000 g", {"fat_g": 12.0})["fat_g"]["category"] == "unit"


def test_comma_digits_glued():
    fields = scored("x", "Fat 17 g\nnote 1,7 g", {"fat_g": 1.7})
    assert fields["fat_g"]["category"] == "comma"


def test_comma_class_is_empty_for_the_real_comma_fixture_5411188116592():
    fields = scored("5411188116592")
    assert all(f["category"] != "comma" for f in fields.values())


def test_synonym_value_on_a_row_with_an_unknown_label():
    fields = scored("x", "Tuotteen xyz 7,0 g\nFat 3 g", {"sugars_g": 7.0})
    assert fields["sugars_g"]["outcome"] == "missing"
    assert fields["sugars_g"]["category"] == "synonym"


def test_column_label_known_but_other_column_taken():
    fields = scored("x", "Fat 5 g\n[ref] Fat 9 g", {"fat_g": 9.0})
    assert fields["fat_g"]["got"] == 5.0
    assert fields["fat_g"]["category"] == "column"


def test_truth_disagreement_whole_panel_slightly_off_20995553():
    fields = scored("20995553")
    wrong = [f for f in fields.values() if f["outcome"] == "wrong"]
    assert len(wrong) >= 3
    assert {f["category"] for f in wrong} == {"truth_disagreement"}
    assert not any(f["model_read_accuracy"] for f in wrong)


def test_model_value_not_in_the_text_and_no_pattern():
    fields = scored("x", "Fat 3 g\nProtein 9 g", {"fat_g": 3.0, "sugars_g": 41.0})
    assert fields["sugars_g"]["category"] == "model"
    assert fields["sugars_g"]["model_read_accuracy"] is False


def test_dropped_zero_is_model_not_synonym():
    fields = scored("x", "Fat 3 g", {"fat_g": 3.0, "salt_g": 0.0})
    assert fields["salt_g"]["category"] == "model"
    assert fields["salt_g"]["model_read_accuracy"] is False


def test_correct_fields_have_no_category():
    fields = scored("x", "Fat 3 g", {"fat_g": 3.0})
    assert fields["fat_g"]["category"] is None
