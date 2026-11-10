# Kibana: Dev Console and Discover queries

`docs/kibana-console.txt` has the Console requests in one file: paste it into **Dev Tools → Console** and run
them in order. It uses an index called `food_labels_demo`, so it never touches the app's `food_labels`. This page
explains them and has the Discover (ES|QL) queries for the app's real indices.

Sample labels are Open Food Facts photos (data ODbL, images CC BY-SA). `docs/demo-label.png` is a small
generated label used for the base64 example.

## What each request is

- **Inference API**: `GET _inference/_all`, `POST _inference/document_extraction/.jina-reader` (the OCR call).
- **Index APIs**: `PUT` index (mapping), `PUT` document, `GET _mapping`, `DELETE`.
- **Query DSL** (`_search`): `match` (words) and `semantic` (meaning).
- **ES|QL**: `FROM`, `STATS ... BY`, `WHERE MATCH(...)`. Runs in Discover, or in Console with `POST _query`.

## How the app uses them

| App step | Code | Request |
|---|---|---|
| Read a photo | `eis.read` | `POST _inference/document_extraction/.jina-reader` |
| Create the indices (first write) | `es.ensure_index` | `PUT food_labels` with the mapping |
| Save a label | `es.index_doc` | index a document into `food_labels`, refreshed straight away |
| Search the Library | `es._search` | `_search`: `multi_match` for words, `semantic` for meaning |
| Library counts | `es._aggregate` | `_search` with nested and terms aggregations |
| Add to today | `es.log_entry` | index a document into `food_log` |
| Today's totals | `es.day_summary` | `_search` on `food_log`, term on `day`, sum aggregations |

## 1. Check the reader

```
GET _inference/_all
```
Look for `"task_type": "document_extraction"` with `"inference_id": ".jina-reader"`. It is preconfigured.

## 2. Extract text from an image

```
POST _inference/document_extraction/.jina-reader?filter_path=document_extraction.content
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
The response has one item per input, in order: `content` (the Markdown), `format` and a `metadata` object that
can change. `filter_path` keeps only `content`. Nothing is stored and there is no `usage`.

For a base64 image, set `"format": "base64"` and `"value": "data:image/png;base64,..."`. Build the string from
a file with:
```bash
echo "data:image/jpeg;base64,$(base64 -i photo.jpg)" | pbcopy
```
Images already default to OCR, and the text was the same with and without the `ocr` preset; the app sends it
explicitly. A scanned PDF (`"type": "pdf"`) with no text layer returns an empty result without it.

## 3. Create an index and store the text

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
```
PUT food_labels_demo/_doc/pesto-de?refresh=true
{
  "product_name": "Pesto Rosso 200g",
  "language": "de",
  "source_url": "https://images.openfoodfacts.org/images/products/807/680/952/3547/nutrition_de.380.full.jpg",
  "content": "<the Markdown from step 2, as one JSON string>"
}
```
`content` is the text that words search reads. `copy_to` also feeds it into `meaning`, a `semantic_text` field.
That needs no inference endpoint: on Serverless the default model is `.jina-embeddings-v5-text-small`
(`GET food_labels_demo/_mapping` shows it), and Elasticsearch embeds the text when you index it. The console
file indexes three labels (German, French, English) with real extracted text.

## 4. Search: words or meaning

By words. It matches only labels that contain the word, so "sugar" finds nothing when a label prints "Zucker":
```
POST food_labels_demo/_search
{
  "query": { "match": { "content": "Zucker" } },
  "_source": ["product_name", "language"]
}
```

By meaning. Same API, different query. It compares meaning, so an English question can find a French label:
```
POST food_labels_demo/_search
{
  "query": { "semantic": { "field": "meaning", "query": "fresh dairy cheese" } },
  "_source": ["product_name", "language"]
}
```
Meaning search ranks every label by closeness and does not filter, so compare the scores. The app's default
search is words (typo-tolerant, one language at a time); meaning is a checkbox in the Library.

```
DELETE food_labels_demo
```

## 5. Discover (ES|QL)

Another way to query the same data. In Discover, pick **ES|QL** mode and paste a query. These use the demo index
from the console file; after you have scanned labels in the app, use `food_labels` instead.

List the labels:
```
FROM food_labels_demo
| KEEP product_name, language
| SORT product_name
```

Count the labels per language:
```
FROM food_labels_demo
| STATS labels = COUNT(*) BY language
```

Search by meaning (`MATCH` on the `semantic_text` field runs the semantic query):
```
FROM food_labels_demo METADATA _score
| WHERE MATCH(meaning, "fresh dairy cheese")
| SORT _score DESC
| KEEP product_name, language, _score
| LIMIT 3
```

On the app's own indices, for example the newest labels:
```
FROM food_labels
| SORT captured_at DESC
| LIMIT 20
```
