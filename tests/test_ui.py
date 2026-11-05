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

from app import eis, es, main, off, pipeline

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


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    """The real app on a real port, EIS / ES / OFF replaced by in-memory fakes."""
    docs: dict[str, dict] = {}
    mp = pytest.MonkeyPatch()
    call = eis.Call(
        status=200, ms=2900, method="POST", path="/_inference/chat_completion/x",
        request={"messages": ["<image>"]}, text=(FIX / "yogurt_official.md").read_text(),
        usage={"prompt_tokens": 905, "completion_tokens": 386}, finish_reason="stop",
    )  # fmt: skip
    mp.setattr(pipeline, "CAPTURES", tmp_path_factory.mktemp("captures"))
    mp.setattr(eis, "ocr_chat", lambda url, prompt=None, **kw: call)
    mp.setattr(eis, "warmup", lambda: 0.0)
    mp.setattr(off, "lookup", lambda code: None)
    mp.setattr(es, "index_doc", lambda doc: docs.__setitem__(doc["id"], doc))
    mp.setattr(es, "get_doc", lambda doc_id: docs.get(doc_id))
    mp.setattr(
        es,
        "search",
        lambda q, a, lang, ver, size, kind: {"total": len(docs), "hits": list(docs.values())},
    )
    mp.setattr(es, "aggregate", lambda q, a, lang, ver, kind: {"total": len(docs), "allergens": [], "languages": [], "verified": {}})  # fmt: skip
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
            "document.readyState === 'complete' && document.querySelector('#prompt')?.options.length > 0"
        )

    def reload(self) -> None:
        self.call("Page.reload")
        time.sleep(0.3)
        assert self.wait(
            "document.readyState === 'complete' && document.querySelector('#prompt')?.options.length > 0"
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


def test_developer_toggle_and_prompt_choice_survive_a_reload(page):
    assert page.ev("document.body.dataset.dev") == "0"  # off by default
    assert page.ev("document.querySelector('#sheet-dev').hidden") is True

    page.ev("document.querySelector('#dev-open').click()")
    assert page.ev("document.querySelector('#sheet-dev').hidden") is False
    assert (
        page.ev("document.querySelector('#dev-prompt-wrap').hidden") is True
    )  # selector only when on
    page.ev("document.querySelector('#dev-toggle').click()")
    assert page.ev("localStorage.getItem('fi.dev')") == "1"
    assert page.ev("document.querySelector('#dev-prompt-wrap').hidden") is False
    page.ev(
        "(() => { const s = document.querySelector('#prompt'); s.value = 'official'; s.dispatchEvent(new Event('change')); })()"
    )
    assert page.ev("localStorage.getItem('fi.prompt')") == "official"

    page.reload()  # the setting is remembered
    assert page.ev("document.body.dataset.dev") == "1"
    assert page.ev("document.querySelector('#dev-toggle').checked") is True
    assert page.ev("document.querySelector('#prompt').value") == "official"

    page.ev("document.querySelector('#dev-open').click()")
    page.ev("document.querySelector('#dev-toggle').click()")  # and turning it off is remembered too
    page.reload()
    assert page.ev("document.body.dataset.dev") == "0"
    assert page.ev("document.querySelector('#dev-toggle').checked") is False


def test_result_sheet_opens_after_a_read_and_closes_every_way(page, tmp_path):
    photo = tmp_path / "label.jpg"
    Image.new("RGB", (400, 300), "white").save(photo)

    # two tabs only: the result is a sheet, not a tab
    assert page.ev(
        "[...document.querySelectorAll('.tabs button')].map(b => b.textContent.trim())"
    ) == ["Capture", "Library"]
    assert page.ev("document.querySelector('#sheet-result').hidden") is True
    assert page.ev("document.querySelector('#primary').textContent") == "Take photo"

    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden"), (
        "the sheet did not open after the read"
    )
    assert page.ev("document.querySelector('#r-hero .num').textContent") == "27"
    assert page.ev("document.querySelector('#r-verified').textContent") == "Verified"
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
    assert page.ev("document.querySelector('#primary').textContent") == "Take photo"
    assert page.ev("document.querySelector('#preview').hidden") is True

    page.upload("#pick", photo)
    assert page.wait("document.querySelector('#primary').textContent === 'Read label'")
    page.ev("document.querySelector('#primary').click()")
    assert page.wait("!document.querySelector('#sheet-result').hidden")
    page.ev(
        "document.querySelector('#r-library').click()"
    )  # "Open in library" lands on the Library tab
    assert page.wait("document.querySelector('#sheet-result').hidden")
    assert page.ev("document.querySelector('#screen-library').hidden") is False
