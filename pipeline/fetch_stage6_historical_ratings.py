"""Fetch dated 538 rating editions for historical as-of poll weighting."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/reference/pollster_ratings/historical"
COMMITS = {
    2019: "c3240539f398",
    2021: "6b0362a08118",
    2023: "fea5d9ee79d2",
}
REPLAY_USE = {2020: 2019, 2022: 2021, 2024: 2023}


def main() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    records = {}
    for edition, commit in COMMITS.items():
        url = (f"https://raw.githubusercontent.com/fivethirtyeight/data/{commit}/"
               f"pollster-ratings/{edition}/pollster-ratings.csv")
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        content = response.content
        path = DEST / f"538_{edition}.csv"
        path.write_bytes(content)
        records[str(edition)] = {
            "url": url, "filename": path.name, "bytes": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    manifest = {
        "source": "FiveThirtyEight/data pollster-ratings edition directories",
        "replay_use": {str(k): v for k, v in REPLAY_USE.items()},
        "publication_evidence": {
            "2019": "https://data.fivethirtyeight.com/ (May 19, 2020 ratings update ahead of general election)",
            "2021": "https://fivethirtyeight.com/features/the-death-of-polling-is-greatly-exaggerated/ (March 25, 2021 release)",
            "2023": "https://fivethirtyeight.com/features/the-polls-were-historically-accurate-in-2022/ (March 10, 2023 update)",
        },
        "caveat": "These editions predate their scored general elections, but only a single edition per cycle is available; within-cycle rating changes cannot be reconstructed.",
        "files": records,
    }
    (DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
