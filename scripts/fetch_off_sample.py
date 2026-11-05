"""Fetch an Open Food Facts sample.

    uv run python scripts/fetch_off_sample.py [--target 50]

Writes data/off/<code>.jpg, data/off/manifest.jsonl (panel/secondary schema, per 100 g),
data/off/ATTRIBUTION.md and _notes/reports/fetch_off_sample.md. Search pages are cached in
data/off/cache/, search calls are throttled below 10/min, 503 never stops the run.
Data: ODbL. Images: CC BY-SA. Attribute per product.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
OFF = ROOT / "data" / "off"
CACHE = OFF / "cache"
REPORTS = ROOT / "_notes" / "reports"  # git-ignored local notes
SEARCH = "https://world.openfoodfacts.org/api/v2/search"
# Search does not return image_nutrition_url, and selected_images only has the front pack.
# `images.nutrition_<lang>.rev` is enough to build the nutrition image URL.
FIELDS = "code,product_name,lang,countries_tags,images,nutriments"
# (country tag for the query, default language when the product has no `lang`)
COUNTRIES = [
    ("united-kingdom", "en"),
    ("france", "fr"),
    ("germany", "de"),
    ("portugal", "pt"),
    ("spain", "es"),
    ("italy", "it"),
    ("japan", "ja"),
]
# manifest key -> OFF nutriments key (all per 100 g)
NUTRIMENTS = {
    "energy_kcal": "energy-kcal_100g",
    "fat_g": "fat_100g",
    "saturated_fat_g": "saturated-fat_100g",
    "carbohydrates_g": "carbohydrates_100g",
    "sugars_g": "sugars_100g",
    "protein_g": "proteins_100g",
    "salt_g": "salt_100g",
}
MIN_SEARCH_INTERVAL = 7.0  # seconds; keeps us at <= ~8 search calls/min
BACKOFF = (10, 30, 60)  # seconds to wait after a failed search attempt
PAGE_SIZES = (100, 100, 50, 25)  # heavy pages 503, so later attempts ask for lighter ones
MAX_PAGES_PER_COUNTRY = 8
DOWNLOAD_PAUSE = 1.0  # seconds after each image: be gentle with the image server
MIN_NUTRIENTS = 4  # a product needs at least this many scored nutrients


class Throttle:
    def __init__(self, interval: float) -> None:
        self.interval, self.last = interval, 0.0

    def wait(self) -> None:
        delay = self.last + self.interval - time.time()
        if delay > 0:
            time.sleep(delay)
        self.last = time.time()


def search_page(client: httpx.Client, throttle: Throttle, country: str, page: int, stats: dict):
    """One cached search page. Returns the product list, or None if OFF never answered."""
    cache = CACHE / f"search_{country}_p{page}.json"
    if cache.exists():
        return json.loads(cache.read_text()).get("products", [])
    params = {
        "fields": FIELDS,
        "page": page,
        "sort_by": "unique_scans_n",
        "countries_tags_en": country,
    }
    for attempt, page_size in enumerate(PAGE_SIZES):
        params["page_size"] = page_size
        throttle.wait()
        stats["search_calls"] += 1
        try:
            r = client.get(SEARCH, params=params)
        except httpx.HTTPError:
            r = None
        if r is not None and r.status_code == 200:
            try:
                data = r.json()
            except ValueError:
                data = None
            if data is not None:
                cache.write_text(json.dumps(data))
                return data.get("products", [])
        stats["search_failures"] += 1
        if attempt < len(BACKOFF):
            time.sleep(BACKOFF[attempt])
    return None


def number(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def image_dir(code: str) -> str:
    """OFF image folder: 13-digit codes split 3/3/3/rest, shorter codes are used as-is."""
    return "/".join([code[0:3], code[3:6], code[6:9], code[9:]]) if len(code) > 8 else code


def nutrition_image_url(p: dict, lang: str) -> str | None:
    """400 px URL of the product's nutrition photo in `lang` (full_size() derives the original).

    Only the target language counts: a product sold in Italy often carries a French label.
    """
    images = p.get("images") or {}
    key = f"nutrition_{lang}"
    if not (images.get(key) or {}).get("rev"):
        return None
    base = "https://images.openfoodfacts.org/images/products"
    return f"{base}/{image_dir(str(p['code']))}/{key}.{images[key]['rev']}.400.jpg"


def usable(p: dict, lang: str) -> dict | None:
    """Keep products with a nutrition photo in `lang` and a ground truth worth scoring.

    Dropped: no photo in that language, no carbohydrates_100g, fewer than 4 nutrient values,
    or all zero / no energy (mineral water would make "carbs = 0" a free pass).
    """
    nut = p.get("nutriments") or {}
    image_url = nutrition_image_url(p, lang)
    if not image_url or number(nut.get("carbohydrates_100g")) is None:
        return None
    nutrients = {k: number(nut.get(src)) for k, src in NUTRIMENTS.items()}
    nutrients = {k: v for k, v in nutrients.items() if v is not None}
    if len(nutrients) < MIN_NUTRIENTS or not nutrients.get("energy_kcal"):
        return None
    return {
        "code": str(p["code"]),
        "name": p.get("product_name") or "",
        "lang": lang,
        "image_url": image_url,
        "nutrients": nutrients,
    }


def full_size(url: str) -> str:
    """OFF serves nutrition_en.<rev>.400.jpg; the original is nutrition_en.<rev>.full.jpg."""
    return url.replace(".400.jpg", ".full.jpg")


def valid_image(data: bytes) -> bool:
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:  # noqa: BLE001 - any decode failure just means "not a usable image"
        return False
    return True


def download(client: httpx.Client, url: str, dest: Path) -> str | None:
    """Full-size first, then the URL OFF gave us. Returns the URL used, or None."""
    for candidate in dict.fromkeys([full_size(url), url]):
        try:
            r = client.get(candidate)
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and valid_image(r.content):
            dest.write_bytes(r.content)
            time.sleep(DOWNLOAD_PAUSE)
            return candidate
    return None


def manifest_entry(c: dict, country: str, used_url: str) -> dict:
    return {
        "image": f"{c['code']}.jpg",
        "barcode": c["code"],
        "name": c["name"],
        "lang": c["lang"],
        "country": country,
        "image_url": used_url,
        "product_url": f"https://world.openfoodfacts.org/product/{c['code']}",
        "panel": {"per": "100g", "serving_text": None, "nutrients": c["nutrients"]},
        "secondary": {"scored": False},
    }


def collect_country(
    client: httpx.Client,
    throttle: Throttle,
    country: str,
    default_lang: str,
    *,
    quota: int,
    target: int,
    entries: list[dict],
    seen: set[str],
    stats: dict,
) -> int:
    """Download up to `quota` usable products of one country into `entries`; returns how many."""
    got = 0

    def enough() -> bool:
        return got >= quota or len(entries) >= target

    for page in range(1, MAX_PAGES_PER_COUNTRY + 1):
        if enough():
            break
        products = search_page(client, throttle, country, page, stats)
        if products is None:  # OFF unavailable: skip, never abort
            print(f"  {country} page {page}: unavailable, skipping")
            continue
        if not products:
            break
        for p in products:
            c = usable(p, default_lang)
            if not c or c["code"] in seen:
                continue
            if enough():
                break
            used = download(client, c["image_url"], OFF / f"{c['code']}.jpg")
            if used is None:
                stats["download_failures"] += 1
                continue
            stats["no_full_size"] += used != full_size(c["image_url"])
            seen.add(c["code"])
            entries.append(manifest_entry(c, country, used))
            got += 1
    return got


def write_manifest(entries: list[dict]) -> None:
    (OFF / "manifest.jsonl").write_text(
        "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries)
    )


def write_attribution(entries: list[dict]) -> None:
    lines = [
        "# Attribution",
        "",
        "Product data from [Open Food Facts](https://world.openfoodfacts.org), available under the",
        "[Open Database License (ODbL)](https://opendatacommons.org/licenses/odbl/1-0/).",
        "Product images are licensed [CC BY-SA](https://creativecommons.org/licenses/by-sa/3.0/)",
        "by their Open Food Facts contributors. Each image links to its product page below.",
        "",
        "| Barcode | Product | Country | Page |",
        "|---|---|---|---|",
    ]
    for e in entries:
        name = (e["name"] or "(unnamed)").replace("|", "/")
        lines.append(f"| {e['barcode']} | {name} | {e['country']} | [page]({e['product_url']}) |")
    (OFF / "ATTRIBUTION.md").write_text("\n".join(lines) + "\n")


def write_report(
    entries: list[dict], per_country: dict[str, int], stats: dict, target: int
) -> dict:
    """The run's report (JSON and Markdown); returns the language counts for the summary line."""
    langs: dict[str, int] = {}
    for e in entries:
        langs[e["lang"]] = langs.get(e["lang"], 0) + 1
    summary = {"images": len(entries), "per_country": per_country, "languages": langs, **stats}
    (REPORTS / "fetch_off_sample.json").write_text(json.dumps(summary, indent=2))
    (REPORTS / "fetch_off_sample.md").write_text(
        "# OFF sample fetch\n\n"
        f"- Images: {len(entries)} (target {target})\n"
        f"- Per country: {per_country}\n- Languages: {langs}\n"
        f"- Search calls: {stats['search_calls']} ({stats['search_failures']} failed or 503)\n"
        f"- Downloads that fell back to the 400 px image: {stats['no_full_size']}\n"
        f"- Download failures: {stats['download_failures']}\n"
    )
    return langs


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=50)
    args = ap.parse_args()
    ua = os.getenv("OFF_USER_AGENT")
    if not ua:
        sys.exit("OFF_USER_AGENT must be set in .env")

    CACHE.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    quota = math.ceil(args.target / len(COUNTRIES))
    stats = {"search_calls": 0, "search_failures": 0, "download_failures": 0, "no_full_size": 0}
    entries: list[dict] = []
    seen: set[str] = set()
    per_country: dict[str, int] = {}

    with httpx.Client(headers={"User-Agent": ua}, timeout=30, follow_redirects=True) as client:
        throttle = Throttle(MIN_SEARCH_INTERVAL)
        for country, default_lang in COUNTRIES:
            per_country[country] = collect_country(
                client, throttle, country, default_lang,
                quota=quota, target=args.target, entries=entries, seen=seen, stats=stats,
            )  # fmt: skip
            print(f"{country}: {per_country[country]}/{quota}")

    write_manifest(entries)
    write_attribution(entries)
    langs = write_report(entries, per_country, stats, args.target)
    print(f"{len(entries)} images -> data/off/ (languages {langs}, {stats})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
