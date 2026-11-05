# Seed: Open Food Facts sample -> food_labels

Index `food_labels` (existed), source `off`, prompt `table`, 50 images, 118 s, same pipeline as `/api/capture`.

| Outcome | Count |
|---|---|
| indexed | 47 |
| skipped | 3 |

- Verified panels: 40 of 47; looped outputs: 0
- OFF cross-check statuses: {'match': 22, 'mismatch': 6, 'not_comparable': 11, 'not_found': 8}
- Tokens in / out: 33584 / 20561; cost_est $0.0828
- Allergen mentions as read (name:kind): {'gluten:may_contain': 1, 'milk:contains': 2, 'milk:may_contain': 1, 'peanuts:may_contain': 1, 'soybeans:may_contain': 1, 'tree_nuts:may_contain': 1}

## State of the index after the run

The first 3 images were seeded earlier as a trial (the run above skipped them), so the figures above
cover 47 documents. After `seed_off.py --recheck-off` (no OCR) the index holds **50** documents with
`source: off`:

- OFF cross-check: match 25, mismatch 12, not_comparable 13 (panel not per 100 g), not_found 0, error 0.
- Verified panels: 42 of 50.
- During the parallel seed, 8 existing products had come back `not_found` because OFF answered 429/503
  under load, and 3 trial documents had `error` from an OFF outage. `app/off.py` now reports a busy or
  failing OFF as `error` (never `not_found`), and `--recheck-off` re-did all 11.
