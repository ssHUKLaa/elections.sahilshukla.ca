"""Fetch the checksum-pinned Downballot sheets used for replay map shifts."""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.build_stage6_historical_house_map_shifts import SHEETS

REFERENCE = ROOT / "data/reference/stage6_historical_house_map_shifts.json"
DESTINATION = ROOT / "data/raw/census_districts"


def main() -> None:
    report = json.loads(REFERENCE.read_text(encoding="utf-8"))
    DESTINATION.mkdir(parents=True, exist_ok=True)
    fetched = []
    for name, (filename, _, _, url) in SHEETS.items():
        path = DESTINATION / filename
        expected = report["sources"][name]["sha256"]
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == expected:
            continue
        base, _, query = url.partition("?")
        params = urllib.parse.parse_qs(query)
        gid = params["gid"][0]
        export_url = base.replace("/edit", "/export") + "?format=csv&gid=" + gid
        with urllib.request.urlopen(export_url, timeout=30) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Source hash changed: {name} {export_url}")
        path.write_bytes(data)
        fetched.append(filename)
    print(json.dumps({"verified_sources": len(SHEETS), "downloaded": fetched}))


if __name__ == "__main__":
    main()
