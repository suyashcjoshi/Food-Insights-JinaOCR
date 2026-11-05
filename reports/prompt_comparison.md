# Prompt comparison: official vs table

Same 50 OFF images, temperature 0, same parser. `official` = "Convert the document to markdown."; `table` = "Convert the document to markdown. Render nutrition tables as HTML tables."

## Model side (what the prompt controls)

| | official | table | better |
|---|---|---|---|
| Model read accuracy (OFF value is in the text) | 70.6% | 74.3% | table |
| Read accuracy after triage | 80.3% | 82.6% | table |
| `model` misses (value not in the text) | 91 | 78 | table |
| `truth_disagreement` (panel slightly off OFF) | 8 | 8 | = |
| Looped outputs | 1 | 0 | table |
| Outputs with `<table>` | 30 | 49 | = |

Paired over 350 fields: the OFF value is in the `official` text only for **9** fields and in the `table` text only for **22**.

## Cost and speed

| | official | table | better |
|---|---|---|---|
| Prompt tokens p50 / p95 | 705 / 915 | 712 / 922 | = |
| Completion tokens p50 / p95 | 306 / 1097 | 461 / 803 | official |
| Latency ms p50 / p95 | 3439 / 10682 | 4072 / 8133 | official |
| Cost for the run (USD) | 0.0798 | 0.0868 | official |

## Parser side (what code can fix)

Fields lost to the parser, by cause. Fixable in `app/parse.py`; they say nothing about the prompt unless one output shape keeps producing more of them.

| | official | table | better |
|---|---|---|---|
| `shift` | 25 | 20 | table |
| `column` | 9 | 14 | official |
| `synonym` | 10 | 11 | = |
| `unit` | 2 | 0 | table |
| `comma` | 0 | 0 | = |
| **parser-side total** | 46 | 45 | = |

## For reference only (not a decision criterion)

| | official | table | better |
|---|---|---|---|
| Fields correct | 205/350 (58.6%) | 219/350 (62.6%) | table |
| Carbs correct | 56.0% | 58.0% | = |
| Images verified / accuracy among them | 38 / 66.9% | 43 / 69.4% | = |

"better" is "=" when the gap is inside the noise for 50 images (read accuracy 1 point, model misses 2 fields, tokens 20 / 30, latency 250 ms, cost $0.002, parser-side total 3).
