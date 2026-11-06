"""Elasticsearch side: the `food_labels` mapping, index, search and aggregations.

The official `elasticsearch` client is used only here (index / search / aggs); every call to
`_inference/*` goes through httpx in `eis.py`. Nutrients and telemetry are numbers, language and
allergen_mentions are keywords, so one terms aggregation answers "which allergens, how often".
"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv
from elasticsearch import Elasticsearch, NotFoundError

load_dotenv()

KINDS = ("contains", "may_contain")
SEARCH_FIELDS = ["product_name^3", "plain_text", "unverified_text"]  # product name counts triple
HIGHLIGHT = {
    "fields": {"plain_text": {}, "unverified_text": {}},
    "pre_tags": ["<mark>"],
    "post_tags": ["</mark>"],
    "fragment_size": 120,
    "number_of_fragments": 1,
}
NOT_RETURNED = ["raw_markdown", "plain_text"]  # big, and the Library does not show them
AGG_SIZE = 20  # most allergens / languages a Library panel lists
EMPTY_AGGS = {"total": 0, "allergens": [], "languages": []}

# --- the mapping -------------------------------------------------------------------------------

NUTRIENT_FIELDS = (
    "energy_kcal",
    "energy_kj",
    "fat_g",
    "saturated_fat_g",
    "trans_fat_g",
    "carbohydrates_g",
    "sugars_g",
    "added_sugars_g",
    "fiber_g",
    "protein_g",
    "salt_g",
    "sodium_mg",
    "cholesterol_mg",
    "vitamin_d_mcg",
    "calcium_mg",
    "iron_mg",
    "potassium_mg",
    "vitamin_a_mcg",
)

MAPPING = {
    "properties": {
        "id": {"type": "keyword"},
        "captured_at": {"type": "date"},
        "source": {"type": "keyword"},  # kitchen | off | demo
        "image_path": {"type": "keyword"},
        "product_name": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
        "language": {"type": "keyword"},  # user-set or from OFF; never model-detected
        "nutrients": {
            "properties": {
                **{k: {"type": "float"} for k in NUTRIENT_FIELDS},
                "serving_text": {"type": "keyword"},
                "per": {"type": "keyword"},  # serving | 100g
                "basis": {"type": "keyword"},  # 100g | 100ml | serving | unknown
            }
        },
        "parse_flags": {"type": "keyword"},
        "unverified_text": {"type": "text"},
        # allergen words as read in unverified_text, one entry per allergen; nested so that a
        # name keeps its own kind (contains | may_contain) in filters and aggregations
        "allergen_mentions": {
            "type": "nested",
            "properties": {"name": {"type": "keyword"}, "kind": {"type": "keyword"}},
        },
        "source_url": {"type": "keyword"},
        "front_image_path": {"type": "keyword"},  # the optional front-of-pack photo
        "name_source": {
            "type": "keyword"
        },  # front | typed (a guess from the front, or what you typed)
        "edited_fields": {"type": "keyword"},  # numbers a person corrected by hand
        "raw_markdown": {"type": "text"},
        "plain_text": {"type": "text"},
        "telemetry": {
            "properties": {
                "endpoint": {"type": "keyword"},
                "task": {"type": "keyword"},
                "ocr_ms": {"type": "integer"},
                "front_ocr_ms": {"type": "integer"},
            }
        },
    }
}

# One entry per thing eaten: a snapshot of the label's numbers times the portions (see diary.py).
LOG_MAPPING = {
    "properties": {
        "id": {"type": "keyword"},
        "label_id": {"type": "keyword"},
        "product_name": {"type": "text", "fields": {"raw": {"type": "keyword"}}},
        "image_path": {"type": "keyword"},
        "day": {"type": "keyword"},  # the person's local date, e.g. 2026-11-06
        "eaten_at": {"type": "date"},
        "portions": {"type": "float"},
        "basis": {"type": "keyword"},
        "net_carbs_g": {"type": "float"},
        "calories_kcal": {"type": "float"},
        "fiber_read": {"type": "boolean"},
        "edited": {"type": "boolean"},
    }
}
LOG_ENTRIES_SIZE = 200
# Writes refresh the index straight away (0.9 s) instead of waiting for the next scheduled refresh
# (about 5 s on Serverless), so a label or a log entry shows up the moment it is saved. Fine at demo
# volumes; a busy production app would batch writes and not refresh on each one.


# --- connection and single-document calls ------------------------------------------------------


def index_name() -> str:
    return os.getenv("ES_INDEX", "food_labels")


@lru_cache(maxsize=1)
def client() -> Elasticsearch:
    url, key = os.getenv("ES_URL", ""), os.getenv("ES_API_KEY", "")
    if not url or not key:
        raise RuntimeError("ES_URL and ES_API_KEY must be set in .env")
    return Elasticsearch(url, api_key=key, request_timeout=30)


def ensure_index() -> bool:
    """Create the index with the mapping if missing. True when it was created."""
    es, name = client(), index_name()
    if es.indices.exists(index=name):
        return False
    es.indices.create(index=name, mappings=MAPPING)
    return True


def index_doc(doc: dict) -> None:
    ensure_index()
    client().index(index=index_name(), id=doc["id"], document=doc, refresh=True)


def update_doc(doc_id: str, fields: dict) -> None:
    """Merge `fields` into an existing document (a name or language edit)."""
    client().update(index=index_name(), id=doc_id, doc=fields, refresh=True)


def log_index_name() -> str:
    return os.getenv("ES_LOG_INDEX", "food_log")


def ensure_log_index() -> bool:
    es, name = client(), log_index_name()
    if es.indices.exists(index=name):
        return False
    es.indices.create(index=name, mappings=LOG_MAPPING)
    return True


def get_doc(doc_id: str) -> dict | None:
    try:
        return client().get(index=index_name(), id=doc_id)["_source"]
    except NotFoundError:
        return None


# --- queries -----------------------------------------------------------------------------------


def _nested_allergen(query: dict) -> dict:
    return {"nested": {"path": "allergen_mentions", "query": query}}


def _filters(allergens: list[str], language: str | None, kind: str | None = None) -> list[dict]:
    """Every named allergen must be present (AND); `kind` limits them to contains / may_contain."""
    out: list[dict] = []
    for a in allergens:
        must = [{"term": {"allergen_mentions.name": a}}]
        if kind in KINDS:
            must.append({"term": {"allergen_mentions.kind": kind}})
        out.append(_nested_allergen({"bool": {"filter": must}}))
    if kind in KINDS and not allergens:  # "anything that contains / may contain something"
        out.append(_nested_allergen({"term": {"allergen_mentions.kind": kind}}))
    if language:
        out.append({"term": {"language": language}})
    return out


def _query(q: str, filters: list[dict]) -> dict:
    """Text match (typo-tolerant) when `q` is given, everything otherwise; `filters` never score."""
    text = {"multi_match": {"query": q, "fields": SEARCH_FIELDS, "fuzziness": "AUTO"}}
    return {"bool": {"must": [text] if q.strip() else [{"match_all": {}}], "filter": filters}}


# --- search and aggregations (the Library) -----------------------------------------------------


def _search(
    q: str = "",
    allergens: list[str] | None = None,
    language: str | None = None,
    size: int = 24,
    kind: str | None = None,
) -> dict:
    """Keyword search with optional allergen / kind / language filters."""
    body = client().search(
        index=index_name(),
        query=_query(q, _filters(allergens or [], language, kind)),
        sort=[{"_score": "desc"}, {"captured_at": "desc"}]
        if q.strip()
        else [{"captured_at": "desc"}],
        highlight=HIGHLIGHT,
        source_excludes=NOT_RETURNED,
        size=size,
    )
    hits = [
        {**h["_source"], "_score": h.get("_score"), "highlight": h.get("highlight", {})}
        for h in body["hits"]["hits"]
    ]
    return {"total": body["hits"]["total"]["value"], "hits": hits}


def shape_allergen_buckets(buckets: list[dict]) -> list[dict]:
    """Terms buckets (name -> kind sub-buckets) to `{key, count, contains, may_contain}` rows.
    There is one nested entry per allergen per capture, so `count` is a number of captures."""
    out = []
    for b in buckets:
        kinds = {k["key"]: k["doc_count"] for k in b.get("kinds", {}).get("buckets", [])}
        out.append(
            {
                "key": b["key"],
                "count": b["doc_count"],
                "contains": kinds.get("contains", 0),
                "may_contain": kinds.get("may_contain", 0),
            }
        )
    return out


def _aggregate(
    q: str = "",
    allergens: list[str] | None = None,
    language: str | None = None,
    kind: str | None = None,
) -> dict:
    """Counts for the Library panel: allergen mentions as read (split contains / may contain),
    languages."""
    body = client().search(
        index=index_name(),
        query=_query(q, _filters(allergens or [], language, kind)),
        size=0,
        aggs={
            "allergens": {
                "nested": {"path": "allergen_mentions"},
                "aggs": {
                    "names": {
                        "terms": {"field": "allergen_mentions.name", "size": AGG_SIZE},
                        "aggs": {"kinds": {"terms": {"field": "allergen_mentions.kind"}}},
                    }
                },
            },
            "languages": {"terms": {"field": "language", "size": AGG_SIZE}},
        },
    )
    aggs = body["aggregations"]
    return {
        "total": body["hits"]["total"]["value"],
        "allergens": shape_allergen_buckets(aggs["allergens"]["names"]["buckets"]),
        "languages": [
            {"key": b["key"], "count": b["doc_count"]} for b in aggs["languages"]["buckets"]
        ],
    }


# `search` / `aggregate` are what the API calls: before the first capture there is no index, which
# is an empty library and not an error.


def search(*args, **kwargs) -> dict:
    """Keyword search (see `_search`)."""
    try:
        return _search(*args, **kwargs)
    except NotFoundError:
        return {"total": 0, "hits": []}


def aggregate(*args, **kwargs) -> dict:
    """Counts for the Library panel (see `_aggregate`); an empty library before the first capture."""
    try:
        return _aggregate(*args, **kwargs)
    except NotFoundError:
        return dict(EMPTY_AGGS)


# --- the daily log -------------------------------------------------------------------------------


def log_entry(entry: dict) -> None:
    ensure_log_index()
    client().index(index=log_index_name(), id=entry["id"], document=entry, refresh=True)


def delete_log_entry(entry_id: str) -> bool:
    """True when an entry was removed."""
    try:
        client().delete(index=log_index_name(), id=entry_id, refresh=True)
    except NotFoundError:
        return False
    return True


def day_summary(day: str) -> dict:
    """Everything eaten on `day`, oldest first, with the day's totals from one aggregation."""
    empty = {
        "day": day,
        "entries": [],
        "totals": {"net_carbs_g": 0, "calories_kcal": 0, "entries": 0},
    }
    try:
        body = client().search(
            index=log_index_name(),
            query={"term": {"day": day}},
            sort=[{"eaten_at": "asc"}],
            size=LOG_ENTRIES_SIZE,
            aggs={
                "net_carbs": {"sum": {"field": "net_carbs_g"}},
                "calories": {"sum": {"field": "calories_kcal"}},
            },
        )
    except NotFoundError:  # before the first entry there is no log index: an empty day
        return empty
    aggs = body["aggregations"]
    return {
        "day": day,
        "entries": [hit["_source"] for hit in body["hits"]["hits"]],
        "totals": {
            "net_carbs_g": round(aggs["net_carbs"]["value"] or 0, 1),
            "calories_kcal": round(aggs["calories"]["value"] or 0),
            "entries": body["hits"]["total"]["value"],
        },
    }
