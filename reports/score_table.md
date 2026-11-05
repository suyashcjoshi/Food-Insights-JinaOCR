# OFF score

Per 100 g, tolerance ±0.5 g (±5 kcal). Truth is Open Food Facts, which can disagree with the pack.

| Language | Images | Carbs correct | Fields correct | wrong | missing |
|---|---|---|---|---|---|
| de | 8 | 62% | 66% (37/56) | 6 | 13 |
| en | 8 | 75% | 75% (42/56) | 1 | 13 |
| es | 8 | 62% | 68% (38/56) | 11 | 7 |
| fr | 8 | 50% | 43% (24/56) | 6 | 26 |
| it | 8 | 62% | 77% (43/56) | 12 | 1 |
| ja (n=2) | 2 | 0% | 36% (5/14) | 5 | 4 |
| pt | 8 | 50% | 54% (30/56) | 13 | 13 |
| **all** | 50 | 58% | 63% (219/350) | 54 | 77 |

- Verified (panel parsed, no cut-off flag, not looped): 43 of 50 images; field accuracy among them 69%, carbs 67%
- Looped outputs: 0; API errors: 0; not cached: 0
- Tokens in p50/p95: 712/922; out p50/p95: 461/803
- Latency ms p50/p95: 4072/8133
- cost_est for the whole run: $0.08678
- Of 131 wrong or missing fields, 52 have the OFF value somewhere in the OCR text (parser or column choice may be at fault) and 79 do not (model misread, photo is not that label, or OFF is wrong)
- Model read accuracy (OFF value appears in the OCR text, normalised): 74%
- Panels flagged parse_suspect: 1
- Read accuracy after triage: 83% (before triage 74%). 29 of 78 `model` misses have a cause where the model read the pack correctly (basis_mismatch, rounding_lt05, revision); 0 causes confirmed by hand, 78 suggested by the heuristic
- Prompt `table`: 49 of 50 outputs contain `<table>`

Languages with fewer than 5 images are listed with their n but left out of `chart` in the JSON (chart data): ja (n=2). Their percentages move 50 points per image.

## Why fields are wrong or missing

Each wrong or missing field gets one cause, first match wins (order below).

| Category | before | after | meaning |
|---|---|---|---|
| shift | - | 20 | value sits on another nutrient's row, or the parser gave this value to a neighbour |
| comma | - | 0 | decimal comma misread (`1,7` taken as 17 or 7) |
| unit | - | 0 | kJ read as kcal, g/mg mixed up, sodium vs salt |
| synonym | - | 11 | the value is in the text on a row whose label the parser does not know |
| column | - | 14 | the label is known and the value is on its row, but another column was taken |
| truth_disagreement | - | 8 | OFF value not in the text and every parsed field is off by a similar small ratio |
| model | - | 78 | OFF value is not on this nutrient's row (or at all): misread, dropped, not that label, or OFF is wrong |
| **total** | - | 131 | |

A zero-valued OFF field counts as read only if a zero sits on a row of that nutrient. Multi-language blobs with 20+ languages (labels the parser has no synonyms for) land in `synonym`; they are out of scope.

## Per nutrient

| Nutrient | correct | wrong | missing |
|---|---|---|---|
| energy_kcal | 33 | 9 | 8 |
| fat_g | 36 | 6 | 8 |
| saturated_fat_g | 25 | 7 | 18 |
| carbohydrates_g | 29 | 12 | 9 |
| sugars_g | 26 | 8 | 16 |
| protein_g | 33 | 8 | 9 |
| salt_g | 37 | 4 | 9 |

## Wrong values (parsed, outside tolerance)

