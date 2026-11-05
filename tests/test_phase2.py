"""Phase 2: allergens, OFF cross-check, the ES mapping, and the API with EIS / ES / OFF faked."""

import io
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import eis, es, main, off, pipeline
from app.allergens import ALLERGENS, find_allergens

FIX = Path(__file__).parent / "fixtures"

# --- allergens ---------------------------------------------------------------------------------


def test_fourteen_regulated_allergens():
    assert len(ALLERGENS) == 14


@pytest.mark.parametrize(
    ("text", "want"),
    [
        (
            "INGREDIENTS: MILK, SOY LECITHIN. MAY CONTAIN PEANUTS, TREE NUTS",
            {"milk", "soybeans", "peanuts", "tree_nuts"},
        ),
        (
            "Zutaten: Weizenmehl, Eier, Haselnüsse, Milchpulver, Senf",
            {"gluten", "eggs", "tree_nuts", "milk", "mustard"},
        ),
        (
            "Ingrédients : blé, œuf, lait, moutarde, poisson, moules",
            {"gluten", "eggs", "milk", "mustard", "fish", "molluscs"},
        ),
        (
            "Ingredientes: trigo, huevo, leche, cacahuetes, apio, sésamo, sulfitos",
            {"gluten", "eggs", "milk", "peanuts", "celery", "sesame", "sulphites"},
        ),
        (
            "Ingredientes: ovos, leite, amendoim, tremoços, camarão",
            {"eggs", "milk", "peanuts", "lupin", "crustaceans"},
        ),
        (
            "Ingredienti: frumento, uova, latte, arachidi, sedano, vongole",
            {"gluten", "eggs", "milk", "peanuts", "celery", "molluscs"},
        ),
    ],
    ids=["en", "de", "fr", "es", "pt", "it"],
)
def test_allergen_names_in_six_languages(text, want):
    assert {a["name"] for a in find_allergens(text)} == want


def test_allergens_are_whole_words_and_butter_is_not_milk():
    assert find_allergens("eggplant, cocoa butter, coconut, Eisbein") == []
    assert find_allergens("peanut butter") == [{"name": "peanuts", "kind": "contains"}]
    assert find_allergens("") == []


# --- contains vs may contain ---------------------------------------------------------------------

KINDS = {
    "en": ("CONTAINS: MILK. MAY CONTAIN: PEANUTS, TREE NUTS.", {"milk"}, {"peanuts", "tree_nuts"}),
    "fr": ("Contient : lait. Peut contenir des traces de soja, fruits à coque.", {"milk"}, {"soybeans", "tree_nuts"}),
    "es": ("Contiene: leche. Puede contener trazas de cacahuetes y sésamo.", {"milk"}, {"peanuts", "sesame"}),
    "pt": ("Contém: leite. Pode conter vestígios de amendoim e tremoços.", {"milk"}, {"peanuts", "lupin"}),
    "de": ("Enthält: Milch. Kann Spuren von Haselnüssen und Sellerie enthalten.", {"milk"}, {"tree_nuts", "celery"}),
    "it": ("Contiene: latte. Può contenere tracce di arachidi e sedano.", {"milk"}, {"peanuts", "celery"}),
}  # fmt: skip


@pytest.mark.parametrize("lang", sorted(KINDS))
def test_may_contain_clause_in_six_languages(lang):
    text, contains, may = KINDS[lang]
    found = {a["name"]: a["kind"] for a in find_allergens(text)}
    assert {n for n, k in found.items() if k == "contains"} == contains
    assert {n for n, k in found.items() if k == "may_contain"} == may


def test_the_clause_ends_at_a_full_stop_a_semicolon_or_a_line_break():
    found = {a["name"]: a["kind"] for a in find_allergens("May contain nuts; contains wheat")}
    assert found == {"tree_nuts": "may_contain", "gluten": "contains"}
    found = {a["name"]: a["kind"] for a in find_allergens("May contain nuts\nContains milk")}
    assert found == {"milk": "contains", "tree_nuts": "may_contain"}


def test_an_allergen_named_both_ways_is_contains():
    """Contains wins: a precaution clause must never downgrade a stated ingredient."""
    found = find_allergens("Contains milk and may contain milk traces; wheat")
    assert {"name": "milk", "kind": "contains"} in found
    assert len([a for a in found if a["name"] == "milk"]) == 1


