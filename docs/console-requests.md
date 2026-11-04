# Console requests — copy, paste, run

All of these run in Kibana → Developer tools → Console (no key needed) or
with curl from a terminal where `ES_URL` and `ES_API_KEY` are set:

```
curl -s "$ES_URL/<path>" -H "Authorization: ApiKey $ES_API_KEY" -H "Content-Type: application/json" -d '<body>'
```

In Console, use a public image URL (Open Food Facts product page → right-click
the nutrition photo → copy image address). Base64 bodies are too long to
paste; use curl or the probe script for those.

---

## 0. Inventory

```
GET _inference/_all
```
Look for `.jina-ocr-v1-chat_completion`. (Use "Filter response" at the
bottom of the output pane, not browser find.)

```
GET _inference/chat_completion/.jina-ocr-v1-chat_completion
```
Save this response: `properties`, `regions`, `release_date` are video frames.

```
GET _inference/_region_policy
```
Expected: 404 `No region policy is configured for this deployment` = default
nearest-region routing.

---

## 1. OCR, non-streaming (the one to use in the app)

```
POST _inference/chat_completion/.jina-ocr-v1-chat_completion
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "image_url", "image_url": { "url": "PASTE_IMAGE_URL" } },
        { "type": "text", "text": "Convert the document to markdown." }
      ]
    }
  ],
  "max_completion_tokens": 2048,
  "temperature": 0
}
```
Expect one JSON with `choices[0].message.content` and `usage`. Run twice;
compare. Default timeout is 120 s, which covers most of a cold start.

## 2. OCR, streaming (what we ran first; keep for the "on the wire" shot)

```
POST _inference/chat_completion/.jina-ocr-v1-chat_completion/_stream
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "image_url", "image_url": { "url": "PASTE_IMAGE_URL" } },
        { "type": "text", "text": "Convert the document to markdown." }
      ]
    }
  ],
  "max_completion_tokens": 2048
}
```
Concatenate `choices[0].delta.content`; `usage` is on the last chunk.

## 3. Grounded prompt variant (same path as 1 or 2)

Replace the text part with:
```
"Transcribe only text that is fully visible in the image. Where text is cut off or unreadable, write […] instead of guessing. Return Markdown."
```
Count inventions in the ingredients block vs the official prompt.

---

## 4. Document extraction — the test that decides the primary API

```
PUT _inference/document_extraction/label-ocr
{
  "service": "elastic",
  "service_settings": { "model_id": "jina-ocr-v1" }
}
```
If 200:

```
POST _inference/document_extraction/label-ocr
{
  "input": {
    "content": { "type": "image", "format": "url", "value": "PASTE_IMAGE_URL" }
  },
  "task_settings": { "output_format": "markdown" }
}
```
Expect `document_extraction[0].content`, `format: "markdown"`.

Base64 variant (curl / script):
```
{
  "input": { "content": { "type": "image", "format": "base64", "value": "data:image/jpeg;base64,..." } },
  "task_settings": { "output_format": "markdown" }
}
```
PDF variant (curl / script):
```
{
  "input": { "content": { "type": "pdf", "format": "base64", "value": "data:application/pdf;base64,..." } }
}
```
Clean up when done, or keep it if it works:
```
DELETE _inference/document_extraction/label-ocr
```

## 5. PDF through chat_completion (expected to fail; record the error)

```
POST _inference/chat_completion/.jina-ocr-v1-chat_completion
{
  "messages": [{ "role": "user", "content": [
    { "type": "file", "file": { "file_data": "data:application/pdf;base64,...", "filename": "label.pdf" } },
    { "type": "text", "text": "Convert the document to markdown." }
  ]}],
  "max_completion_tokens": 2048
}
```

---

## 6. The hammer (frontier LLM, same project, same image)

```
POST _inference/chat_completion/.google-gemini-3.8-flash-chat_completion
{
  "messages": [
    {
      "role": "user",
      "content": [
        { "type": "image_url", "image_url": { "url": "PASTE_IMAGE_URL" } },
        { "type": "text", "text": "Read this nutrition label. Return ONLY JSON with keys energy_kcal, fat_g, saturated_fat_g, carbohydrates_g, sugars_g, protein_g, salt_g or sodium_mg, serving, allergens_raw. Use null when a value is not visible." }
      ]
    }
  ],
  "max_completion_tokens": 600,
  "temperature": 0
}
```
Swap the endpoint id for `.openai-gpt-6-astra-chat_completion` or
`.anthropic-claude-5.5-opus-chat_completion` for a second data point.
Record `usage`, latency, whether the JSON parses, and field accuracy.

---

## 7. curl with your own photo (base64)

```
sips -Z 1600 label.jpg --out label_small.jpg        # macOS resize
B64=$(base64 -i label_small.jpg | tr -d '\n')

curl -s "$ES_URL/_inference/chat_completion/.jina-ocr-v1-chat_completion" \
  -H "Authorization: ApiKey $ES_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"messages\":[{\"role\":\"user\",\"content\":[{\"type\":\"image_url\",\"image_url\":{\"url\":\"data:image/jpeg;base64,$B64\"}},{\"type\":\"text\",\"text\":\"Convert the document to markdown.\"}]}],\"max_completion_tokens\":2048,\"temperature\":0}"
```
(`sips` does not apply EXIF rotation; the Python scripts do.)

---

## 8. Yogurt ground truth (for the probe and parser tests)

Serving 6 oz (170 g), about 5 per container. Calories 150. Total fat 2 g
(3%), saturated 1 g (5%), trans 0 g. Cholesterol 10 mg (3%). Sodium 85 mg
(4%). Total carbohydrate 27 g (10%), dietary fiber 0 g (0%), total sugars
20 g, incl. 18 g added sugars (36%). Protein 6 g. Vitamin D 2 mcg (10%),
calcium 200 mg (15%), iron 0 mg (0%), potassium 260 mg (6%), vitamin A
130 mcg (15%). Barcode 0 21130 07740 3.
Ingredients (visible part): CULTURED PASTEURIZED … MILK, SUGAR, MODIFIED
CORNSTARCH, … SOLIDS, KOSHER GELATIN, NATURAL FL… ACID, POTASSIUM SORBATE
(TO MAINTAIN …) ANNATTO (COLOR), VITAMIN A PALMITATE … CONTAINS LIVE AND
ACTIVE YOGURT CULTURES. CONTAINS: MILK. MAY CONTAIN: TREE NUTS (COCONUT) …
