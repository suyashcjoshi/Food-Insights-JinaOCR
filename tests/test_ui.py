"""Browser tests for the phone UI (real Chrome over the DevTools protocol, the real app with EIS,
Elasticsearch and Open Food Facts faked). Skipped when no Chrome is installed."""

import json
import shutil
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn
from PIL import Image
from websockets.sync.client import connect

from app import eis, es, main, pipeline

FIX = Path(__file__).parent / "fixtures"
MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def chrome_path() -> str | None:
    if Path(MAC_CHROME).exists():
        return MAC_CHROME
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if found := shutil.which(name):
            return found
    return None


pytestmark = pytest.mark.skipif(chrome_path() is None, reason="Chrome is not installed")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _summary(entries: list[dict], day: str) -> dict:
    mine = [e for e in entries if e["day"] == day]
    return {
        "day": day,
        "entries": mine,
        "totals": {
            "net_carbs_g": round(sum(e.get("net_carbs_g", 0) for e in mine), 1),
            "calories_kcal": round(sum(e.get("calories_kcal", 0) for e in mine)),
            "entries": len(mine),
        },
    }


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The real app on a real port, EIS / ES / OFF replaced by in-memory fakes."""
    docs: dict[str, dict] = {}
    mp = pytest.MonkeyPatch()
    call = eis.Call(
        status=200, ms=2900, method="POST", path="/_inference/document_extraction/.jina-reader",
        request={"input": ["<image>"]}, text=(FIX / "yogurt_official.md").read_text(),
        body={"document_extraction": [{"content": "…", "format": "markdown"}]},
    )  # fmt: skip
    mp.setattr(pipeline, "CAPTURES", tmp_path_factory.mktemp("captures"))
    mp.setattr(eis, "read", lambda url: call)
    mp.setattr(eis, "warmup", lambda: 0.0)
    mp.setattr(es, "index_doc", lambda doc: docs.__setitem__(doc["id"], doc))
    mp.setattr(es, "get_doc", lambda doc_id: docs.get(doc_id))
    mp.setattr(
        es,
        "search",
        lambda q, a, lang, size, kind: {"total": len(docs), "hits": list(docs.values())},
    )
    mp.setattr(es, "aggregate", lambda q, a, lang, kind: {"total": len(docs), "allergens": [], "languages": []})  # fmt: skip
    entries: list[dict] = []
    mp.setattr(es, "update_doc", lambda doc_id, fields: docs[doc_id].update(fields))
    mp.setattr(es, "log_entry", entries.append)
    mp.setattr(
        es,
        "delete_log_entry",
        lambda entry_id: bool([entries.remove(e) for e in list(entries) if e["id"] == entry_id]),
    )
    mp.setattr(es, "day_summary", lambda day: _summary(entries, day))
    port = free_port()
    srv = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(5)
    mp.undo()


class Browser:
    """A headless Chrome page at phone size, driven with CDP."""

    def __init__(self, tmp: Path) -> None:
        port = free_port()
        self.proc = subprocess.Popen(
            [chrome_path(), "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={tmp}",
             "--no-first-run", "--no-sandbox", "--disable-gpu", "--window-size=390,844", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.1)
        self.ws = connect(next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"])
        self.n = 0
        self.call("Page.enable")
        self.call("DOM.enable")
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=390,
            height=844,
            deviceScaleFactor=1,
            mobile=True,
        )

    def call(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("id") == self.n:
                return m.get("result", m.get("error"))

    def ev(self, js: str):
        return self.call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)[
            "result"
        ].get("value")

    def wait(self, js: str, secs: float = 15) -> bool:
        end = time.time() + secs
        while time.time() < end:
            if self.ev(js):
                return True
            time.sleep(0.1)
        return False

    def open(self, url: str) -> None:
        self.call("Page.navigate", url=url)
        assert self.wait(
            "document.readyState === 'complete' && document.querySelector('#primary')?.textContent === 'Take front photo'"
        )

    def reload(self) -> None:
        self.call("Page.reload")
        time.sleep(0.3)
        assert self.wait(
            "document.readyState === 'complete' && document.querySelector('#primary')?.textContent === 'Take front photo'"
        )

    def upload(self, selector: str, path: Path) -> None:
        root = self.call("DOM.getDocument")["root"]["nodeId"]
        node = self.call("DOM.querySelector", nodeId=root, selector=selector)["nodeId"]
        self.call("DOM.setFileInputFiles", files=[str(path)], nodeId=node)

    def close(self) -> None:
        self.proc.terminate()


@pytest.fixture
def page(server, tmp_path):
    b = Browser(tmp_path / "profile")
    b.open(server + "/")
    b.ev("localStorage.clear()")
    b.reload()
    yield b
    b.close()


def test_result_sheet_opens_after_a_read_and_closes_every_way(page, tmp_path):
    photo = tmp_path / "label.jpg"
    Image.new("RGB", (400, 300), "white").save(photo)

    # three tabs: the result is a sheet, not a tab
    assert page.ev(
        "[...document.querySelectorAll('.tabs button')].map(b => b.textContent.trim())"
    ) == ["Capture", "Today", "Library"]
    assert page.ev("document.querySelector('#sheet-result').hidden") is True
    assert page.ev("document.querySelector('#primary').textContent") == "Take front photo"

    page.ev("document.querySelector('#skip-front').click()")  # back photo only
    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden"), (
        "the sheet did not open after the read"
    )
    assert page.ev("document.querySelector('#r-hero .num').textContent") == "27"
    assert page.ev("document.querySelector('#r-read').textContent") == "Read in 2.9 s"
    assert page.ev("document.querySelector('#r-contains').textContent.includes('Milk')") is True

    page.ev("document.querySelector('#r-back').click()")  # the back arrow
    assert page.wait("document.querySelector('#sheet-result').hidden")
    assert (
        page.ev("document.querySelector('#primary').textContent") == "Read label"
    )  # photo is kept

    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    page.ev("document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))")  # Escape
    assert page.wait("document.querySelector('#sheet-result').hidden")

    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    page.ev("document.querySelector('#r-again').click()")  # "Read another label" starts fresh
    assert page.wait("document.querySelector('#sheet-result').hidden")
    assert page.ev("document.querySelector('#primary').textContent") == "Take front photo"
    assert page.ev("document.querySelector('#preview').hidden") is True

    page.ev("document.querySelector('#skip-front').click()")  # back photo only
    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    page.ev(
        "document.querySelector('#r-library').click()"
    )  # "Open in library" lands on the Library tab
    assert page.wait("document.querySelector('#sheet-result').hidden")
    assert page.ev("document.querySelector('#screen-library').hidden") is False


def test_the_result_shows_the_pipeline_and_a_raw_request_and_response_button(page, tmp_path):
    """Extract -> Ingest -> Search is on the Result; the raw API call is one button away, both halves."""
    photo = tmp_path / "label.jpg"
    Image.new("RGB", (400, 300), "white").save(photo)
    page.ev("document.querySelector('#skip-front').click()")  # back photo only
    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    pipe = page.ev("document.querySelector('#r-pipe').textContent")
    assert "Extract" in pipe and "Ingest" in pipe and "saved" in pipe and "Search" in pipe
    for gone in ("#dev-open", "#sheet-dev", "#scan", "#r-verified", "#r-xchip", "#sheet-barcode"):
        assert page.ev(f"document.querySelector('{gone}')") is None, gone

    page.ev("document.querySelector('[data-raw=json]').click()")
    shown_json = page.ev("document.querySelector('#r-raw-body').textContent")
    assert '"carbohydrates_g": 27' in shown_json
    assert "nutrients_verified" not in shown_json and "off_match" not in shown_json
    page.ev("document.querySelector('[data-raw=markdown]').click()")
    assert "Nutrition Facts" in page.ev("document.querySelector('#r-raw-body').textContent")

    assert page.ev("document.querySelector('#r-api').textContent") == "Raw request & response"
    assert page.ev("document.querySelector('#r-api').hidden") is False
    page.ev("document.querySelector('#r-api').click()")
    assert page.ev("document.querySelector('#sheet-raw').hidden") is False
    line = page.ev("document.querySelector('#raw-line').textContent")
    assert line == "POST /_inference/document_extraction/.jina-reader"
    assert '"input"' in page.ev("document.querySelector('#raw-req').textContent")
    assert '"document_extraction"' in page.ev("document.querySelector('#raw-res').textContent")
    page.ev("document.querySelector('#sheet-raw .close').click()")
    assert page.ev("document.querySelector('#sheet-raw').hidden") is True


def test_a_photo_with_no_panel_gets_an_explanation_not_an_empty_table(page, tmp_path, monkeypatch):
    call = eis.Call(
        status=200, ms=1500, method="POST", path="/_inference/document_extraction/.jina-reader", request={},
        text="Fresh apples, Cox's Orange Pippin, 1 kg, grown in Kent.",
    )  # fmt: skip
    monkeypatch.setattr(eis, "read", lambda url: call)
    photo = tmp_path / "apples.jpg"
    Image.new("RGB", (400, 300), "white").save(photo)
    page.ev("document.querySelector('#skip-front').click()")  # back photo only
    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    shown = "(sel) => getComputedStyle(document.querySelector(sel)).display !== 'none'"
    assert page.ev(f"({shown})('#r-nopanel')")
    assert (
        page.ev("document.querySelector('#r-nopanel h2').textContent") == "No nutrition panel found"
    )
    for sel in ("#r-hero", "#r-panel", "#r-basis"):
        assert not page.ev(f"({shown})('{sel}')"), sel
    assert "Fresh apples" in page.ev(
        "document.querySelector('#r-unv').textContent"
    )  # what we read is still shown


def read_back_photo(page, tmp_path):
    """Skip the front photo, give a back photo, read it, wait for the Result."""
    photo = tmp_path / "back.jpg"
    Image.new("RGB", (400, 300), "white").save(photo)
    page.ev("document.querySelector('#skip-front').click()")
    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")


def test_two_photos_front_for_the_name_then_back_for_the_numbers(page, tmp_path):
    front, back = tmp_path / "front.jpg", tmp_path / "back.jpg"
    Image.new("RGB", (400, 300), "white").save(front)
    Image.new("RGB", (400, 300), "white").save(back)
    assert page.ev("document.querySelector('#primary').textContent") == "Take front photo"
    assert page.ev("document.querySelector('#skip-front').hidden") is False
    page.upload("#pick", front)  # goes to the front slot, then moves on to the back
    assert page.wait("document.querySelector('#primary').textContent === 'Take back photo'")
    assert page.ev("document.querySelector('#front-thumb').hidden") is False
    assert page.ev("document.querySelector('#slot-back').getAttribute('aria-pressed')") == "true"
    page.upload("#pick", back)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    assert page.ev("document.querySelector('#r-name').value") != ""  # the name came from the front
    assert page.ev("document.querySelector('#r-thumb-front').hidden") is False


def test_big_net_carbs_and_calories_edit_by_hand_and_add_to_today(page, tmp_path):
    read_back_photo(page, tmp_path)
    figures = page.ev(
        "[...document.querySelectorAll('#r-hero .big')].map(b => b.querySelector('.big-label').textContent)"
    )
    assert figures == ["Net carbs", "Calories"]
    assert page.ev("document.querySelector('#r-hero .num').textContent") == "27"

    page.ev("document.querySelector('#r-edit').click()")  # fix a number by hand
    page.ev("document.querySelector('#e-fiber').value = '7'")
    page.ev("document.querySelector('#r-editor').requestSubmit()")
    assert page.wait("document.querySelector('#r-hero .num').textContent === '20'")  # 27 - 7
    assert "fibre" in page.ev("document.querySelector('#r-edited').textContent")

    page.ev("document.querySelector('#log-plus').click()")  # 1.5 portions
    assert page.ev("document.querySelector('#log-portions').textContent") == "1.5"
    page.ev("document.querySelector('#log-add').click()")
    assert page.wait("!document.querySelector('#log-done').hidden")
    assert (
        page.ev("document.querySelector('#log-totals [data-total=carbs] .num').textContent") == "30"
    )  # 20 x 1.5

    page.ev("document.querySelector('#log-see').click()")
    assert page.wait("!document.querySelector('#screen-today').hidden")
    assert page.wait("document.querySelectorAll('#today-entries .entry').length === 1")
    assert (
        page.ev("document.querySelector('#today-totals [data-total=carbs] .num').textContent")
        == "30"
    )
    assert (
        page.ev("!!document.querySelector('#today-totals .total.over')") is False
    )  # 30 of 100: fine

    page.ev("document.querySelector('#today-entries .remove').click()")
    assert page.wait("document.querySelectorAll('#today-entries .entry').length === 0")
    assert page.ev("document.querySelector('#today-empty').hidden") is False


def test_today_turns_red_over_your_limit_and_the_limits_are_behind_the_gear(page, tmp_path):
    read_back_photo(page, tmp_path)
    page.ev("document.querySelector('#log-add').click()")
    assert page.wait("!document.querySelector('#log-done').hidden")
    page.ev("document.querySelector('#log-see').click()")
    assert page.wait("document.querySelectorAll('#today-entries .entry').length >= 1")
    assert page.ev("!!document.querySelector('#today-totals .total.over')") is False

    page.ev("document.querySelector('#limits-open').click()")  # the limits live behind the gear
    assert page.ev("document.querySelector('#sheet-limits').hidden") is False
    assert page.ev("document.querySelector('#lim-carbs').value") == "100"  # defaults
    assert page.ev("document.querySelector('#lim-kcal').value") == "1800"
    page.ev("document.querySelector('#lim-carbs').value = '10'")
    page.ev("document.querySelector('#limits-save').click()")
    assert page.wait("!!document.querySelector('#today-totals [data-total=carbs].over')")
    assert (
        page.ev("document.querySelector('#today-totals [data-total=carbs] .t-flag').textContent")
        == "Over your limit"
    )
    assert page.ev("!!document.querySelector('#today-totals [data-total=calories].over')") is False
    assert "10" in page.ev("localStorage.getItem('fi.limits')")  # remembered