def test_a_wrapped_may_contain_line_over_reports_never_downgrades():
    """The clause stops at the line break, so a wrapped list is `contains`: the safe direction."""
    found = {a["name"]: a["kind"] for a in find_allergens("MAY CONTAIN TRACES OF\nPEANUTS")}
    assert found.get("peanuts") == "contains"


def test_facility_phrases_are_precautionary():
    text = "Made in a facility that also processes peanuts and soy."
    found = {a["name"]: a["kind"] for a in find_allergens(text)}
    assert found == {"peanuts": "may_contain", "soybeans": "may_contain"}


# --- Open Food Facts -----------------------------------------------------------------------------


def test_barcode_checksum():
    assert off.valid_barcode("3017620425035")
    assert off.valid_barcode("20003166")
    assert not off.valid_barcode("3017620425036")
    assert not off.valid_barcode("12345")


def test_barcode_found_in_text_only_if_checksum_passes():
    assert off.find_barcode("EAN 3 017620 425035 best before") == "3017620425035"
    assert off.find_barcode("lot 1234567890123") is None


def _client(status: int, body: dict | None = None) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body or {}))
    )


def test_a_404_is_no_match_not_an_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    assert off.lookup("3017620425035", _client(404)) is None


@pytest.mark.parametrize("status", [503, 429])
def test_a_busy_off_is_an_error_not_a_missing_product(tmp_path, monkeypatch, status):
    """A 429 / 503 says nothing about the product: lookup raises, cross_check reports `error`
    (retryable), never `not_found`. Nothing reaches the capture, which is never blocked."""
    monkeypatch.setattr(off, "CACHE", tmp_path)
    monkeypatch.setitem(off._breaker, "fails", 0)
    monkeypatch.setitem(off._breaker, "open_until", 0.0)
    with pytest.raises(httpx.HTTPStatusError):
        off.lookup("3017620425035", _client(status))
    monkeypatch.setattr(off, "lookup", lambda code: (_ for _ in ()).throw(httpx.HTTPError("busy")))
    assert off.cross_check("3017620425035", 5, "100g")["status"] == "error"


def test_off_status_zero_is_no_match(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    assert off.lookup("3017620425035", _client(200, {"status": 0})) is None


def test_off_product_is_cached_to_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    body = {"status": 1, "product": {"product_name": "Nutella"}}
    assert off.lookup("3017620425035", _client(200, body))["product_name"] == "Nutella"
    assert (tmp_path / "3017620425035.json").exists()
    assert off.lookup("3017620425035", _client(503))["product_name"] == "Nutella"  # from cache


@pytest.mark.parametrize(
    ("carbs", "basis", "status"),
    [(57.5, "100g", "match"), (57.9, "100g", "match"), (30.0, "100g", "mismatch"),
     (27.0, "serving", "not_comparable"), (None, "100g", "not_comparable")],
)  # fmt: skip
def test_cross_check_statuses(monkeypatch, carbs, basis, status):
    product = {"product_name": "Nutella", "nutriments": {"carbohydrates_100g": 57.5}}
    monkeypatch.setattr(off, "lookup", lambda code: product)
    assert off.cross_check("3017620425035", carbs, basis)["status"] == status


def test_cross_check_not_found_and_error(monkeypatch):
    assert off.cross_check(None, 5, "100g")["status"] == "not_found"
    monkeypatch.setattr(off, "lookup", lambda code: None)
    assert off.cross_check("3017620425035", 5, "100g")["status"] == "not_found"

    def boom(code):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(off, "lookup", boom)
    assert off.cross_check("3017620425035", 5, "100g")["status"] == "error"


# --- mapping -------------------------------------------------------------------------------------


def test_mapping_types():
    p = es.MAPPING["properties"]
    num = [v for v in p["nutrients"]["properties"].values() if v["type"] != "keyword"]
    assert all(v["type"] == "float" for v in num)
    assert p["nutrients"]["properties"]["carbohydrates_g"]["type"] == "float"
    assert p["language"]["type"] == "keyword"
    am = p["allergen_mentions"]  # nested: a name keeps its own kind in filters and aggregations
    assert am["type"] == "nested"
    assert am["properties"]["name"]["type"] == am["properties"]["kind"]["type"] == "keyword"
    t = p["telemetry"]["properties"]
    assert [t[k]["type"] for k in ("prompt_tokens", "completion_tokens", "ocr_ms")] == [
        "integer"
    ] * 3
    assert t["cost_est"]["type"] == "float"
    assert t["endpoint"]["type"] == t["prompt_variant"]["type"] == "keyword"


# --- API with everything faked -------------------------------------------------------------------

YOGURT = (FIX / "yogurt_official.md").read_text()


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, format="JPEG")
    return buf.getvalue()


