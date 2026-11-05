# Triage: "model" misses

91 fields where the OFF value is not on that nutrient's row of the OCR text (source: `reports/score_official.json`). `suggested_cause` is a heuristic from the script's docstring; fill `confirmed_cause` (one of the five causes) after looking at the photo. Re-running the script keeps what you filled in. `scripts/score.py` uses `confirmed_cause` when present and `suggested_cause` otherwise.

| suggested_cause | count |
|---|---|
| basis_mismatch | 8 |
| rounding_lt05 | 20 |
| revision | 6 |
| multilang_blob | 5 |
| misread | 52 |
| **total** | 91 |

`closest 3` are the three numbers in the OCR text nearest the OFF value (HTML tags and `%` values excluded). `got` is what the parser produced ('-' = missing). An OFF value of 0 means the model dropped that nutrient's row or never read a zero for it.

| image | lang | nutrient | OFF | closest 3 | basis indicators | got | suggested_cause | confirmed_cause |
|---|---|---|---|---|---|---|---|---|
| data/off/20003166.jpg | es | salt_g | 0.02 | 0.03, 0.01, 0.3 | 100 g | - | basis_mismatch |  |
| data/off/4056489620938.jpg | es | energy_kcal | 103 | 100, 51.8, 29.6 | 100 g | 656 | basis_mismatch |  |
| data/off/4056489620938.jpg | es | fat_g | 8.3 | 8.6, 3.7, 15.9 | 100 g | 51.8 | basis_mismatch |  |
| data/off/4056489620938.jpg | es | sugars_g | 0.6 | 0.47, 3.7, 8.6 | 100 g | 3.7 | basis_mismatch |  |
| data/off/80052760.jpg | it | carbohydrates_g | 52 | 49.5, 41.21, 37.3 | per portion | - | basis_mismatch |  |
| data/off/80052760.jpg | it | protein_g | 8.6 | 8.61, 8, 3 | per portion | - | basis_mismatch |  |
| data/off/80052760.jpg | it | salt_g | 0.2675 | 0.272, 3, 8 | per portion | - | basis_mismatch |  |
| data/off/8076809573252.jpg | it | protein_g | 8 | 7.5, 9.3, 9.39 | 100 g | - | basis_mismatch |  |
| data/off/3046920028721.jpg | es | sugars_g | 0.49 | 0.7, 1, 4 | 100 g | 1 | rounding_lt05 |  |
| data/off/5000157024671.jpg | pt | protein_g | 4.8 | 4.7, 5, 3.7 | 100 g | 3.7 | rounding_lt05 |  |
| data/off/5000157024671.jpg | pt | salt_g | 0.6 | 0.2, 3.7, 4.7 | 100 g | 4.7 | rounding_lt05 |  |
| data/off/5053990155354.jpg | it | saturated_fat_g | 6.4 | 6.3, 8.7, 3.5 | 100 g | 2.9 | rounding_lt05 |  |
| data/off/5053990155354.jpg | it | sugars_g | 2.7 | 2.9, 2.1, 3.5 | 100 g | 2.1 | rounding_lt05 |  |
| data/off/5053990156009.jpg | it | protein_g | 6.2 | 5.9, 6.6, 3.5 | 100 g | 3.5 | rounding_lt05 |  |
| data/off/5410041001204.jpg | de | protein_g | 8.3 | 8.4, 7.1, 2.4 | - | - | rounding_lt05 |  |
| data/off/5411188110835.jpg | de | fat_g | 1.2 | 1, 0.5, 2 | - | 12 | rounding_lt05 |  |
| data/off/5411188110835.jpg | de | sugars_g | 2.4 | 2.3, 2.6, 2 | - | 0.3 | rounding_lt05 |  |
| data/off/5411188116592.jpg | pt | saturated_fat_g | 0.9 | 0.8, 0.75, 0.38 | 100 ml | - | rounding_lt05 |  |
| data/off/5411188116592.jpg | pt | sugars_g | 1.9 | 2, 2.7, 0.8 | 100 ml | - | rounding_lt05 |  |
| data/off/5411188119098.jpg | es | sugars_g | 2.2 | 2.3, 2.4, 2.9 | 100 g | - | rounding_lt05 |  |
| data/off/6111246721261.jpg | fr | energy_kcal | 80.6 | 80, 70, 11 | - | - | rounding_lt05 |  |
| data/off/6902007505264.jpg | ja | carbohydrates_g | 3.8 | 4.1, 1.5, 1 | 100 ml | 1.5 | rounding_lt05 |  |
| data/off/6902007505264.jpg | ja | sugars_g | 1.1 | 1, 1.5, 0 | 100 ml | - | rounding_lt05 |  |
| data/off/8000500310427.jpg | pt | fat_g | 24.8 | 24.83, 13.8, 35.84 | - | - | rounding_lt05 |  |
| data/off/8000500310427.jpg | pt | protein_g | 7.9 | 7.91, 11.51, 13.8 | - | - | rounding_lt05 |  |
| data/off/8000500310427.jpg | pt | salt_g | 0.559 | 0.559, 7.91, 11.51 | - | - | rounding_lt05 |  |
| data/off/8000500310427.jpg | pt | saturated_fat_g | 11.5 | 11.51, 13.8, 7.91 | - | - | rounding_lt05 |  |
| data/off/8000500310427.jpg | pt | sugars_g | 35.8 | 35.84, 24.83, 13.8 | - | - | rounding_lt05 |  |
| data/off/3046920028363.jpg | pt | energy_kcal | 584 | 530, 100, 46 | 100 g | 530 | revision |  |
| data/off/3046920028721.jpg | es | carbohydrates_g | 9 | 8, 10, 6 | 100 g | 10 | revision |  |
| data/off/3046920028721.jpg | es | saturated_fat_g | 29 | 30, 18, 16 | 100 g | 30 | revision |  |
| data/off/5053990156009.jpg | it | carbohydrates_g | 54 | 56, 31, 30 | 100 g | 56 | revision |  |
| data/off/8076809573252.jpg | it | carbohydrates_g | 59 | 60, 47, 28 | 100 g | 21.5 | revision |  |
| data/off/8076809573252.jpg | it | sugars_g | 23 | 21.5, 26, 28 | 100 g | 3.3 | revision |  |
| data/off/3046920028721.jpg | es | salt_g | 0.06 | 0.7, 1, 4 | 100 g | 0.7 | multilang_blob |  |
| data/off/5000157024671.jpg | pt | carbohydrates_g | 15.5 | 12.9, 5, 4.7 | 100 g | 12.9 | multilang_blob |  |
| data/off/5000157024671.jpg | pt | sugars_g | 10.3 | 12.9, 5, 4.7 | 100 g | 5 | multilang_blob |  |
| data/off/5410041001204.jpg | de | saturated_fat_g | 9 | 8.4, 7.1, 2.4 | - | - | multilang_blob |  |
| data/off/8000500310427.jpg | pt | carbohydrates_g | 64 | 35.84, 100, 24.83 | - | - | multilang_blob |  |
| data/off/20022464.jpg | es | carbohydrates_g | 32 | 2000, 8400 | - | - | misread |  |
| data/off/20022464.jpg | es | energy_kcal | 571 | 2000, 8400 | - | - | misread |  |
| data/off/20022464.jpg | es | fat_g | 42 | 2000, 8400 | - | - | misread |  |
| data/off/20022464.jpg | es | protein_g | 9.9 | 2000, 8400 | - | - | misread |  |
| data/off/20022464.jpg | es | salt_g | 0.02 | 2000, 8400 | - | - | misread |  |
| data/off/20022464.jpg | es | saturated_fat_g | 26 | 2000, 8400 | - | - | misread |  |
| data/off/20022464.jpg | es | sugars_g | 26 | 2000, 8400 | - | - | misread |  |
| data/off/20171841.jpg | pt | energy_kcal | 373.333 | 319, 243, 100 | 100 g | - | misread |  |
| data/off/3017620425035.jpg | en | sugars_g | 56.3 | 57.5, 80, 30.9 | 100 g, per portion, par portion | - | misread |  |
| data/off/3497917000938.jpg | ja | saturated_fat_g | 2.6 | 1.3, 1, 6.4 | 100 g | - | misread |  |
| data/off/3497917000938.jpg | ja | sugars_g | 3 | 1.3, 1, 6.4 | 100 g | - | misread |  |
| data/off/4056489620938.jpg | es | carbohydrates_g | 1.8 | 0.47, 3.7, 8.6 | 100 g | 15.9 | misread |  |
| data/off/4056489620938.jpg | es | protein_g | 4.6 | 3.7, 8.6, 0.47 | 100 g | 29.6 | misread |  |
| data/off/4056489620938.jpg | es | saturated_fat_g | 1.8 | 0.47, 3.7, 8.6 | 100 g | 8.6 | misread |  |
| data/off/5053990155354.jpg | it | energy_kcal | 525 | 517, 648, 155 | 100 g | 517 | misread |  |
| data/off/6111242100206.jpg | fr | energy_kcal | 78.5 | 100, 140, 15.7 | 100 g | 161 | misread |  |
| data/off/6111242100206.jpg | fr | fat_g | 3.3 | 7.5, 7.6, 15.7 | 100 g | 0.14 | misread |  |
| data/off/6111242100206.jpg | fr | protein_g | 4.2 | 7.5, 7.6, 15.7 | 100 g | 15.7 | misread |  |
| data/off/6111242100206.jpg | fr | salt_g | 0 | 7.5, 7.6, 15.7 | 100 g | - | misread |  |
| data/off/6111242100206.jpg | fr | saturated_fat_g | 2.4 | 7.5, 7.6, 15.7 | 100 g | - | misread |  |
| data/off/6111242100206.jpg | fr | sugars_g | 0 | 7.5, 7.6, 15.7 | 100 g | - | misread |  |
| data/off/6111242100985.jpg | fr | carbohydrates_g | 4.2 | 9.4, 9.6, 9.7 | 100 g | - | misread |  |
| data/off/6111242100985.jpg | fr | fat_g | 6 | 9.4, 9.6, 9.7 | 100 g | - | misread |  |
| data/off/6111242100985.jpg | fr | protein_g | 7.6 | 9.4, 9.6, 9.7 | 100 g | - | misread |  |
| data/off/6111242100985.jpg | fr | salt_g | 0 | 9.4, 9.6, 9.7 | 100 g | - | misread |  |
| data/off/6111242100985.jpg | fr | saturated_fat_g | 3.5 | 9.4, 9.6, 9.7 | 100 g | - | misread |  |
| data/off/6111242100985.jpg | fr | sugars_g | 0 | 9.4, 9.6, 9.7 | 100 g | - | misread |  |
| data/off/6111242100992.jpg | fr | salt_g | 0 | 3, 8, 9.4 | 100 g | - | misread |  |
| data/off/6111242100992.jpg | fr | saturated_fat_g | 0 | 3, 8, 9.4 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | carbohydrates_g | 3.5 | 100 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | energy_kcal | 235 | 100 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | fat_g | 21 | 100 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | protein_g | 8 | 100 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | salt_g | 0.46 | 100 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | saturated_fat_g | 15 | 100 | 100 g | - | misread |  |
| data/off/6111242106949.jpg | fr | sugars_g | 0 | 100 | 100 g | - | misread |  |
| data/off/6111246721261.jpg | fr | carbohydrates_g | 6.1 | 11, 70, 80 | - | - | misread |  |
| data/off/6111246721261.jpg | fr | fat_g | 12 | 11, 70, 80 | - | 11 | misread |  |
| data/off/6111246721261.jpg | fr | protein_g | 7.3 | 11, 70, 80 | - | - | misread |  |
| data/off/6111246721261.jpg | fr | salt_g | 0.1 | 11, 70, 80 | - | - | misread |  |
| data/off/6111246721261.jpg | fr | saturated_fat_g | 7.15 | 11, 70, 80 | - | - | misread |  |
| data/off/6111246721261.jpg | fr | sugars_g | 4 | 11, 70, 80 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | carbohydrates_g | 3.1 | 1 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | energy_kcal | 257 | 1 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | fat_g | 18 | 1 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | protein_g | 10 | 1 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | salt_g | 0 | 1 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | saturated_fat_g | 0 | 1 | - | - | misread |  |
| data/off/6111246721278.jpg | fr | sugars_g | 0 | 1 | - | - | misread |  |
| data/off/6902007505264.jpg | ja | energy_kcal | 32 | 43, 4.1, 1.5 | 100 ml | 43 | misread |  |
| data/off/6902007505264.jpg | ja | saturated_fat_g | 0 | 0, 1, 1.5 | 100 ml | - | misread |  |
| data/off/7622210449283.jpg | fr | saturated_fat_g | 5.6 | 6.3, 4, 3.5 | 100 g | - | misread |  |
