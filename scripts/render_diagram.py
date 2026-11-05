"""Render docs/architecture.mmd to docs/architecture.svg.

    uv run python scripts/render_diagram.py

Needs Chrome (headless) and network access once, for Mermaid from a CDN. The SVG uses plain text
labels (no HTML inside), so it displays the same as an <img> on GitHub, and has its own background so
it reads on light and dark pages.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "architecture.mmd"
OUT = ROOT / "docs" / "architecture.svg"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
MERMAID = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"
PAPER = "#FBFAF6"

PAGE = """<!doctype html><meta charset="utf-8"><body><textarea id="out"></textarea>
<script type="module">
import mermaid from "%(mermaid)s";
mermaid.initialize({ startOnLoad: false, htmlLabels: false, theme: "base", fontFamily: "Inter Tight, system-ui, sans-serif",
  flowchart: { htmlLabels: false, curve: "basis", padding: 14 },
  themeVariables: { primaryColor: "#FFFFFF", primaryBorderColor: "#C9C5BB", primaryTextColor: "#232323",
    lineColor: "#6B6B6B", clusterBkg: "#F4F1E8", clusterBorder: "#C9C5BB", edgeLabelBackground: "%(paper)s",
    fontSize: "15px" } });
const { svg } = await mermaid.render("arch", %(source)s);
document.getElementById("out").textContent = svg;
</script>"""


def main() -> int:
    import json

    page = ROOT / "data" / "scratch" / "render_diagram.html"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        PAGE % {"mermaid": MERMAID, "paper": PAPER, "source": json.dumps(SRC.read_text())}
    )
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--virtual-time-budget=20000", "--dump-dom", page.as_uri()],
        capture_output=True, text=True, timeout=90, check=True,
    ).stdout  # fmt: skip
    m = re.search(r'<textarea id="out">(.*?)</textarea>', dom, re.DOTALL)
    svg = html.unescape(m.group(1)) if m else ""
    if "<svg" not in svg:
        print("render failed: no SVG came back (is there network access for the Mermaid CDN?)")
        return 1
    vb = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    x, y, w, h = (float(v) for v in vb.groups())
    svg = re.sub(
        r'(<svg[^>]*?) width="100%"', rf'\1 width="{w:.0f}" height="{h:.0f}"', svg, count=1
    )
    svg = re.sub(r' style="max-width:[^"]*;?"', "", svg, count=1)
    svg = svg.replace(' role="graphics-document document"', "", 1)
    svg = (
        svg.replace(
            "<svg ",
            '<svg xmlns:xlink="http://www.w3.org/1999/xlink" role="img" aria-labelledby="t d" ',
            1,
        )
        if "xmlns:xlink" not in svg
        else svg
    )
    head_end = svg.index(">") + 1
    svg = (
        svg[:head_end]
        + '<title id="t">How a capture flows through Food Insights</title>'
        + '<desc id="d">A browser sends a photo to the FastAPI app. The pipeline rotates and shrinks it, '
        + "reads the label with jina-ocr-v1 on the Elastic Inference Service, finds the numbers, checks the "
        + "barcode against Open Food Facts and saves the result in Elasticsearch Serverless. The browser also "
        + "searches that index through the app.</desc>"
        + f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{PAPER}"/>'
        + svg[head_end:]
    )
    OUT.write_text(svg)
    print(f"{OUT.relative_to(ROOT)}: {len(svg) // 1024} KB, {w:.0f}x{h:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
