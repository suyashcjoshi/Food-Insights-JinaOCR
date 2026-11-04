# OFF score

Per 100 g, tolerance ±0.5 g (±5 kcal). Truth is Open Food Facts, which can disagree with the pack.

| Language | Images | Carbs correct | Fields correct | wrong | missing |
|---|---|---|---|---|---|
| de | 8 | 38% | 57% (32/56) | 10 | 14 |
| en | 8 | 75% | 80% (45/56) | 3 | 8 |
| es | 8 | 50% | 50% (28/56) | 13 | 15 |
| fr | 8 | 25% | 21% (12/56) | 8 | 36 |
| it | 8 | 62% | 64% (36/56) | 12 | 8 |
| ja | 2 | 0% | 36% (5/14) | 5 | 4 |
| pt | 8 | 50% | 48% (27/56) | 13 | 16 |
| **all** | 50 | 48% | 53% (185/350) | 64 | 101 |

- Verified (panel parsed, no cut-off flag, not looped): 36 of 50 images; field accuracy among them 63%, carbs 61%
- Looped outputs: 1; API errors: 0; not cached: 0
- Tokens in p50/p95: 705/915; out p50/p95: 306/1097
- Latency ms p50/p95: 3439/10682
- cost_est for the whole run: $0.07985
- Of 165 wrong or missing fields, 71 have the OFF value somewhere in the OCR text (parser or column choice may be at fault) and 94 do not (model misread, photo is not that label, or OFF is wrong)
- Model read accuracy (OFF value appears in the OCR text, normalised): 70%
- Panels flagged parse_suspect: 4

## Before / after the parser changes

Before = the parser as of the first full score (frozen in `reports/baseline/`); same 50 images, same cached OCR text, same classifier on both sides.

| | before | after |
|---|---|---|
| Carbs correct | 42% | 48% |
| Fields correct | 51% (179/350) | 53% (185/350) |
| Wrong | 70 | 64 |
| Missing | 101 | 101 |
| Model read accuracy | 70% | 70% |
| Images verified | 39 | 36 |
| Field accuracy among verified | 58% (159/273) | 63% (158/252) |

| Language | before | after |
|---|---|---|
| de | 57% (32/56) | 57% (32/56) |
| en | 79% (44/56) | 80% (45/56) |
| es | 45% (25/56) | 50% (28/56) |
| fr | 21% (12/56) | 21% (12/56) |
| it | 64% (36/56) | 64% (36/56) |
| ja | 36% (5/14) | 36% (5/14) |
| pt | 45% (25/56) | 48% (27/56) |

## Why fields are wrong or missing

Each wrong or missing field gets one cause, first match wins (order below).

| Category | before | after | meaning |
|---|---|---|---|
| shift | 49 | 41 | value sits on another nutrient's row, or the parser gave this value to a neighbour |
| comma | 0 | 0 | decimal comma misread (`1,7` taken as 17 or 7) |
| unit | 3 | 2 | kJ read as kcal, g/mg mixed up, sodium vs salt |
| synonym | 9 | 10 | the value is in the text on a row whose label the parser does not know |
| column | 11 | 12 | the label is known and the value is on its row, but another column was taken |
| truth_disagreement | 8 | 8 | OFF value not in the text and every parsed field is off by a similar small ratio |
| model | 91 | 92 | OFF value is not on this nutrient's row (or at all): misread, dropped, not that label, or OFF is wrong |
| **total** | 171 | 165 | |

A zero-valued OFF field counts as read only if a zero sits on a row of that nutrient. Multi-language blobs with 20+ languages (labels the parser has no synonyms for) land in `synonym`; they are out of scope.

## Per nutrient

| Nutrient | correct | wrong | missing |
|---|---|---|---|
| energy_kcal | 32 | 10 | 8 |
| fat_g | 30 | 8 | 12 |
| saturated_fat_g | 19 | 7 | 24 |
| carbohydrates_g | 24 | 13 | 13 |
| sugars_g | 18 | 9 | 23 |
| protein_g | 29 | 10 | 11 |
| salt_g | 33 | 7 | 10 |

## Wrong values (parsed, outside tolerance)

