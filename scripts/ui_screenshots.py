"""Screenshots of every UI state at 390x844 (a phone), saved to data/scratch/ui/ (git-ignored).

    uv run python scripts/ui_screenshots.py --base http://127.0.0.1:8000 --empty-base http://127.0.0.1:8001

--base         a running app whose library has labels (Library filled, allergen list)
--empty-base   a running app on an EMPTY index (Library empty). It also does one real read of
               data/kitchen/yogurt.jpg for the Result screens (one EIS call, about $0.002), so point it
               at a throwaway index (ES_INDEX=food_labels_ui_tmp) and delete that index afterwards.

Drives headless Chrome over the DevTools protocol. Prints layout checks as it goes: whether the
Capture screen overflows and whether the Result hero is above the fold.
"""

from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.request
import warnings
from pathlib import Path

from websockets.sync.client import connect

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "scratch" / "ui"  # docs/screenshots/ holds the four that ship in the README
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
W, H = 390, 844


class Page:
    def __init__(self, port: int = 9335) -> None:
        self.proc = subprocess.Popen(
            [
                CHROME, "--headless=new", f"--remote-debugging-port={port}",
                f"--user-data-dir={ROOT / 'data' / 'scratch' / 'chrome-ui'}", "--no-first-run",
                "--disable-gpu", f"--window-size={W},{H}", "about:blank",
            ],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )  # fmt: skip
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                time.sleep(0.2)
        self.ws = connect(
            next(t for t in tabs if t["type"] == "page")["webSocketDebuggerUrl"],
            max_size=80_000_000,
        )
        self.n = 0
        self.problems: list[str] = []
        self.call("Page.enable")
        self.call("Runtime.enable")
        self.call("DOM.enable")
        self.size(W, H, mobile=True)
        self.scheme("light")

    def scheme(self, value: str) -> None:
        self.call(
            "Emulation.setEmulatedMedia",
            features=[{"name": "prefers-color-scheme", "value": value}],
        )

    def call(self, method: str, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv())
            if m.get("method") == "Runtime.consoleAPICalled" and m["params"]["type"] in (
                "error",
                "warning",
            ):
                self.problems.append(
                    " ".join(str(a.get("value", a.get("description"))) for a in m["params"]["args"])
                )
            if m.get("method") == "Runtime.exceptionThrown":
                self.problems.append("EXC " + json.dumps(m["params"]["exceptionDetails"])[:300])
            if m.get("id") == self.n:
                return m.get("result", m.get("error"))

    def ev(self, js: str):
        return self.call("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)[
            "result"
        ].get("value")

    def size(self, w: int, h: int, mobile: bool) -> None:
        self.call(
            "Emulation.setDeviceMetricsOverride",
            width=w,
            height=h,
            deviceScaleFactor=2,
            mobile=mobile,
        )

    def go(self, url: str, settle: float = 1.5) -> None:
        self.call("Page.navigate", url=url)
        time.sleep(settle)

    def wait(self, js: str, secs: float = 90) -> bool:
        t = time.time()
        while time.time() - t < secs:
            if self.ev(js):
                return True
            time.sleep(0.3)
        return False

    def shot(self, name: str) -> None:
        time.sleep(0.5)  # let the sheet animation finish
        data = self.call("Page.captureScreenshot", format="png")["data"]
        (OUT / f"{name}.png").write_bytes(base64.b64decode(data))
        print("saved", f"data/scratch/ui/{name}.png")

    def upload(self, selector: str, path: str) -> None:
        root = self.call("DOM.getDocument")["root"]["nodeId"]
        node = self.call("DOM.querySelector", nodeId=root, selector=selector)["nodeId"]
        self.call("DOM.setFileInputFiles", files=[path], nodeId=node)

    def close(self) -> None:
        self.proc.terminate()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--empty-base", default="http://127.0.0.1:8001")
    ap.add_argument("--yogurt", default=str(ROOT / "data" / "kitchen" / "yogurt.jpg"))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    p = Page()
    try:
        # ---- empty library, then capture, on the empty index ----
        p.go(args.empty_base + "/")
        p.ev("document.querySelector('#dev-toggle') && (localStorage.clear())")
        p.go(args.empty_base + "/")
        p.shot("capture")
        over = p.ev(
            "(() => { const s = document.querySelector('#screen-capture'); return [s.scrollHeight, s.clientHeight]; })()"
        )
        print(
            "capture screen scrollHeight/clientHeight:",
            over,
            "-> fits" if over[0] <= over[1] else "-> OVERFLOWS",
        )
        fh = p.ev("document.querySelector('#finder').getBoundingClientRect().height")
        print(f"viewfinder height {fh:.0f} px of {H} ({fh / H:.0%})")
        p.ev("document.querySelector('[data-tab=library]').click()")
        p.wait("!document.querySelector('#empty').hidden", 20)
        p.shot("library_empty")
        p.ev("document.querySelector('[data-tab=capture]').click()")

        p.upload("#pick", args.yogurt)
        time.sleep(0.8)
        p.shot("capture_photo")
        p.ev("document.querySelector('#why-open').click()")
        p.shot("why_framing")
        p.ev("document.querySelector('#sheet-why .close').click()")
        p.ev("document.querySelector('#scan').click()")
        p.shot("barcode_sheet")
        p.ev("document.querySelector('#backdrop').click()")
        p.ev("document.querySelector('#dev-open').click()")
        p.ev("document.querySelector('#dev-toggle').click()")
        p.shot("developer")
        p.ev(
            "document.querySelector('#dev-toggle').click()"
        )  # off again for the normal result shots
        p.ev("document.querySelector('#backdrop').click()")

        # ---- one real read for the Result sheet ----
        p.ev("document.querySelector('#primary').click()")
        p.shot("capture_reading")
        ok = p.wait("!document.querySelector('#sheet-result').hidden", 180)
        print("result sheet opened:", ok)
        time.sleep(0.8)
        p.shot("result_top")
        fold = p.ev(
            "(() => { const h = document.querySelector('#r-hero').getBoundingClientRect(), "
            "a = document.querySelector('.sheet-actions').getBoundingClientRect(); return [Math.round(h.bottom), Math.round(a.top)]; })()"
        )
        print(
            "result hero bottom / action bar top:",
            fold,
            "-> above the fold" if fold[0] < fold[1] else "-> BELOW THE FOLD",
        )
        p.ev("document.querySelector('#r-scroll').scrollTop = 560")
        p.shot("result_scrolled")
        p.ev("document.querySelector('#r-scroll').scrollTop = 99999")
        p.shot("result_bottom")
        p.ev("document.querySelector('#r-scroll').scrollTop = 0")
        p.ev("document.querySelector('#r-more').click()")
        p.ev("document.querySelector('#r-unv-more').click()")
        p.ev("document.querySelector('#r-scroll').scrollTop = 420")
        p.shot("result_expanded")
        # developer on: the request, the prompt, the re-read button
        p.ev("document.querySelector('#r-back').click()")
        p.ev("document.querySelector('#dev-open').click()")
        p.ev("document.querySelector('#dev-toggle').click()")
        p.ev("document.querySelector('#backdrop').click()")
        p.ev("document.querySelector('#primary').click()")
        p.wait("!document.querySelector('#sheet-result').hidden", 180)
        time.sleep(0.8)
        p.ev("document.querySelector('#r-raw').open = true")
        p.ev("document.querySelector('#r-scroll').scrollTop = 99999")
        p.shot("result_developer")
        p.ev("document.querySelector('#r-back').click()")
        p.ev("localStorage.clear()")

        # ---- filled library on the real index ----
        p.go(args.base + "/")
        p.ev("localStorage.clear()")
        p.ev("document.querySelector('[data-tab=library]').click()")
        p.wait("document.querySelectorAll('.tile').length > 0", 30)
        time.sleep(1.5)
        p.shot("library_filled")
        p.ev("document.querySelector('#lib-scroll').scrollTop = 99999")
        p.shot("library_allergens")
        p.ev("document.querySelector('#lib-scroll').scrollTop = 0")
        # a matched and a mismatched Open Food Facts cross-check, opened from the library
        hits = json.load(urllib.request.urlopen(args.base + "/api/search?size=100&verified=true"))[
            "hits"
        ]
        for status, name in (("match", "result_matched"), ("mismatch", "result_mismatch")):
            doc = next((d for d in hits if d.get("off_match", {}).get("status") == status), None)
            if doc:
                p.ev(f"openDoc('{doc['id']}')")
                p.wait("!document.querySelector('#sheet-result').hidden", 15)
                time.sleep(1.2)
                p.shot(name)
                p.ev("document.querySelector('#r-back').click()")
                time.sleep(0.4)
        # ---- dark mode: the same screens with the dark tokens ----
        p.scheme("dark")
        p.ev("document.querySelector('#lib-scroll').scrollTop = 0")
        p.shot("library_dark")
        p.ev("document.querySelector('[data-tab=capture]').click()")
        p.shot("capture_dark")
        p.ev("document.querySelector('[data-tab=library]').click()")
        p.ev("document.querySelector('.tile').click()")
        p.wait("!document.querySelector('#sheet-result').hidden", 15)
        time.sleep(1)
        p.shot("result_dark")
        p.ev("document.querySelector('#r-back').click()")
        p.scheme("light")
        # ---- desktop: still a phone-width column ----
        p.size(1280, 800, mobile=False)
        time.sleep(0.5)
        p.shot("desktop_column")
        print("console problems:", p.problems or "none")
    finally:
        p.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
