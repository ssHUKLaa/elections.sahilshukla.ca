"""Save immutable NYT polling CSV snapshots with a manifest and schema checks.

Run from the repository root with ``python pipeline/snapshot_nyt_polls.py``.
The snapshot directory is intentionally ignored by Git.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests


SOURCES = {
    "president_approval_polls": "https://www.nytimes.com/newsgraphics/polls/approval/president.csv",
    "president_approval_averages": "https://www.nytimes.com/newsgraphics/polls/approval/president-averages.csv",
    "senate": "https://www.nytimes.com/newsgraphics/polls/senate.csv",
    "house": "https://www.nytimes.com/newsgraphics/polls/house.csv",
    "governor": "https://www.nytimes.com/newsgraphics/polls/governor.csv",
    "other": "https://www.nytimes.com/newsgraphics/polls/other.csv",
}

DEFAULT_SCHEMA_CONTRACT = Path("data/reference/nyt_poll_schema_v1.json")


def inspect_csv(payload: bytes) -> tuple[list[str], int]:
    """Check that a download is parseable CSV and return header and data-row count."""
    stream = io.StringIO(payload.decode("utf-8-sig", errors="strict"), newline="")
    reader = csv.reader(stream)
    header = next(reader, None)
    if not header or len(header) != len(set(header)):
        raise ValueError("CSV header is missing or contains duplicate column names")
    if header[0].lstrip().startswith("<"):
        raise ValueError("Response looks like HTML rather than CSV")
    rows = 0
    for line_number, row in enumerate(reader, 2):
        if len(row) != len(header):
            raise ValueError(
                f"CSV row {line_number} has {len(row)} fields; expected {len(header)}"
            )
        rows += 1
    return header, rows


def load_schema_contract(path: Path) -> dict[str, list[str]]:
    """Load the exact ordered headers accepted by this adapter version."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("contract_version") != "1.0":
        raise ValueError(f"Unsupported NYT schema contract in {path}")
    schemas = document.get("feeds")
    if not isinstance(schemas, dict) or set(schemas) != set(SOURCES):
        raise ValueError("NYT schema contract does not cover exactly the configured feeds")
    return {name: value["columns"] for name, value in schemas.items()}


def assert_expected_schema(name: str, actual: list[str], expected: list[str]) -> None:
    """Fail loudly when columns are added, removed, renamed, or reordered."""
    if actual == expected:
        return
    added = [column for column in actual if column not in expected]
    missing = [column for column in expected if column not in actual]
    raise ValueError(
        f"Schema drift in {name}: expected {len(expected)} ordered columns, "
        f"received {len(actual)}; added={added}; missing={missing}; "
        "inspect the feed and version the adapter contract before continuing"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/nyt"))
    parser.add_argument(
        "--schema-contract", type=Path, default=DEFAULT_SCHEMA_CONTRACT
    )
    args = parser.parse_args()

    expected_schemas = load_schema_contract(args.schema_contract)
    contract_sha256 = hashlib.sha256(args.schema_contract.read_bytes()).hexdigest()

    started_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = args.output_root / started_at
    staging = args.output_root / f"{started_at}.incomplete"
    if destination.exists() or staging.exists():
        raise FileExistsError(f"Snapshot directory already exists: {destination}")
    staging.mkdir(parents=True)

    manifest: dict[str, object] = {
        "retrieved_at_utc": started_at,
        "source": "New York Times public polling downloads",
        "adapter_version": "1.0",
        "schema_contract": str(args.schema_contract),
        "schema_contract_sha256": contract_sha256,
        "permission_record": "data/reference/source_permissions_2026.json",
        "files": {},
    }
    session = requests.Session()
    session.headers.update({"User-Agent": "us2026forecast-data-inventory/0.1"})
    for name, url in SOURCES.items():
        response = session.get(url, timeout=45)
        response.raise_for_status()
        payload = response.content
        header, row_count = inspect_csv(payload)
        assert_expected_schema(name, header, expected_schemas[name])
        (staging / f"{name}.csv").write_bytes(payload)
        manifest["files"][name] = {
            "source_url": url,
            "final_url": response.url,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "content_type": response.headers.get("Content-Type"),
            "etag": response.headers.get("ETag"),
            "last_modified": response.headers.get("Last-Modified"),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "bytes": len(payload),
            "rows": row_count,
            "columns": header,
        }
        print(f"{name}: {row_count} rows, {len(header)} columns")

    content_hash = hashlib.sha256()
    for name in sorted(manifest["files"]):
        content_hash.update(name.encode("utf-8"))
        content_hash.update(manifest["files"][name]["sha256"].encode("ascii"))
    manifest["content_sha256"] = content_hash.hexdigest()

    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    staging.replace(destination)
    print(f"Saved {destination / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (requests.RequestException, UnicodeError, ValueError, OSError) as error:
        print(f"Snapshot failed: {error}", file=sys.stderr)
        raise SystemExit(1)
