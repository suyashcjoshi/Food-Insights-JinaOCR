"""Guess a product name from the reader's Markdown of the FRONT of a pack.

The first readable line is a guess, not a fact: the model can invent words where the frame cuts the
text off. The page always lets the person correct it, and the document records `name_source`.
"""

from __future__ import annotations

import re

from app.ocr import strip_regions

MAX_NAME_CHARS = 60
MIN_LETTERS = 3
_TAGS = re.compile(r"<[^>]+>")
_MARKUP = re.compile(r"(\*\*|__|`|^#{1,6}\s*|^[-*>]\s+)")
_WEIGHT = re.compile(
    r"^\W*(?:net\s*wt\.?|e)?\s*\d+[.,]?\d*\s*(?:g|kg|ml|cl|l|oz|fl\.? ?oz)\b", re.IGNORECASE
)


def _letters(text: str) -> int:
    return sum(ch.isalpha() for ch in text)


def _readable(line: str) -> bool:
    """A line that could be a name: enough letters, not a weight like "500 g" or a lone number."""
    return _letters(line) >= MIN_LETTERS and not _WEIGHT.match(line)


def guess_product_name(markdown: str) -> str | None:
    """The first readable line of the front photo, cleaned of markup and capped in length."""
    for raw in strip_regions(markdown or "").splitlines():
        line = _MARKUP.sub("", _TAGS.sub(" ", raw)).strip(" \t|:-–—")
        line = re.sub(r"\s+", " ", line)
        if _readable(line):
            return line[:MAX_NAME_CHARS].rstrip()
    return None
