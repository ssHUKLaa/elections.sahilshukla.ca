"""Restore the six checksum-pinned public poll CSVs used by Stage 6."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/reference/stage6_wayback_manifest.json"
DESTINATION = ROOT / "data/raw/historical_wayback/20241129"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    DESTINATION.mkdir(parents=True, exist_ok=True)
    sources = {**manifest["files"], **manifest.get("national_files", {})}
    for filename, spec in sources.items():
        path = DESTINATION / filename
        if path.exists():
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != spec["sha256"]:
                raise RuntimeError(f"Existing source file differs from manifest: {path}")
            print(f"verified {filename}")
            continue
        url = (f"https://web.archive.org/web/{spec['capture']}id_/"
               f"https://projects.fivethirtyeight.com/polls-page/data/{filename}")
        with urllib.request.urlopen(url, timeout=90) as response:
            if "csv" not in response.headers.get("Content-Type", "").lower():
                raise RuntimeError(f"Archive did not return a CSV: {url}")
            body = response.read()
        actual = hashlib.sha256(body).hexdigest()
        if actual != spec["sha256"]:
            raise RuntimeError(f"Archive file differs from manifest: {filename}")
        pending = path.with_suffix(".pending")
        pending.write_bytes(body)
        pending.replace(path)
        print(f"downloaded {filename}")


if __name__ == "__main__":
    main()