def fake_call(status=200, text=YOGURT) -> eis.Call:
    return eis.Call(
        status=status, ms=3602, method="POST", path="/_inference/chat_completion/x",
        request={"messages": ["<image>"]}, text=text,
        usage={"prompt_tokens": 905, "completion_tokens": 386}, finish_reason="stop", raw="boom",
    )  # fmt: skip


@pytest.fixture
def api(monkeypatch, tmp_path):
    indexed = []
    monkeypatch.setattr(pipeline, "CAPTURES", tmp_path)
    monkeypatch.setattr(eis, "ocr_chat", lambda url, prompt=None, **kw: fake_call())
    monkeypatch.setattr(es, "index_doc", indexed.append)
    monkeypatch.setattr(off, "lookup", lambda code: None)
    client = TestClient(main.app)
    client.indexed = indexed
    return client


def post(api, **form):
    return api.post("/api/capture", files={"image": ("l.jpg", jpeg(), "image/jpeg")}, data=form)


def test_capture_returns_verified_card_unverified_text_and_telemetry(api):
    r = post(api, language="en")
    assert r.status_code == 200
    body = r.json()
    doc = body["doc"]
    assert doc["nutrients"]["carbohydrates_g"] == 27
    assert doc["nutrients_verified"] is True
    assert doc["unverified_text"].startswith("INGREDIENTS")
    assert doc["language"] == "en"
    assert doc["telemetry"]["prompt_tokens"] == 905
    assert doc["telemetry"]["prompt_variant"] == eis.DEFAULT_PROMPT
    assert body["raw"]["prompt"] == eis.PROMPTS[eis.DEFAULT_PROMPT]
    assert body["raw"]["request"]["path"].startswith("/_inference/chat_completion/")
    assert body["image_url"] == f"/captures/{doc['id']}.jpg"
    assert body["indexed"]["ok"] is True
    assert api.indexed[0]["id"] == doc["id"]


def test_capture_extracts_allergen_mentions_from_the_unverified_text_only(api):
    doc = post(api).json()["doc"]
    kinds = {a["name"]: a["kind"] for a in doc["allergen_mentions"]}
    assert kinds["milk"] == "contains"
    assert kinds["tree_nuts"] == "may_contain"  # `MAY CONTAIN: TREE NUTS (CRUSHED)`
    assert "carbohydrates_g" not in doc["unverified_text"].lower()


def test_language_is_never_model_detected(api):
    assert "language" not in post(api).json()["doc"]


def test_capture_survives_an_es_failure(api, monkeypatch):
    def boom(doc):
        raise RuntimeError("cluster unreachable")

    monkeypatch.setattr(es, "index_doc", boom)
    r = post(api)
    assert r.status_code == 200
    assert r.json()["indexed"]["ok"] is False and "unreachable" in r.json()["indexed"]["error"]


def test_capture_reports_an_eis_failure_as_502(api, monkeypatch):
    monkeypatch.setattr(eis, "ocr_chat", lambda url, prompt=None, **kw: fake_call(status=503))
    r = post(api)
    assert r.status_code == 502
    assert r.json()["error"] == "ocr_failed" and r.json()["status"] == 503