| Barcode | Lang | Nutrient | OFF | Parsed |
|---|---|---|---|---|
| 3017620425035 | en | carbohydrates_g | 57.5 | 10.6 |
| 3017620425035 | en | protein_g | 6.3 | 57.5 |
| 3017620425035 | en | salt_g | 0.107 | 6.3 |
| 6111246721261 | fr | fat_g | 12.0 | 11.0 |
| 7622210449283 | fr | sugars_g | 32.0 | 69.0 |
| 7622210449283 | fr | protein_g | 6.3 | 4.0 |
| 7622210449283 | fr | salt_g | 0.49 | 6.3 |
| 6111032009665 | fr | fat_g | 1.5 | 188.0 |
| 6111242100206 | fr | energy_kcal | 78.5 | 161.0 |
| 6111242100206 | fr | fat_g | 3.3 | 0.14 |
| 6111242100206 | fr | protein_g | 4.2 | 15.7 |
| 20995553 | de | energy_kcal | 554.0 | 579.0 |
| 20995553 | de | fat_g | 44.2 | 46.8 |
| 20995553 | de | saturated_fat_g | 26.7 | 28.2 |
| 20995553 | de | carbohydrates_g | 19.9 | 21.4 |
| 20995553 | de | protein_g | 11.5 | 10.8 |
| 5411188110835 | de | energy_kcal | 23.0 | 2.0 |
| 5411188110835 | de | fat_g | 1.2 | 12.0 |
| 5411188110835 | de | saturated_fat_g | 0.0 | 2.6 |
| 5411188110835 | de | carbohydrates_g | 2.6 | 0.5 |
| 5411188110835 | de | sugars_g | 2.4 | 0.3 |
| 8410376009392 | pt | saturated_fat_g | 17.0 | 1.7 |
| 8410376009392 | pt | sugars_g | 5.0 | 0.5 |
| 8000500310427 | pt | energy_kcal | 515.0 | 2158.0 |
| 20005733 | pt | carbohydrates_g | 3.7 | 6.8 |
| 3046920028363 | pt | energy_kcal | 584.0 | 530.0 |
| 3046920028363 | pt | sugars_g | 11.0 | 14.0 |
| 3046920028363 | pt | protein_g | 12.5 | 11.0 |
| 5000157024671 | pt | carbohydrates_g | 15.5 | 12.9 |
| 5000157024671 | pt | protein_g | 4.8 | 3.7 |
| 5000157024671 | pt | salt_g | 0.6 | 4.7 |
| 20171841 | pt | carbohydrates_g | 60.0 | 1.5 |
| 20171841 | pt | protein_g | 8.3 | 60.0 |
| 20171841 | pt | salt_g | 1.3 | 2.5 |
| 4056489620938 | es | energy_kcal | 103.0 | 656.0 |
| 4056489620938 | es | fat_g | 8.3 | 51.8 |
| 4056489620938 | es | saturated_fat_g | 1.8 | 8.6 |
| 4056489620938 | es | carbohydrates_g | 1.8 | 15.9 |
| 4056489620938 | es | sugars_g | 0.6 | 3.7 |
| 4056489620938 | es | protein_g | 4.6 | 29.6 |
| 20003166 | es | carbohydrates_g | 58.7 | 1.3 |
| 20003166 | es | protein_g | 13.5 | 0.7 |
| 20003166 | es | salt_g | 0.02 | 10.0 |
| 3046920028721 | es | energy_kcal | 567.0 | 573.0 |
| 3046920028721 | es | carbohydrates_g | 9.0 | 10.0 |
| 3046920028721 | es | sugars_g | 0.49 | 1.0 |
| 3046920028721 | es | salt_g | 0.06 | 0.7 |
| 5053990156009 | it | saturated_fat_g | 3.0 | 31.0 |
| 5053990156009 | it | carbohydrates_g | 54.0 | 6.6 |
| 5053990156009 | it | sugars_g | 0.9 | 56.0 |
| 5053990156009 | it | protein_g | 6.2 | 3.5 |
| 5053990156009 | it | salt_g | 1.0 | 5.9 |
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
