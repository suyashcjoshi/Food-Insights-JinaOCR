# Open Food Facts live lookup: 021130077403

Recorded 2026-11-05T00:08:23+00:00 by `scripts/off_live.py`: one GET, same URL, `fields` and User-Agent as `app/off.py`.

## Request

```
GET https://world.openfoodfacts.org/api/v2/product/021130077403.json?fields=code,product_name,lang,nutriments,image_front_url
User-Agent: FoodInsights/0.1
```

Note: this run used the generic User-Agent above because `app/off.py` did not load `.env` when imported on its own (fixed afterwards; the app itself always loaded it through `eis.py`). Both agents were answered normally in a follow-up check.

Barcode check digit (GS1): valid. Client timeout 45 s, redirects followed, no retry.

## Response

HTTP **200** in 1770 ms, 3054 bytes.

```
content-type: application/json; charset=utf-8
server: nginx
```

Top-level keys: `code, product, status, status_verbose`.
`status` = `1`, `status_verbose` = `'product found'`, `code` = `'0021130077403'`.

Outcome for the app: **found**.

### `product` shape (types, short samples)

```json
{
  "code": "string ('0021130077403')",
  "image_front_url": "string ('https://images.openfoodfacts.org/images/'…)",
  "lang": "string ('en')",
  "nutrition_data": "string ('on')",
  "nutrition_data_prepared_per": "string ('100g')",
  "product_name": "string ('Vanilla Lowfat Yogurt')"
}
```

`nutriments` has 99 keys. The ones the app can use (per 100 g):

| key | value | type |
|---|---|---|
| `energy-kcal_100g` | 82.3529411764706 | float |
| `fat_100g` | 0.882352941176471 | float |
| `saturated-fat_100g` | 0.588235294117647 | float |
| `carbohydrates_100g` | 15.2941176470588 | float |
| `sugars_100g` | 11.1764705882353 | float |
| `proteins_100g` | 2.94117647058824 | float |
| `salt_100g` | 0.147058823529412 | float |

### What `app/off.py` reads

- `product_name`: 'Vanilla Lowfat Yogurt'
- `lang`: 'en'
- `nutriments.carbohydrates_100g`: 15.2941176470588
- `image_front_url`: present

Data: Open Food Facts contributors, available under the Open Database License (ODbL).
