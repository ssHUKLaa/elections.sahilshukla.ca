"""Snapshot the three Wikipedia 2026 election summary pages with revision IDs."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests


PAGES = {
    "senate": "2026 United States Senate elections",
    "house": "2026 United States House of Representatives elections",
    "governor": "2026 United States gubernatorial elections",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/wikipedia"))
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    destination = args.output_root / now.strftime("%Y%m%dT%H%M%SZ")
    destination.mkdir(parents=True, exist_ok=False)
    session = requests.Session()
    session.headers["User-Agent"] = "us2026forecast/0.1 (local election research)"
    manifest = {
        "retrieved_at_utc": now.isoformat(),
        "license": "CC BY-SA; see each page footer and Wikimedia Terms of Use",
        "files": {},
    }
    for key, title in PAGES.items():
        url = "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))
        response = session.get(url, timeout=120)
        response.raise_for_status()
        payload = response.content
        filename = f"{key}.html"
        (destination / filename).write_bytes(payload)
        api = session.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query", "format": "json", "formatversion": 2,
                "prop": "revisions", "rvprop": "ids|timestamp", "titles": title,
            },
            timeout=60,
        )
        api.raise_for_status()
        page = api.json()["query"]["pages"][0]
        revision = page["revisions"][0]
        manifest["files"][filename] = {
            "url": url,
            "title": title,
            "page_id": page["pageid"],
            "revision_id": revision["revid"],
            "revision_timestamp": revision["timestamp"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
        }
        print(f"{key}: revision {revision['revid']}, {len(payload):,} bytes")
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Saved {destination}")


if __name__ == "__main__":
    main()
