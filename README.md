# Food Insights

Take a photo of a food label. The web app reads the nutrition numbers, checks them against a public
database, and saves everything so you can search it later, for example "every product that
mentions peanuts, in any language".

It is a three-step pipeline, **Extract → Ingest → Search**, all inside Elastic:

1. **Extract**: one call to the Elastic Inference Service (EIS) `document_extraction` task
   (`POST _inference/document_extraction/.jina-reader`) turns the photo into Markdown. Jina's OCR
   model does the reading. This task is in preview on Elasticsearch Serverless.
2. **Ingest**: the app parses the numbers and saves one document per photo in an Elasticsearch index
   (`food_labels`). Extraction does not store anything by itself; saving is a separate `index` call.
3. **Search**: the Library searches and counts what you have read.

One key, one bill.

**It reads the label. It never gives advice**: no doses, no "what to eat".

## How it works

```
  BROWSER (web/)               YOUR APP (FastAPI)                 CLOUD
 ┌──────────────┐  photo   ┌──────────────────────────┐
 │ Capture      │ ───────▶ │ 1  rotate + shrink       │
 │ Result       │          │ 2  EXTRACT  ─────────────┼──▶ Elastic Inference Service
 │ Library      │          │    (app/eis.py)          │    (document_extraction) ──┐
 │              │          │ 3  find the numbers  ◀───┼──────────── Markdown ──────┘
 │              │ ◀─────── │    (app/parse.py)        │
 │              │  result  │ 4  INGEST  ──────────────┼──▶ Elasticsearch  (index food_labels)
 │              │          │                          │
 │              │ search ─▶│ SEARCH  /api/search ─────┼──▶ Elasticsearch  (the Library)
 └──────────────┘          └──────────────────────────┘
```

It is built for a phone (and shows as a phone-width column on a laptop). Two tabs: **Capture** (take or
pick a photo) and **Library** (search what you have read, filter by allergen, see counts). After a
read, the **Result** opens as a sheet: the carbohydrate number next to the photo, the other numbers,
and the unverified text, with the Extract → Ingest → Search strip under the name. Name and language can be edited there, and the **Raw request & response** button shows the exact API call.

| Capture | Result | Raw request & response | Library |
|---|---|---|---|
| <img src="screenshots/capture.png" width="180" alt="The Capture screen: a viewfinder frame and a Take photo button"> | <img src="screenshots/result.png" width="180" alt="The Result sheet: 27 g carbohydrate, the nutrient rows and the Extract, Ingest, Search strip"> | <img src="screenshots/raw.png" width="180" alt="The raw request sent to document_extraction and the JSON response that came back"> | <img src="screenshots/library.png" width="180" alt="The Library: a three-column grid of label photos"> |

The Library photos are Open Food Facts samples (see References).

## What you can trust

- **Nutrition numbers** come straight from what the model read, and the photo is always shown next
  to them: check them against the pack.
- **Ingredients and allergens** are shown as **unverified text**. The model guesses at anything cut
  off by the edge of the photo, so we never turn that text into numbers.
- **Allergen mentions** are keywords found in that text (the 14 EU allergens, in English, French,
  Spanish, Portuguese, German and Italian), marked **contains** or **may contain**, and always
  labelled "as read". It is not a safety check.
- **Extracted text and the raw API call**: on every Result, *Extracted text* shows what the model wrote
  (Markdown) and what the app made of it (JSON), and the **Raw request & response** button shows the exact
  HTTP request sent to the Elastic Inference Service and the JSON that came back.

## How well does it read?

I tried it on 50 Open Food Facts photos in 7 languages: 64% of the values and 58% of the carbohydrate figures match the database. The model puts the right number in its text about 75% of the time (median read 3.1 s, no loops, no errors). The remaining gap is parser work and the database disagreeing with the pack. French was the weakest (41%). Well-framed photos of your own read cleanly.

## Run it

```bash
cp .env.example .env     # add ES_URL and ES_API_KEY from your Elasticsearch Serverless project
make setup               # install (uses uv)
make seed                # optional: read the 50 sample photos into the Library (about $0.09)
make serve               # open http://127.0.0.1:8000
make test                # tests, no network needed
```

The first read after a quiet period can take a few minutes while the model wakes up.

`document_extraction` is in preview on Elasticsearch Serverless: your project needs the `.jina-reader`
endpoint. At the time of writing the response has no token counts (that may change), so the app shows read time and nothing about cost.

## Where things are

| | |
|---|---|
| `app/` | the backend: `eis.py` (model calls), `parse.py` (numbers), `allergens.py`, `off.py`, `es.py`, `pipeline.py`, `main.py` |
| `web/` | the page: `index.html`, `style.css`, and `js/` (four ES modules: `main.js` tabs, capture and wiring; `result.js`; `library.js`; `util.js` helpers and state; no build step) |
| `scripts/` | tools: `score.py` (benchmark against Open Food Facts), `seed_off.py`, `fetch_off_sample.py`, `smoke_test.py` |

## References

**Model**
- Document extraction API (the call this app makes): https://www.elastic.co/docs/api/doc/elasticsearch-serverless/operation/operation-inference-document-extraction
- jina-ocr-v1 on Hugging Face (weights, model card, CC BY-NC 4.0): https://huggingface.co/jinaai/jina-ocr-v1
- Paper: *Jina-OCR-v1: Efficient Document Parsing with Speculative Decoding and Dense Verifiable Rewards*: https://arxiv.org/abs/2609.03181
- Release post: https://jina.ai/news/jina-ocr-v1-faster-document-parsing-on-low-budget-gpus/

**Elastic**
- Elasticsearch API reference: https://www.elastic.co/docs/api/doc/elasticsearch
- Elastic Inference Service: https://www.elastic.co/docs/explore-analyze/elastic-inference/eis
- Jina models on EIS, OCR section: https://www.elastic.co/docs/explore-analyze/machine-learning/nlp/ml-nlp-jina#jina-eis-ocr
- Serverless pricing (Inference rows): https://cloud.elastic.co/cloud-pricing-table?productType=serverless&solution=elasticsearch
- Search Labs: jina-ocr-v1 document parsing: https://www.elastic.co/search-labs/blog/ocr-model-jina-ocr-v1-document-parsing
- Search Labs: scanned-PDF RAG pipeline with Jina OCR: https://www.elastic.co/search-labs/blog/rag-pipeline-scanned-pdf-jina-ocr

**Data**
- Open Food Facts, data and licence: https://world.openfoodfacts.org/data
  Contains data from Open Food Facts, available under the Open Database License. Product images are CC BY-SA.

## License

The code in this repository is MIT licensed. The model is separate: the `jina-ocr-v1` weights are
published on Hugging Face under **CC BY-NC 4.0**, which makes it **open weights with a
non-commercial licence**, not open source. This app does not contain the weights; it calls the
model through the Elastic Inference Service. For commercial use of the model, see the licence on its
[Hugging Face page](https://huggingface.co/jinaai/jina-ocr-v1) (it points to Jina's sales contact)
and the Elastic Inference Service terms.
