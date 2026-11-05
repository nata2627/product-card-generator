"""Build a service input JSON for one feed offer: feed fields plus the product page."""

import argparse
import json
from pathlib import Path

from card_generator.sources import build_input, fetch_page, find_offer

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("offer_id")
    parser.add_argument("--feed", type=Path, default=ROOT / "data/raw/feed.xml")
    parser.add_argument("--pages", type=Path, default=ROOT / "data/raw/pages")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    offer = find_offer(args.feed, args.offer_id)
    html, fetched_at = fetch_page(offer["url"], args.pages)
    data = build_input(offer, html, fetched_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(data['specs'])} specs, {len(data['description'])} chars")


if __name__ == "__main__":
    main()
