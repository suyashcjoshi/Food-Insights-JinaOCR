# Kibana demo: Dev Console and Discover

Every request here was run against an Elasticsearch Serverless project (Nov 2026) and returned 200.
Paste the blocks into **Dev Tools → Console**. The ES|QL ones go in **Discover → ES|QL**.

**Want to paste and run?** Use `docs/kibana-console.txt`: one file, plain requests and `#` comments, real
extracted text already in it, no editing. This page explains each step.

Names: the app uses `food_labels` and `food_log`. The Console steps below use `food_labels_demo` so they
never collide with the app's own index. Open Food Facts images: credit them on screen (ODbL data, CC BY-SA
images).

## 1. Is the reader there?

```
GET _inference/_all
```
Look for `"task_type": "document_extraction"` with `"inference_id": ".jina-reader"`. It is preconfigured,
so there is nothing to create.

## 2. Extract: one call, image in, Markdown out

By URL (easiest on screen; this is a German nutrition panel from Open Food Facts):

```
POST _inference/document_extraction/.jina-reader
{
  "input": [
    {
      "content": {
        "type": "image",
        "format": "url",
        "value": "https://images.openfoodfacts.org/images/products/807/680/952/3547/nutrition_de.380.full.jpg"
      }
    }
  ],
  "task_settings": { "parameters": { "preset": "ocr" } }
}
```

To keep the response short on screen, add a filter to the path. It returns only the Markdown (tested with the
preset above): `POST _inference/document_extraction/.jina-reader?filter_path=document_extraction.content`. Without
it you also get `format` and a `metadata` object.

With your own photo (what the app does): `format` is `base64` and `value` is a data URL. Build it in a
terminal and paste it in:

```bash
echo "data:image/jpeg;base64,$(base64 -i data/kitchen/yogurt.jpg)" | pbcopy
```
```
POST _inference/document_extraction/.jina-reader
{
  "input": [
    { "content": { "type": "image", "format": "base64", "value": "data:image/jpeg;base64,PASTE_HERE" } }
  ],
  "task_settings": { "parameters": { "preset": "ocr" } }
}
```

What comes back (checked): `document_extraction` is an array, one item per input, in order. Each item has
`content` (the Markdown), `format` and a `metadata` object that can change, so don't rely on it. There is no
`usage` and nothing is stored. Other labels to try: the French one
`.../611/124/672/1261/nutrition_fr.139.full.jpg` and the English dark chocolate one
`.../304/692/002/9759/nutrition_en.546.full.jpg` (all under `https://images.openfoodfacts.org/images/products/`).

The `task_settings.parameters.preset: "ocr"` line is what the app sends. Images already default to OCR and gave the
same text with and without it when I compared (2 of 3 identical, the third 97.6% similar). A scanned PDF with no
text layer needs the preset: the default call returned an empty result in my probe. Use `"type": "pdf"` for that.

## 3. Store: the OCR call stores nothing, so create an index

`semantic_text` is the only thing needed for search by meaning. No inference endpoint to create: on
Serverless the default is `.jina-embeddings-v5-text-small`.

```
PUT food_labels_demo
{
  "mappings": {
    "properties": {
      "product_name": { "type": "text" },
      "language":     { "type": "keyword" },
      "source_url":   { "type": "keyword" },
      "content":      { "type": "text", "copy_to": "meaning" },
      "meaning":      { "type": "semantic_text" }
    }
  }
}
```

Index the Markdown you got back. Console accepts triple quotes, so paste it as is:

```
PUT food_labels_demo/_doc/pesto-de?refresh=true
{
  "product_name": "Pesto Rosso 200g",
  "language": "de",
  "source_url": "https://images.openfoodfacts.org/images/products/807/680/952/3547/nutrition_de.380.full.jpg",
  "content": """PASTE THE MARKDOWN FROM STEP 2"""
}
```
Repeat for the French and English labels so the search has something to find.

Check the mapping resolved by itself:
```
GET food_labels_demo/_mapping
```
`meaning` shows `"inference_id": ".jina-embeddings-v5-text-small"`.

## 4. Search

By words. Only labels that contain the word match (a German label says "Zucker", not "sugar"):

```
POST food_labels_demo/_search
{
  "query": { "match": { "content": "sugar" } },
  "_source": ["product_name", "language"]
}
```

By meaning. Ranks every label by closeness, any language:

```
POST food_labels_demo/_search
{
  "query": { "semantic": { "field": "meaning", "query": "dark chocolate high in fat" } },
  "_source": ["product_name", "language"]
}
```
In the test the dark chocolate label ranked first (0.73), then the French cheese (0.69), then the pesto (0.66).
With only three labels the ranking says little; seed the 50 sample labels (`make seed`) for a better demo.

Clean up when done:
```
DELETE food_labels_demo
```

## 5. Discover (ES|QL)

Create a data view for `food_labels` if you want classic Discover; for ES|QL just pick **ES|QL** mode.
These use the app's real indices (run a capture first).

Latest labels, with the numbers the app parsed and how long the read took:
```
FROM food_labels
| KEEP product_name, language, nutrients.energy_kcal, nutrients.carbohydrates_g, telemetry.ocr_ms, captured_at
| SORT captured_at DESC
| LIMIT 20
```

Labels per language and the average read time:
```
FROM food_labels
| STATS labels = COUNT(*), avg_ocr_ms = AVG(telemetry.ocr_ms) BY language
```

Search by meaning in ES|QL (same `semantic_text` field):
```
FROM food_labels METADATA _score
| WHERE MATCH(meaning, "high protein snack")
| SORT _score DESC
| KEEP product_name, language, _score
| LIMIT 5
```

What I ate today (change the date). This is the sum the Today tab shows:
```
FROM food_log
| WHERE day == "2026-11-10"
| STATS net_carbs_g = SUM(net_carbs_g), kcal = SUM(calories_kcal), entries = COUNT(*)
```

Classic query bar (KQL) on the `food_labels` data view, for example `language : "de"` or
`telemetry.ocr_ms > 5000`.

## Notes for the recording

- Warm the endpoint before every take: the first call after idle can take minutes. A tiny image is enough.
- Filter the response so it fits on screen: the Markdown in `content` is what matters. The `metadata` object
  can change, so don't dwell on it.
- Failure scene: the French Open Food Facts label (`611/124/672/1261`) came back starting with a Nutri-Score
  commentary ("ce produit se situerait probablement en : Nutri-Score C"). Compare it with the photo before
  you call it invented; if it is not on the pack, that is a ready-made example of why the app keeps such text
  as "unverified".
