"""The app: allergens, OFF cross-check, the ES mapping, and the API with EIS / ES / OFF faked."""

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import eis, es, main, pipeline
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


# --- mapping -------------------------------------------------------------------------------------


def test_meaning_search_uses_a_semantic_field_fed_from_plain_text():
    p = es.MAPPING["properties"]
    assert p["meaning"]["type"] == "semantic_text"
    assert p["plain_text"]["copy_to"] == "meaning"
    words = es._query("peanut", [])["bool"]["must"][0]
    meaning = es._query("peanut", [], "meaning")["bool"]["must"][0]
    assert "multi_match" in words
    assert meaning == {"semantic": {"field": "meaning", "query": "peanut"}}
    assert es._query("", [], "meaning")["bool"]["must"] == [{"match_all": {}}]


def test_mapping_types():
    p = es.MAPPING["properties"]
    num = [
        v for v in p["nutrients"]["properties"].values() if v["type"] not in ("keyword", "boolean")
    ]
    assert all(v["type"] == "float" for v in num)
    assert p["nutrients"]["properties"]["carbohydrates_g"]["type"] == "float"
    assert p["language"]["type"] == "keyword"
    am = p["allergen_mentions"]  # nested: a name keeps its own kind in filters and aggregations
    assert am["type"] == "nested"
    assert am["properties"]["name"]["type"] == am["properties"]["kind"]["type"] == "keyword"
    t = p["telemetry"]["properties"]
    assert t["ocr_ms"]["type"] == "integer"
    assert t["endpoint"]["type"] == t["task"]["type"] == "keyword"


# --- API with everything faked -------------------------------------------------------------------

YOGURT = (FIX / "yogurt_official.md").read_text()


def jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(buf, format="JPEG")
    return buf.getvalue()


def fake_call(status=200, text=YOGURT) -> eis.Call:
    return eis.Call(
        status=status, ms=4410, method="POST", path="/_inference/document_extraction/.jina-reader",
        request={"input": ["<image>"]}, text=text, raw="boom",
        body={"document_extraction": [{"content": text, "format": "markdown", "metadata": {"title": "document.jpeg"}}]},
    )  # fmt: skip


@pytest.fixture
def api(monkeypatch, tmp_path):
    indexed = []
    monkeypatch.setattr(pipeline, "CAPTURES", tmp_path)
    monkeypatch.setattr(eis, "read", lambda url: fake_call())
    monkeypatch.setattr(es, "index_doc", indexed.append)
    client = TestClient(main.app)
    client.indexed = indexed
    return client


def post(api, **form):
    return api.post("/api/capture", files={"image": ("l.jpg", jpeg(), "image/jpeg")}, data=form)


def test_capture_returns_fields_unverified_text_and_telemetry(api):
    r = post(api, language="en")
    assert r.status_code == 200
    body = r.json()
    doc = body["doc"]
    assert doc["nutrients"]["carbohydrates_g"] == 27
    assert doc["unverified_text"].startswith("INGREDIENTS")
    assert doc["language"] == "en"
    t = doc["telemetry"]
    assert t["task"] == "document_extraction" and t["endpoint"] == ".jina-reader"
    assert t["ocr_ms"] == 4410
    assert "prompt_tokens" not in t  # the reader reports no usage
    assert body["raw"]["request"]["path"] == "/_inference/document_extraction/.jina-reader"
    # the whole HTTP answer is handed to the page too (the JSON envelope around the markdown)
    assert body["raw"]["response"]["document_extraction"][0]["content"] == body["raw"]["markdown"]
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
    monkeypatch.setattr(eis, "read", lambda url: fake_call(status=503))
    r = post(api)
    assert r.status_code == 502
    assert r.json()["error"] == "ocr_failed" and r.json()["status"] == 503


def post_with_front(api, front: bytes):
    files = {"image": ("l.jpg", jpeg(), "image/jpeg"), "front": ("f.jpg", front, "image/jpeg")}
    return api.post("/api/capture", files=files)


