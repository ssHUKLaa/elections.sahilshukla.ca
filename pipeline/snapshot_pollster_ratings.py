"""Snapshot 538 pollster ratings used by the nowcast research model."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "data/reference/pollster_ratings"
URL = "https://raw.githubusercontent.com/fivethirtyeight/data/master/pollster-ratings/pollster-ratings-combined.csv"


def main():
    payload = urllib.request.urlopen(URL, timeout=45).read()
    text = payload.decode("utf-8-sig")
    rows = list(csv.DictReader(io.StringIO(text)))
    required = {"pollster", "pollster_rating_id", "numeric_grade", "POLLSCORE", "error_ppm", "bias_ppm"}
    if len(rows) < 300 or not required <= set(rows[0]):
        raise ValueError("Unexpected pollster ratings schema or row count")
    DESTINATION.mkdir(parents=True, exist_ok=True)
    path = DESTINATION / "ratings.csv"
    path.write_bytes(payload)
    manifest = {
        "source_url": URL,
        "source_repository": "https://github.com/fivethirtyeight/data/tree/master/pollster-ratings",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "rows": len(rows),
        "local_path": "ratings.csv",
    }
    (DESTINATION / "manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
