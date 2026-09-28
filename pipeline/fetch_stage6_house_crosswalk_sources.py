"""Download and verify the pinned official Census district boundary archives."""

from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data/reference/stage6_house_crosswalk_sources.json"
DESTINATION = ROOT / "data/raw/census_districts"


def verify(path: Path, entry: dict) -> bool:
    if not path.exists() or path.stat().st_size != entry["bytes"]:
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for cycle, entry in manifest.items():
        path = DESTINATION / entry["filename"]
        if not verify(path, entry):
            temporary = path.with_suffix(".download")
            urllib.request.urlretrieve(entry["url"], temporary)
            if not verify(temporary, entry):
                temporary.unlink(missing_ok=True)
                raise ValueError(f"Source checksum mismatch for {entry['url']}")
            temporary.replace(path)
        print(f"{cycle}: verified {path}", flush=True)


if __name__ == "__main__":
    main()
