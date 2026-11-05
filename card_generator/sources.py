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

# Sentences about price, stock, delivery or warranty are shop copy, not device facts.
SHOP_NOISE = re.compile(
    r"цен[аеуы]\b|₽|\bруб|интернет-магазин|в наличии|купить|приобрести|доставк|гаранти",
    re.IGNORECASE,
)

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


def read_shop_name(feed_path: Path) -> str:
    for _, elem in ET.iterparse(feed_path, events=("end",)):
        if elem.tag == "name":
            return (elem.text or "").strip()
    return ""


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


GENERIC_HEADERS = {"характеристики", "параметр", "наименование", "наименование параметра"}
# Drawing captions: every cell is "<same label>: <variant>", as in "Тип штуцера: Х2Х" |
# "Тип штуцера: Х4Х". Such a row names pictures and carries no spec value.
_CAPTION = re.compile(r"^([^:]+):\s*\S")
# A name cut after an adjective ("Устойчивость к механическим" + "воздействиям") goes on
# in the next row, which then starts lowercase.
_UNFINISHED = re.compile(r"(ым|им|ой|ых|их|ого|его|ую|юю|ая|яя)$")


def parse_spec_table(soup: BeautifulSoup) -> dict[str, str]:
    """Flatten the series tables into one key per row with all column values kept.

    Three shapes occur on the pages: a plain "name | value" table, rows that
    continue a key with ``rowspan`` or sit under a section row ending with ':',
    and matrix tables whose first row names the columns (often one row per
    modification). Matrix rows keep the column names next to their values.
    """
    block = soup.select_one("#specifications")
    if block is None:
        return {}
    specs: dict[str, list[str]] = {}
    for table in block.find_all("table"):
        _parse_table(table, specs)
    return {k: "; ".join(v) for k, v in specs.items()}


def _parse_table(table: Tag, specs: dict[str, list[str]]) -> None:
    header: list[str] = []
    section = ""
    current_key = ""
    rows_left = 0
    for index, row in enumerate(r for r in table.find_all("tr") if _row_cells(r)):
        cells = _row_cells(row)
        if index == 0 and len(cells) >= 2:
            if len(cells) >= 3:
                header = cells
                continue
            if cells[0].lower() in GENERIC_HEADERS:
                continue
        if rows_left > 0:
            rows_left -= 1
            specs[current_key].extend(cells)
            continue
        if header and len(cells) == len(header):
            key = f"{header[0]}: {cells[0]}"
            pairs = zip(header[1:], cells[1:], strict=True)
            specs.setdefault(key, []).append("; ".join(f"{h}: {v}" for h, v in pairs))
            continue
        if len(cells) == 1:
            if cells[0].endswith(":"):
                section = cells[0].rstrip(":")
            continue
        key, values = cells[0], cells[1:]
        if _is_caption_row(cells):
            continue
        if key[0].islower() and current_key and _UNFINISHED.search(current_key):
            # Both halves of the row belong together, so the value is joined with a space
            # and does not read as a list of series options.
            merged = f"{current_key} {key}"
            items = list(specs.items())
            specs.clear()
            for name, vals in items:
                if name == current_key:
                    name, vals = merged, [" ".join(vals + values)]
                specs[name] = vals
            current_key = merged
            continue
        if key[0] in "-–":
            key = f"{section}, {key.lstrip('-– ')}" if section else key.lstrip("-– ")
        else:
            section = ""
        current_key = key
        rows_left = int(row.find("td").get("rowspan", 1)) - 1
        specs.setdefault(key, []).extend(values)


def _is_caption_row(cells: list[str]) -> bool:
    labels = {m.group(1) if (m := _CAPTION.match(c)) else None for c in cells}
    return len(labels) == 1 and None not in labels


def _row_cells(row: Tag) -> list[str]:
    return [text for text in (_cell_text(c) for c in row.find_all(["td", "th"])) if text]


def parse_description(soup: BeautifulSoup, shop_name: str = "") -> str:
    block = soup.select_one("#description .long-short-block__inner")
    if block is None:
        return ""
    lines = []
    for el in block.find_all(["p", "td", "h3", "li"]):
        if el.find(["p", "td", "li"]):
            continue
        sentences = re.split(r"(?<=[.!?])\s+", clean_text(el.get_text(" ")))
        text = " ".join(x for x in sentences if x and not _is_shop_copy(x, shop_name))
        if text:
            lines.append(text)
    return "\n".join(lines)


def _is_shop_copy(sentence: str, shop_name: str) -> bool:
    if SHOP_NOISE.search(sentence):
        return True
    if not shop_name:
        return False
    # Shop names are spelled with and without the hyphen on the pages.
    letters = re.sub(r"[\W_]", "", sentence.lower())
    return re.sub(r"[\W_]", "", shop_name.lower()) in letters


def build_input(offer: dict, html: str, fetched_at: datetime, shop_name: str = "") -> dict:
    soup = BeautifulSoup(html, "html.parser")
    specs = parse_quick_specs(soup)
    for key, value in parse_spec_table(soup).items():
        specs.setdefault(key, value)
    description = parse_description(soup, shop_name)[:MAX_DESCRIPTION_CHARS]
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
