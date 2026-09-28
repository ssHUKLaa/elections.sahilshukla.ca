"""Snapshot the Stage 1 historical poll and election-result source catalog."""

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


def inspect_payload(payload: bytes, format_name: str) -> dict[str, object]:
    if payload.lstrip().lower().startswith((b"<!doctype html", b"<html")):
        raise ValueError("download returned HTML rather than the requested data file")
    if format_name == "csv":
        text = payload.decode("utf-8-sig", errors="strict")
        reader = csv.reader(io.StringIO(text, newline=""))
        header = next(reader, None)
        if not header or len(header) != len(set(header)):
            raise ValueError("CSV has a missing or duplicate header")
        rows = 0
        for line, row in enumerate(reader, 2):
            if len(row) != len(header):
                raise ValueError(f"CSV row {line} does not match the header width")
            rows += 1
        return {"rows": rows, "columns": header}
    if format_name == "xlsx" and not payload.startswith(b"PK"):
        raise ValueError("XLSX download does not have a ZIP container signature")
    if format_name == "xls" and not payload.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise ValueError("XLS download does not have an OLE compound-file signature")
    if format_name == "pdf" and not payload.startswith(b"%PDF-"):
        raise ValueError("PDF download does not have a PDF signature")
    return {}


def snapshot_sources(catalog_path: Path, output_root: Path) -> Path:
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    started = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = output_root / started
    staging = output_root / f"{started}.incomplete"
    if destination.exists() or staging.exists():
        raise FileExistsError(f"Snapshot path already exists for {started}")
    staging.mkdir(parents=True)
    manifest: dict[str, object] = {
        "retrieved_at_utc": started,
        "catalog": str(catalog_path),
        "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
        "adapter_version": "1.0",
        "files": {},
    }
    session = requests.Session()
    session.headers["User-Agent"] = "us2026forecast-stage1/1.0"
    for source in catalog["sources"]:
        response = session.get(source["url"], timeout=90)
        response.raise_for_status()
        payload = response.content
        inspection = inspect_payload(payload, source["format"])
        filename = f"{source['id']}.{source['format']}"
        (staging / filename).write_bytes(payload)
        manifest["files"][source["id"]] = {
            **source,
            "filename": filename,
            "final_url": response.url,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "last_modified": response.headers.get("Last-Modified"),
            "etag": response.headers.get("ETag"),
            "content_type": response.headers.get("Content-Type"),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            **inspection,
        }
        print(f"{source['id']}: {len(payload):,} bytes")
    digest = hashlib.sha256()
    for name, record in sorted(manifest["files"].items()):
        digest.update(name.encode("utf-8"))
        digest.update(record["sha256"].encode("ascii"))
    manifest["content_sha256"] = digest.hexdigest()
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    staging.replace(destination)
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--catalog", type=Path, default=Path("data/reference/stage1_source_catalog.json")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("data/raw/historical")
    )
    args = parser.parse_args()
    destination = snapshot_sources(args.catalog, args.output_root)
    print(f"Saved {destination / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError, requests.RequestException) as error:
        print(f"Snapshot failed: {error}", file=sys.stderr)
        raise SystemExit(1)