def test_capture_rejects_unknown_prompt_and_non_images(api):
    assert post(api, prompt="nope").status_code == 400
    r = api.post("/api/capture", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_the_default_prompt_is_the_table_prompt():
    assert eis.DEFAULT_PROMPT == "table"  # decided on the model-side rows, see docs/decisions.md
    assert "HTML tables" in eis.PROMPTS[eis.DEFAULT_PROMPT]


def test_prompt_variant_is_sent_and_recorded(api, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        eis, "ocr_chat", lambda url, prompt=None, **kw: seen.update(p=prompt) or fake_call()
    )
    doc = post(api, prompt="official").json()["doc"]  # still selectable
    assert seen["p"] == eis.PROMPTS["official"]
    assert doc["telemetry"]["prompt_variant"] == "official"
    doc = post(api).json()["doc"]
    assert seen["p"] == eis.PROMPTS["table"]
    assert doc["telemetry"]["prompt_variant"] == "table"


def test_search_and_aggs_pass_filters_through(api, monkeypatch):
    calls = {}

    def fake_search(q, a, lang, ver, size, kind):
        calls["s"] = (q, a, lang, ver, size, kind)
        return {"total": 0, "hits": []}

    def fake_aggs(q, a, lang, ver, kind):
        calls["g"] = (q, a, lang, ver, kind)
        return {"total": 0, "allergens": []}

    monkeypatch.setattr(es, "search", fake_search)
    monkeypatch.setattr(es, "aggregate", fake_aggs)
    url = "/api/search?q=jam&allergen=peanuts&allergen=milk&language=fr&verified=true"
    assert api.get(url + "&allergen_kind=may_contain").status_code == 200
    assert calls["s"] == ("jam", ["peanuts", "milk"], "fr", True, 24, "may_contain")
    assert api.get("/api/aggs?allergen=peanuts").status_code == 200
    assert calls["g"] == ("", ["peanuts"], None, None, None)
    assert api.get("/api/search?allergen_kind=sometimes").status_code == 400
    assert api.get("/api/aggs?allergen_kind=sometimes").status_code == 400


def test_search_unavailable_is_503_not_a_crash(api, monkeypatch):
    def boom(*a):
        raise RuntimeError("no cluster")

    monkeypatch.setattr(es, "search", boom)
    assert api.get("/api/search").status_code == 503


def test_health_lists_prompts_and_allergen_names(api):
    body = api.get("/api/health").json()
    assert set(body["prompts"]) == {"official", "table"}
    assert len(body["allergen_names"]) == 14


# --- ES query / aggregation shapes --------------------------------------------------------------


def test_allergen_filter_is_a_nested_query_per_allergen_and_kind():
    f = es._filters(["peanuts", "milk"], None, None, "may_contain")
    assert len(f) == 2
    for clause, name in zip(f, ["peanuts", "milk"], strict=True):
        assert clause["nested"]["path"] == "allergen_mentions"
        must = clause["nested"]["query"]["bool"]["filter"]
        assert {"term": {"allergen_mentions.name": name}} in must
        assert {"term": {"allergen_mentions.kind": "may_contain"}} in must


def test_kind_alone_matches_any_allergen_of_that_kind():
    (clause,) = es._filters([], None, None, "contains")
    assert clause["nested"]["query"] == {"term": {"allergen_mentions.kind": "contains"}}


def test_no_allergen_no_kind_adds_no_nested_filter():
    assert es._filters([], "fr", True) == [
        {"term": {"language": "fr"}},
        {"term": {"nutrients_verified": True}},
    ]


def test_allergen_buckets_split_contains_and_may_contain():
    kinds = lambda **kw: {"buckets": [{"key": k, "doc_count": v} for k, v in kw.items()]}
    buckets = [
        {"key": "milk", "doc_count": 5, "kinds": kinds(contains=4, may_contain=1)},
        {"key": "sesame", "doc_count": 2, "kinds": kinds(may_contain=2)},
    ]
    assert es.shape_allergen_buckets(buckets) == [
        {"key": "milk", "count": 5, "contains": 4, "may_contain": 1},
        {"key": "sesame", "count": 2, "contains": 0, "may_contain": 2},
    ]


# --- OFF outage guard ----------------------------------------------------------------------------


def test_off_circuit_breaker_opens_after_repeated_timeouts_and_resets_on_success(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    monkeypatch.setitem(off._breaker, "fails", 0)
    monkeypatch.setitem(off._breaker, "open_until", 0.0)

    def timeout(req):
        raise httpx.ReadTimeout("slow", request=req)

    slow = httpx.Client(transport=httpx.MockTransport(timeout))
    for _ in range(off.BREAKER_FAILS):
        with pytest.raises(httpx.ReadTimeout):
            off.lookup("3017620425035", slow)
    calls = []
    counting = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: calls.append(1) or httpx.Response(200, json={"status": 0})
        )
    )
    with pytest.raises(httpx.ConnectError, match="cooling down"):
        off.lookup("3017620425035", counting)
    assert calls == []  # no request was made while the breaker is open
    assert off.cross_check("3017620425035", 5, "100g")["status"] == "error"

    monkeypatch.setitem(off._breaker, "open_until", 0.0)  # cool-down over
    assert off.lookup("3017620425035", counting) is None
    assert off._breaker["fails"] == 0


