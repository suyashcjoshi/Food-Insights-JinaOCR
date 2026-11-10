# Food Insights with Elastic Inference Service (Jina OCR)

Take a photo of a food label. The app reads the nutrition numbers, adds them up against your own daily
limits, and saves them so you can search later, for example "every product that mentions peanuts, in any
language". It reads and adds up. It never gives advice.

<p align="center"><img src="docs/architecture.svg" alt="Architecture: web front end, FastAPI app, Jina OCR on Elastic Inference Service, Elasticsearch Serverless" width="100%"></p>

## How it works

**Extract → Ingest → Search**, all inside Elastic:

1. **Extract**: one call, `POST _inference/document_extraction/.jina-reader`, turns the photo into Markdown.
   Jina OCR does the reading (preview on Elasticsearch Serverless).
2. **Ingest**: the app pulls the numbers out and saves one document per label (`food_labels`) and one entry
   per thing you eat (`food_log`).
3. **Search**: find labels by words, or by meaning with **Search by meaning** ticked. Meaning search uses a
   `semantic_text` field: Elasticsearch embeds the text itself (on Serverless, with
   `.jina-embeddings-v5-text-small`). So "sweet breakfast spread" finds a French *pâte à tartiner* label.

The app is built for a phone, with three tabs: **Capture** (a front photo for the name, a back photo for the
nutrition panel), **Today** (net carbs and calories against limits you set) and **Library** (search, allergen
filter, counts). After a read, the **Result** sheet shows the numbers, lets you fix them by hand, and has
**Add to today**. **Raw request & response** shows the exact API call.

| Capture | Result | Today | Raw request & response | Library |
|---|---|---|---|---|
| <img src="screenshots/capture.png" width="150" alt="The Capture screen: Front and Back photo slots and a viewfinder"> | <img src="screenshots/result.png" width="150" alt="The Result: big net carbs and calories, portions and Add to today"> | <img src="screenshots/today.png" width="150" alt="Today: net carbs in red over the limit, calories, and what was eaten"> | <img src="screenshots/raw.png" width="150" alt="The raw request sent to document_extraction and the JSON response"> | <img src="screenshots/library.png" width="150" alt="The Library: a grid of label photos"> |

The Library photos are Open Food Facts samples.

## What to know

- **Check the numbers against the pack.** They come straight from the model. If one is wrong, edit it; it is
  then marked "edited".
- **Net carbs depend on the label.** US / Canada "Total Carbohydrate" includes fibre, so fibre is subtracted.
  EU / UK "Carbohydrate" already excludes it, so nothing is subtracted. If the format is unclear, the full
  carbohydrate is counted and the app says so.
- **Ingredients and allergens are unverified text.** The model can invent words where the photo is cut off,
  so they are never turned into numbers. Allergen mentions are keywords found in that text, not a safety check.
- **Your limits stay in your browser.** The app only says "over" or "under". It is a demo, not medical advice.

I tried it on 50 Open Food Facts photos in 7 languages: 64% of the values match the database (58% for
carbohydrates), with a median read of 3.1 s. French was the weakest (41%).

## Run it

```bash
cp .env.example .env     # add ES_URL and ES_API_KEY from your Elasticsearch Serverless project
make setup               # install (uses uv)
make fetch-sample        # optional: download the 50 sample photos (needs OFF_USER_AGENT in .env)
make seed                # optional: read them into the Library (50 reads)
make serve               # open http://127.0.0.1:8000
make test                # tests, no network needed
```

This is a demo with no login: run it on your own machine and don't expose it to the internet, because
every page load and every photo makes a paid call to the model. Your project needs the `.jina-reader` endpoint. The first read after a quiet period can take a few minutes
while the model wakes up. The two indices are created on first use; an index from an older version has no
`meaning` field, so delete it and it is recreated.

## Where things are

- `app/`: the backend (`eis.py` calls the model, `parse.py` finds the numbers, `es.py` handles both indices).
- `web/`: the page, plain HTML, CSS and JS, no build step.
- `scripts/`: benchmark and sample-data tools.

## References

- [Document extraction API](https://www.elastic.co/docs/api/doc/elasticsearch-serverless/operation/operation-inference-document-extraction) (the call this app makes)
- [Elastic Inference Service](https://www.elastic.co/docs/explore-analyze/elastic-inference/eis) and [Jina models on EIS](https://www.elastic.co/docs/explore-analyze/machine-learning/nlp/ml-nlp-jina#jina-eis-ocr)
- [jina-ocr-v1 on Hugging Face](https://huggingface.co/jinaai/jina-ocr-v1) and the [paper](https://arxiv.org/abs/2609.03181)
- Search Labs: [jina-ocr-v1 document parsing](https://www.elastic.co/search-labs/blog/ocr-model-jina-ocr-v1-document-parsing), [scanned-PDF RAG with Jina OCR](https://www.elastic.co/search-labs/blog/rag-pipeline-scanned-pdf-jina-ocr)
- [Open Food Facts](https://world.openfoodfacts.org/data): contains data under the Open Database License; product images are CC BY-SA.

## License

The code is MIT licensed. The `jina-ocr-v1` model is separate: **open weights, non-commercial licence**
(CC BY-NC 4.0), not open source. This app does not contain the weights; it calls the model through the
Elastic Inference Service. For commercial use, see the licence on the model's
[Hugging Face page](https://huggingface.co/jinaai/jina-ocr-v1) and the Elastic Inference Service terms.
