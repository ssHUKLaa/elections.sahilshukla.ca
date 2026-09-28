"""Freeze the external election and generic-ballot files used in local research."""

import hashlib
import json
import argparse
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "reference" / "local_lean"
SOURCES = {
    "presidential_results.csv": "https://raw.githubusercontent.com/fivethirtyeight/election-results/main/election_results_presidential.csv",
    "senate_results.csv": "https://raw.githubusercontent.com/fivethirtyeight/election-results/main/election_results_senate.csv",
    "generic_topline_historical.csv": "https://raw.githubusercontent.com/fivethirtyeight/data/master/congress-generic-ballot/generic_topline_historical.csv",
    "fec_2024_presidential.xlsx": "https://www.fec.gov/documents/5645/2024presgeresults.xlsx",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--restore", action="store_true", help="Restore files from the frozen manifest and verify hashes")
    args = parser.parse_args()
    TARGET.mkdir(parents=True, exist_ok=True)
    if args.restore:
        manifest = json.loads((TARGET / "source_manifest.json").read_text(encoding="utf-8"))
        for name, item in manifest.items():
            path = TARGET / name
            if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
                continue
            response = requests.get(item["url"], timeout=60)
            response.raise_for_status()
            if hashlib.sha256(response.content).hexdigest() != item["sha256"]:
                raise ValueError(f"Source no longer matches frozen snapshot: {name}")
            path.write_bytes(response.content)
        print(json.dumps({"status": "restored", "files": len(manifest)}, indent=2))
        return
    manifest = {}
    for name, url in SOURCES.items():
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        (TARGET / name).write_bytes(response.content)
        manifest[name] = {"url": url, "bytes": len(response.content),
                          "sha256": hashlib.sha256(response.content).hexdigest()}
    (TARGET / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