def test_a_503_counts_as_a_failure_for_the_breaker(tmp_path, monkeypatch):
    monkeypatch.setattr(off, "CACHE", tmp_path)
    monkeypatch.setitem(off._breaker, "fails", 0)
    monkeypatch.setitem(off._breaker, "open_until", 0.0)
    with pytest.raises(httpx.HTTPStatusError):
        off.lookup("3017620425035", _client(503))
    assert off._breaker["fails"] == 1
    assert off.lookup("3017620425035", _client(404)) is None  # a clean 404 resets it
    assert off._breaker["fails"] == 0


# --- editing a capture and the empty library ----------------------------------------------------


@pytest.fixture
def stored(api, monkeypatch):
    """A saved capture the edit endpoint can find; records what was written."""
    doc = {"id": "abc", "barcode": None, "product_name": None, "language": None,
           "nutrients": {"carbohydrates_g": 27.0, "basis": "100g"}, "off_match": {"status": "not_found"}}  # fmt: skip
    written = {}
    monkeypatch.setattr(es, "get_doc", lambda doc_id: doc if doc_id == "abc" else None)
    monkeypatch.setattr(es, "update_doc", lambda doc_id, fields: written.update(fields))
    api.written = written
    return api


def test_patch_edits_name_and_language(stored):
    r = stored.patch("/api/doc/abc", json={"product_name": "  Greek yogurt ", "language": "EN"})
    assert r.status_code == 200
    assert r.json()["product_name"] == "Greek yogurt" and r.json()["language"] == "en"
    assert stored.written == {"product_name": "Greek yogurt", "language": "en"}


def test_patch_empty_string_clears_a_field(stored):
    stored.patch("/api/doc/abc", json={"product_name": "", "language": ""})
    assert stored.written == {"product_name": None, "language": None}


def test_patch_a_new_barcode_reruns_the_off_check(stored, monkeypatch):
    seen = {}

    def fake_check(code, carbs, basis):
        seen.update(code=code, carbs=carbs, basis=basis)
        return {"status": "match", "carbohydrates_100g": 27.0}

    monkeypatch.setattr(off, "cross_check", fake_check)
    r = stored.patch("/api/doc/abc", json={"barcode": "3 017620 425035"})
    assert r.status_code == 200
    assert seen == {"code": "3017620425035", "carbs": 27.0, "basis": "100g"}
    assert stored.written["barcode"] == "3017620425035"
    assert r.json()["off_match"]["status"] == "match"


def test_patch_rejects_a_bad_barcode_a_bad_language_and_an_unknown_capture(stored):
    assert stored.patch("/api/doc/abc", json={"barcode": "3017620425036"}).status_code == 400
    assert stored.patch("/api/doc/abc", json={"language": "english!"}).status_code == 400
    assert stored.patch("/api/doc/nope", json={"product_name": "x"}).status_code == 404
    assert stored.written == {}


def test_no_index_yet_is_an_empty_library_not_an_error(monkeypatch):
    from elasticsearch import NotFoundError

    def gone(*a, **k):
        raise NotFoundError.__new__(NotFoundError)  # index_not_found_exception

    monkeypatch.setattr(es, "_search", gone)
    monkeypatch.setattr(es, "_aggregate", gone)
    assert es.search("peanut") == {"total": 0, "hits": []}
    assert es.aggregate()["total"] == 0 and es.aggregate()["allergens"] == []
