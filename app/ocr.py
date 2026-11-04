"""OCR post-processing for jina-ocr-v1 output.

Ported in reduced form from a colleague's jina-ocr-v1 demo (`ocr.py`), used with permission:
`strip_regions()` and the distinct-5-gram runaway-repetition detector. Nothing
Frankenstein-specific is carried over.
"""

from __future__ import annotations

import re

# Region tokens such as `image[[24,35,975,975]]` or `<|ref|>…<|/ref|>` leak out of the model,
# especially with the grounded prompt. Strip the coordinate group; drop a line only when it is
# nothing but a label plus a box.
_COORDS = re.compile(r"\[\[\s*\d+(?:\s*,\s*\d+)*\s*\]\]")
_ARTIFACT_LINE = re.compile(r"^\s*[A-Za-z_][\w-]*?\s*\[\[\s*\d+(?:\s*,\s*\d+)*\s*\]\]\s*$")
_REF_TAGS = re.compile(r"<\|/?(?:ref|det|grounding)\|>")

# Runaway guard. EIS rejects repetition_penalty / no_repeat_ngram_size, so a looping page can
# only be bounded by max_completion_tokens and caught afterwards. The colleague measured the
# distinct-5-gram ratio: runaway 0.006, lowest real prose 0.29, lowest real table 0.41.
LOOP_MIN_DISTINCT = 0.10


def strip_regions(text: str) -> str:
    out = []
    for line in (text or "").splitlines():
        if _ARTIFACT_LINE.match(line) or _COORDS.fullmatch(line.strip()):
            continue
        out.append(_REF_TAGS.sub("", _COORDS.sub("", line)))
    s = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    # unwrap a whole-page code fence so it is not rendered as a code block
    m = re.fullmatch(r"```[a-zA-Z]*\n?(.*?)\n?```", s, re.DOTALL)
    return m.group(1).strip() if m else s


def distinct_5gram_ratio(text: str) -> float | None:
    """Fraction of distinct character 5-grams; None when the text is too short to judge."""
    s = re.sub(r"\s+", " ", text or "")
    if len(re.findall(r"\w", s)) < 20:
        return None
    grams = [s[i : i + 5] for i in range(max(1, len(s) - 5))]
    return round(len(set(grams)) / len(grams), 4)


def is_looped(text: str) -> tuple[bool, float | None]:
    ratio = distinct_5gram_ratio(text)
    return (ratio is not None and ratio < LOOP_MIN_DISTINCT, ratio)