def test_warmup_is_throttled_so_page_loads_do_not_each_cost_a_model_call(api, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_last_warmup", None)
    monkeypatch.setattr(eis, "warmup", lambda: calls.append(1) or 2.0)
    assert api.post("/api/warmup").json() == {"seconds": 2.0}
    assert api.post("/api/warmup").json() == {"seconds": 0.0, "skipped": True}
    assert len(calls) == 1
    monkeypatch.setattr(main, "_last_warmup", main.time.monotonic() - main.WARMUP_GAP_S - 1)
    assert api.post("/api/warmup").json()["seconds"] == 2.0 and len(calls) == 2


def test_retries_stop_at_the_deadline_and_ms_is_the_whole_wait(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(eis.time, "monotonic", lambda: clock["t"])
    monkeypatch.setattr(eis.time, "sleep", lambda s: clock.__setitem__("t", clock["t"] + s))
    attempts = []

    class Slow:
        def request(self, *a, **k):
            attempts.append(1)
            clock["t"] += eis.TIMEOUT_S  # every attempt runs into the timeout
            raise eis.httpx.ReadTimeout("slow")

    monkeypatch.setattr(eis, "client", lambda: Slow())
    call = eis.request("POST", "/_inference/x", {})
    assert len(attempts) == 2 and call.attempts == 2  # a third could pass DEADLINE_S
    assert call.ms == int(clock["t"] * 1000) and clock["t"] <= eis.DEADLINE_S
    assert call.status == 0


def test_an_image_with_far_too_many_pixels_is_a_400(api, monkeypatch):
    def bomb(data, *a, **k):
        raise Image.DecompressionBombError("too big")

    monkeypatch.setattr(pipeline, "prepare_bytes", bomb)
    r = post(api)
    assert r.status_code == 400 and "too many pixels" in r.json()["detail"]


def test_capture_reports_an_unreachable_eis_as_502(api, monkeypatch):
    def down(url):
        raise RuntimeError("cannot reach Elasticsearch: boom")

    monkeypatch.setattr(eis, "read", down)
    r = post(api)
    assert r.status_code == 502 and "cannot reach" in r.json()["detail"]


def test_a_disk_write_failure_is_not_reported_as_a_bad_image(api, monkeypatch, tmp_path):
    (tmp_path / "file").write_text("x")
    monkeypatch.setattr(pipeline, "CAPTURES", tmp_path / "file" / "sub")  # mkdir under a file fails
    r = post(api)
    assert r.status_code == 500 and "could not save" in r.json()["detail"]


def test_a_bad_front_photo_costs_nothing_and_does_not_fail_the_capture(api, monkeypatch):
    calls = []
    monkeypatch.setattr(eis, "read", lambda url: calls.append(url) or fake_call())
    r = post_with_front(api, b"not an image")
    assert r.status_code == 200
    doc = r.json()["doc"]
    assert len(calls) == 1  # only the back photo was read
    assert "front_failed" in doc["parse_flags"] and "front_image_path" not in doc
    assert doc["nutrients"]["carbohydrates_g"] == 27


def test_a_front_read_that_raises_keeps_the_back_read(api, monkeypatch):
    calls = []

    def read(url):
        calls.append(url)
        if len(calls) == 2:  # the front
            raise RuntimeError("cannot reach Elasticsearch: boom")
        return fake_call()

    monkeypatch.setattr(eis, "read", read)
    r = post_with_front(api, jpeg())
    assert r.status_code == 200 and len(calls) == 2
    doc = r.json()["doc"]
    assert "front_failed" in doc["parse_flags"] and doc["nutrients"]["carbohydrates_g"] == 27
    assert api.indexed[0]["id"] == doc["id"]  # the label was still saved


def test_log_and_edit_routes_answer_503_when_elasticsearch_fails(api, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("cluster unreachable")

    label = {"id": "x", "nutrients": {"carbohydrates_g": 10, "basis": "100g"}}
    entry = {"label_id": "x", "portions": 1, "day": "2026-11-10"}
    monkeypatch.setattr(es, "get_doc", boom)
    assert api.post("/api/log", json=entry).status_code == 503
    assert api.patch("/api/doc/x", json={"product_name": "Jam"}).status_code == 503
    assert api.get("/api/doc/x").status_code == 503
    monkeypatch.setattr(es, "get_doc", lambda doc_id: label)
    monkeypatch.setattr(es, "log_entry", boom)
    monkeypatch.setattr(es, "update_doc", boom)
    monkeypatch.setattr(es, "delete_log_entry", boom)
    assert api.post("/api/log", json=entry).status_code == 503
    assert api.patch("/api/doc/x", json={"product_name": "Jam"}).status_code == 503
    assert api.delete("/api/log/abc").status_code == 503


def test_capture_rejects_non_images(api):
    r = api.post("/api/capture", files={"image": ("x.jpg", b"not an image", "image/jpeg")})
    assert r.status_code == 400


def test_search_and_aggs_pass_filters_through(api, monkeypatch):
    calls = {}

    def fake_search(q, a, lang, size, kind, mode="words"):
        calls["s"] = (q, a, lang, size, kind, mode)
        return {"total": 0, "hits": []}

    def fake_aggs(q, a, lang, kind, mode="words"):
        calls["g"] = (q, a, lang, kind, mode)
        return {"total": 0, "allergens": []}

    monkeypatch.setattr(es, "search", fake_search)
    monkeypatch.setattr(es, "aggregate", fake_aggs)
    url = "/api/search?q=jam&allergen=peanuts&allergen=milk&language=fr"
    assert api.get(url + "&allergen_kind=may_contain").status_code == 200
    assert calls["s"] == ("jam", ["peanuts", "milk"], "fr", 24, "may_contain", "words")
    assert api.get("/api/aggs?allergen=peanuts").status_code == 200
    assert calls["g"] == ("", ["peanuts"], None, None, "words")
    assert api.get("/api/search?q=sweet+spread&mode=meaning").status_code == 200
    assert calls["s"][0] == "sweet spread" and calls["s"][-1] == "meaning"
    assert api.get("/api/search?mode=nonsense").status_code == 422
    assert api.get("/api/search?allergen_kind=sometimes").status_code == 400
    assert api.get("/api/aggs?allergen_kind=sometimes").status_code == 400


def test_search_unavailable_is_503_not_a_crash(api, monkeypatch):
    def boom(*a):
        raise RuntimeError("no cluster")

    monkeypatch.setattr(es, "search", boom)
    assert api.get("/api/search").status_code == 503


def test_health_lists_endpoint_and_allergen_names(api, monkeypatch):
    monkeypatch.setenv("EIS_OCR_DOCX_ENDPOINT", ".jina-reader")
    body = api.get("/api/health").json()
    assert body["endpoint"] == ".jina-reader"
    assert len(body["allergen_names"]) == 14


# --- ES query / aggregation shapes --------------------------------------------------------------


def test_allergen_filter_is_a_nested_query_per_allergen_and_kind():
    f = es._filters(["peanuts", "milk"], None, "may_contain")
    assert len(f) == 2
    for clause, name in zip(f, ["peanuts", "milk"], strict=True):
        assert clause["nested"]["path"] == "allergen_mentions"
        must = clause["nested"]["query"]["bool"]["filter"]
        assert {"term": {"allergen_mentions.name": name}} in must
        assert {"term": {"allergen_mentions.kind": "may_contain"}} in must


def test_kind_alone_matches_any_allergen_of_that_kind():
    (clause,) = es._filters([], None, "contains")
    assert clause["nested"]["query"] == {"term": {"allergen_mentions.kind": "contains"}}


def test_no_allergen_no_kind_adds_no_nested_filter():
    assert es._filters([], "fr") == [{"term": {"language": "fr"}}]


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


# --- editing a capture and the empty library ----------------------------------------------------


@pytest.fixture
def stored(api, monkeypatch):
    """A saved capture the edit endpoint can find; records what was written."""
    doc = {"id": "abc", "product_name": None, "language": None,
           "nutrients": {"carbohydrates_g": 27.0, "basis": "100g"}}  # fmt: skip
    written = {}
    monkeypatch.setattr(es, "get_doc", lambda doc_id: doc if doc_id == "abc" else None)
    monkeypatch.setattr(es, "update_doc", lambda doc_id, fields: written.update(fields))
    api.written = written
    return api


def test_patch_edits_name_and_language(stored):
    r = stored.patch("/api/doc/abc", json={"product_name": "  Greek yogurt ", "language": "EN"})
    assert r.status_code == 200
    assert r.json()["product_name"] == "Greek yogurt" and r.json()["language"] == "en"
    assert stored.written == {
        "product_name": "Greek yogurt",
        "name_source": "typed",
        "language": "en",
    }


def test_patch_empty_string_clears_a_field(stored):
    stored.patch("/api/doc/abc", json={"product_name": "", "language": ""})
    assert stored.written == {"product_name": None, "name_source": "typed", "language": None}


def test_patch_rejects_a_bad_language_and_an_unknown_capture(stored):
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


def test_a_photo_with_no_nutrition_panel_is_flagged(api, monkeypatch):
    """A label-less photo is not an error: the read succeeds and the flag says why."""
    text = "Fresh apples, Cox's Orange Pippin, 1 kg, grown in Kent."
    monkeypatch.setattr(eis, "read", lambda url: fake_call(text=text))
    doc = post(api).json()["doc"]
    assert "no_panel" in doc["parse_flags"]
    assert "carbohydrates_g" not in doc["nutrients"]
    assert doc["unverified_text"] == text  # everything we read is shown, as unverified


def test_a_real_panel_is_not_flagged_no_panel(api):
    assert "no_panel" not in post(api).json()["doc"]["parse_flags"]


# --- hand edits to the numbers -------------------------------------------------------------------


def test_patch_edits_the_big_numbers_and_marks_them_edited(stored):
    r = stored.patch("/api/doc/abc", json={"nutrients": {"carbohydrates_g": 31.5, "fiber_g": 4}})
    assert r.status_code == 200
    body = r.json()
    assert body["nutrients"] == {"carbohydrates_g": 31.5, "basis": "100g", "fiber_g": 4}
    assert body["edited_fields"] == ["carbohydrates_g", "fiber_g"]
    assert stored.written["edited_fields"] == ["carbohydrates_g", "fiber_g"]


def test_patch_only_allows_the_carb_fibre_and_calorie_numbers(stored):
    assert stored.patch("/api/doc/abc", json={"nutrients": {"fat_g": 3}}).status_code == 400
    assert stored.patch("/api/doc/abc", json={"nutrients": {"fiber_g": -1}}).status_code == 400
    assert stored.written == {}


# --- the daily log -------------------------------------------------------------------------------


@pytest.fixture
def diary_api(api, monkeypatch):
    label = {"id": "abc", "product_name": "Greek yogurt", "image_path": "captures/abc.jpg",
             "nutrients": {"carbohydrates_g": 27.0, "fiber_g": 4.0, "energy_kcal": 150.0, "basis": "serving", "carb_includes_fibre": True}}  # fmt: skip
    logged = []
    monkeypatch.setattr(es, "get_doc", lambda doc_id: label if doc_id == "abc" else None)
    monkeypatch.setattr(es, "log_entry", logged.append)
    api.logged = logged
    return api


def test_adding_to_today_snapshots_net_carbs_and_calories_times_portions(diary_api):
    r = diary_api.post("/api/log", json={"label_id": "abc", "portions": 2, "day": "2026-11-06"})
    assert r.status_code == 200
    entry = r.json()
    assert entry["net_carbs_g"] == 46.0  # (27 - 4) x 2
    assert entry["calories_kcal"] == 300
    assert entry["net_method"] == "minus_fibre" and entry["day"] == "2026-11-06"
    assert entry["unit_text"] == "serving"
    assert diary_api.logged[0]["label_id"] == "abc"


def test_adding_to_today_rejects_a_bad_day_bad_portions_and_unknown_label(diary_api):
    ok = {"label_id": "abc", "portions": 1, "day": "2026-11-06"}
    assert diary_api.post("/api/log", json={**ok, "day": "tomorrow"}).status_code == 400
    assert diary_api.post("/api/log", json={**ok, "portions": 0}).status_code == 400
    assert diary_api.post("/api/log", json={**ok, "portions": 99}).status_code == 400
    assert diary_api.post("/api/log", json={**ok, "label_id": "nope"}).status_code == 404
    assert diary_api.logged == []


def test_today_returns_the_summary_and_validates_the_day(api, monkeypatch):
    summary = {
        "day": "2026-11-06",
        "entries": [],
        "totals": {"net_carbs_g": 0, "calories_kcal": 0, "entries": 0},
    }
    monkeypatch.setattr(es, "day_summary", lambda day: summary)
    assert api.get("/api/today?day=2026-11-06").json() == summary
    assert api.get("/api/today?day=nope").status_code == 400


def test_removing_an_entry(api, monkeypatch):
    monkeypatch.setattr(es, "delete_log_entry", lambda entry_id: entry_id == "e1")
    assert api.delete("/api/log/e1").status_code == 200
    assert api.delete("/api/log/zzz").status_code == 404


# --- two photos ----------------------------------------------------------------------------------


def test_front_photo_gives_the_product_name_and_is_stored_with_the_label(api, monkeypatch):
    reads = []

    def fake_read(url):
        reads.append(url)
        return fake_call(text="# Chobani Greek Yogurt\n\n500 g") if len(reads) == 2 else fake_call()

    monkeypatch.setattr(eis, "read", fake_read)
    r = api.post(
        "/api/capture",
        files={"image": ("b.jpg", jpeg(), "image/jpeg"), "front": ("f.jpg", jpeg(), "image/jpeg")},
    )
    assert r.status_code == 200
    doc = r.json()["doc"]
    assert doc["product_name"] == "Chobani Greek Yogurt" and doc["name_source"] == "front"
    assert doc["front_image_path"].endswith("_front.jpg")
    assert len(reads) == 2


def test_a_typed_name_wins_over_the_front_photo(api, monkeypatch):
    monkeypatch.setattr(eis, "read", lambda url: fake_call(text="Something else"))
    r = api.post(
        "/api/capture",
        files={"image": ("b.jpg", jpeg(), "image/jpeg"), "front": ("f.jpg", jpeg(), "image/jpeg")},
        data={"product_name": "My yogurt"},
    )
    assert r.json()["doc"]["product_name"] == "My yogurt"
    assert r.json()["doc"]["name_source"] == "typed"
