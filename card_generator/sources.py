"""Build service input from the public YML feed and the product page.

The feed has no descriptions or specs, only names and prices, so the text and
characteristics come from the product page. A page describes the whole series,
while a feed offer is one modification, hence ``specs_scope = "series"``.
"""

import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

FEED_URL = "https://www.souz-pribor.ru/yml/any/feed.xml"
USER_AGENT = "card-draft-prototype/0.1 (test task, low rate)"
REQUEST_PAUSE_S = 2.0
MAX_DESCRIPTION_CHARS = 6000

_last_request_at = 0.0


def iter_offers(feed_path: Path) -> Iterator[dict]:
    """Stream offers from a YML file without loading the 37 MB tree."""
    for _, elem in ET.iterparse(feed_path, events=("end",)):
        if elem.tag != "offer":
            continue
        offer = {
            "id": elem.get("id"),
            "params": {p.get("name"): (p.text or "").strip() for p in elem.findall("param")},
        }
        for child in elem:
            if child.tag != "param":
                offer[child.tag] = (child.text or "").strip()
        elem.clear()
        yield offer


def find_offer(feed_path: Path, offer_id: str) -> dict:
    for offer in iter_offers(feed_path):
        if offer["id"] == offer_id:
            return offer
    raise KeyError(f"offer {offer_id} not found in {feed_path}")


def page_cache_path(url: str, cache_dir: Path) -> Path:
    slug = urlparse(url).path.strip("/").split("/")[-1] or "index"
    return cache_dir / f"{slug}.html"


def fetch_page(url: str, cache_dir: Path) -> tuple[str, datetime]:
    """Return page HTML and the moment it was downloaded; a cached page is never refetched."""
    global _last_request_at
    path = page_cache_path(url, cache_dir)
    if not path.exists():
        wait = REQUEST_PAUSE_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        response = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        _last_request_at = time.monotonic()
        response.raise_for_status()
        cache_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text, encoding="utf-8")
    fetched_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return path.read_text(encoding="utf-8"), fetched_at


def clean_text(text: str) -> str:
    text = text.replace("\xa0", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", text).strip()


def _cell_text(cell: Tag) -> str:
    return clean_text(cell.get_text(" "))


def parse_quick_specs(soup: BeautifulSoup) -> dict[str, str]:
    specs = {}
    for item in soup.select(".characteristics .characteristics__item"):
        name = item.select_one(".characteristics__name")
        value = item.select_one(".characteristics__desc")
        if name and value:
            key = _cell_text(name).rstrip(":").strip()
            if key and _cell_text(value):
                specs[key] = _cell_text(value)
    return specs


def parse_spec_table(soup: BeautifulSoup) -> dict[str, str]:
    """Flatten the series table: one key per row, values of all columns joined.

    Rows that continue a key with ``rowspan`` and section rows ending with ':'
    are folded into readable keys, so the series values stay together.
    """
    block = soup.select_one("#specifications")
    if block is None:
        return {}
    specs: dict[str, list[str]] = {}
    section = ""
    current_key = ""
    rows_left = 0
    for row in block.select("table tr"):
        cells = [_cell_text(c) for c in row.find_all("td")]
        cells = [c for c in cells if c]
        if not cells:
            continue
        if rows_left > 0:
            rows_left -= 1
            specs[current_key].extend(cells)
            continue
        first = row.find("td")
        if len(cells) == 1:
            if cells[0].endswith(":"):
                section = cells[0].rstrip(":")
            continue
        key, values = cells[0], cells[1:]
        if key.lower() == "характеристики":
            continue
        if key.startswith("-") or key.startswith("–"):
            key = f"{section}, {key.lstrip('-– ')}" if section else key.lstrip("-– ")
        else:
            section = ""
        current_key = key
        rows_left = int(first.get("rowspan", 1)) - 1
        specs.setdefault(key, []).extend(values)
    return {k: "; ".join(v) for k, v in specs.items()}


def parse_description(soup: BeautifulSoup) -> str:
    block = soup.select_one("#description .long-short-block__inner")
    if block is None:
        return ""
    lines = []
    for el in block.find_all(["p", "td", "h3", "li"]):
        if el.find(["p", "td", "li"]):
            continue
        text = clean_text(el.get_text(" "))
        if text:
            lines.append(text)
    return "\n".join(lines)


def build_input(offer: dict, html: str, fetched_at: datetime) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    specs = parse_quick_specs(soup)
    for key, value in parse_spec_table(soup).items():
        specs.setdefault(key, value)
    description = parse_description(soup)[:MAX_DESCRIPTION_CHARS]
    series = soup.select_one("#specifications h2")
    return {
        "name": offer.get("name", ""),
        "manufacturer": offer.get("vendor", ""),
        "product_type": offer.get("typePrefix", ""),
        "specs": specs,
        "description": description,
        "specs_scope": "series",
        "source": {
            "feed_url": FEED_URL,
            "offer_id": offer["id"],
            "page_url": offer.get("url", ""),
            "page_fetched_at": fetched_at.isoformat(timespec="seconds"),
            "series_title": clean_text(series.get_text()) if series else "",
        },
    }