| Barcode | Lang | Nutrient | OFF | Parsed |
|---|---|---|---|---|
| 8000500426494 | en | energy_kcal | 534.0 | 31.8 |
| 6111246721261 | fr | fat_g | 12.0 | 11.0 |
| 6111242100985 | fr | protein_g | 7.6 | 9.7 |
| 6111242100206 | fr | energy_kcal | 78.5 | 161.0 |
| 6111242100206 | fr | fat_g | 3.3 | 7.5 |
| 6111242100206 | fr | carbohydrates_g | 8.0 | 15.7 |
| 6111242100206 | fr | protein_g | 4.2 | 7.6 |
| 20995553 | de | energy_kcal | 554.0 | 579.0 |
| 20995553 | de | fat_g | 44.2 | 46.8 |
| 20995553 | de | saturated_fat_g | 26.7 | 28.2 |
| 20995553 | de | carbohydrates_g | 19.9 | 21.4 |
| 20995553 | de | protein_g | 11.5 | 10.8 |
| 5411188110835 | de | sugars_g | 2.4 | 0.3 |
| 8410376009392 | pt | saturated_fat_g | 17.0 | 1.7 |
| 8410376009392 | pt | sugars_g | 5.0 | 0.5 |
| 20005733 | pt | carbohydrates_g | 3.7 | 6.8 |
| 3046920028363 | pt | energy_kcal | 584.0 | 530.0 |
| 3046920028363 | pt | sugars_g | 11.0 | 14.0 |
| 3046920028363 | pt | protein_g | 12.5 | 11.0 |
| 5000157024671 | pt | carbohydrates_g | 15.5 | 12.9 |
| 5000157024671 | pt | sugars_g | 10.3 | 5.0 |
| 5000157024671 | pt | protein_g | 4.8 | 3.7 |
| 5000157024671 | pt | salt_g | 0.6 | 4.7 |
| 20171841 | pt | carbohydrates_g | 60.0 | 0.3 |
| 20171841 | pt | protein_g | 8.3 | 60.0 |
| 20171841 | pt | salt_g | 1.3 | 2.5 |
| 4056489620938 | es | energy_kcal | 103.0 | 656.0 |
| 4056489620938 | es | fat_g | 8.3 | 51.8 |
| 4056489620938 | es | saturated_fat_g | 1.8 | 8.6 |
| 4056489620938 | es | carbohydrates_g | 1.8 | 15.9 |
| 4056489620938 | es | sugars_g | 0.6 | 3.7 |
| 4056489620938 | es | protein_g | 4.6 | 29.6 |
| 3046920028721 | es | energy_kcal | 567.0 | 573.0 |
| 3046920028721 | es | saturated_fat_g | 29.0 | 30.0 |
| 3046920028721 | es | carbohydrates_g | 9.0 | 10.0 |
| 3046920028721 | es | sugars_g | 0.49 | 1.0 |
| 3046920028721 | es | salt_g | 0.06 | 0.7 |
| 5053990156009 | it | saturated_fat_g | 3.0 | 6.6 |
| 5053990156009 | it | carbohydrates_g | 54.0 | 56.0 |
| 5053990156009 | it | protein_g | 6.2 | 3.5 |
| 5053990156009 | it | salt_g | 1.0 | 5.9 |
| 80052760 | it | carbohydrates_g | 52.0 | 49.5 |
| 5053990155354 | it | energy_kcal | 525.0 | 517.0 |
| 5053990155354 | it | fat_g | 30.0 | 29.0 |
| 5053990155354 | it | saturated_fat_g | 6.4 | 2.9 |
| 5053990155354 | it | sugars_g | 2.7 | 2.1 |
| 8076809573252 | it | saturated_fat_g | 5.0 | 7.5 |
| 8076809573252 | it | carbohydrates_g | 59.0 | 60.0 |
| 8076809573252 | it | sugars_g | 23.0 | 21.5 |
| 3497917000938 | ja | energy_kcal | 525.0 | 542.0 |
| 3497917000938 | ja | fat_g | 31.0 | 34.0 |
| 3497917000938 | ja | carbohydrates_g | 52.0 | 50.0 |
| 6902007505264 | ja | energy_kcal | 32.0 | 43.0 |
| 6902007505264 | ja | carbohydrates_g | 3.8 | 1.5 |
