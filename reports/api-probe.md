# API probe

| # | Check | Result | Status / ms |
|---|---|---|---|
| 1 | inventory lists OCR endpoint | PASS | 200 / 526 ms |
| 2 | OCR endpoint metadata (save for video) | RECORDED | 200 / 94 ms |
| 3 | no region policy (expect 404) | PASS | 404 / 92 ms |
| 4 | non-streaming OCR, temp 0, twice identical | PASS | 200 / 3332 ms, 200 / 2932 ms |
| 5 | streaming equals non-streaming | PASS | 200 / 2765 ms |
| 6 | PUT document_extraction endpoint (decides primary API) | FAIL | 400 / 120 ms |
| 9 | chat_completion with PDF file part (expected to fail) | RECORDED | 400 / 215 ms |
| 10 | official vs grounded prompt: invention count | RECORDED | 200 / 2780 ms, 200 / 5286 ms |
| 11 | hammer: .google-gemini-3.8-flash-chat_completion | DEFERRED | 403 / 159 ms |

## Findings

- **Primary API: non-streaming `chat_completion`.** Check 6 (PUT `document_extraction` for jina-ocr-v1) returned 400 `unsupported model: jina-ocr-v1`, so checks 7 and 8 were skipped.
- **PDFs must be rendered to images client-side.** Check 9: `chat_completion` accepts only `text` and `image_url` content parts; a `file` part returns 400.

### Check 10: invention counts (ingredients paragraph only)

| Prompt | Words not in visible ground truth | Known inventions hit |
|---|---|---|
| official | 5 (FIBER, FOSTERED, IMPROVE, LEVEL, MALTOLACTONE) | FIBER |
| grounded | 6 (CORTICAL, FIBER, FOSTERED, IMPROVE, LEVEL, MALTOLACTONE) | FIBER |

_The count is comparative, not absolute: cut-off words in the ground truth (e.g. `FL`) never match the full word (`FLAVOR`), so some correct words count as unknown. Compare prompts against each other, not against zero._

- **Check 11 (hammer): DEFERRED.** EIS returns 403 Forbidden for third-party LLM endpoints in this org (confirmed from Kibana Console too, so not a key privilege). Not blocking. The hammer script stays in place; if it runs it reports accuracy and output format, with tokens and latency for reference only.
