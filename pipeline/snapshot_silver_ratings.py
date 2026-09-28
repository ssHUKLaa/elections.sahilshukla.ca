"""Pin Silver Bulletin's January 2026 pollster ratings and normalize the model fields."""

from __future__ import annotations

import csv
import hashlib
import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
DESTINATION = ROOT / "data/reference/pollster_ratings"
PAGE = "https://www.natesilver.net/p/pollster-ratings-silver-bulletin"
FILE_URL = "https://www.natesilver.net/api/v1/file/7bd65470-3e0d-4c0f-a658-22ca23b216ae.xlsx"
FIELDS = (
    "pollster_rating_id", "pollster", "predictive_plus_minus", "grade",
    "banned", "poll_count", "simple_expected_error", "mean_reverted_bias",
)


def main() -> None:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    workbook_path = DESTINATION / "silver_2026.xlsx"
    request = urllib.request.Request(FILE_URL, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": PAGE,
    })
    payload = urllib.request.urlopen(request, timeout=45).read()
    if not payload.startswith(b"PK\x03\x04") or len(payload) < 50_000:
        raise ValueError("Unexpected Silver Bulletin workbook payload")
    workbook_path.write_bytes(payload)
    workbook = load_workbook(workbook_path, read_only=True, data_only=True)
    sheet = workbook.worksheets[0]
    source_rows = list(sheet.values)
    header = source_rows[0]
    expected = {2: "Pollster Rating ID", 7: "Predictive    Plus-Minus", 8: "SB Grade"}
    if any(header[index] != name for index, name in expected.items()):
        raise ValueError("Silver Bulletin workbook schema changed")
    rows = []
    for row in source_rows[1:]:
        if row[2] is None:
            continue
        rows.append({
            "pollster_rating_id": str(int(row[2])),
            "pollster": str(row[1]),
            "predictive_plus_minus": float(row[7]),
            "grade": str(row[8]),
            "banned": str(row[5]).strip().lower() == "yes",
            "poll_count": int(row[3]),
            "simple_expected_error": float(row[14]) if row[14] is not None else "",
            "mean_reverted_bias": float(row[9]) if row[9] is not None else "",
        })
    if len(rows) < 500 or len({row["pollster_rating_id"] for row in rows}) != len(rows):
        raise ValueError("Unexpected Silver Bulletin row count or duplicate pollster IDs")
    csv_path = DESTINATION / "silver_2026.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "source_page": PAGE, "source_file_url": FILE_URL,
        "source_date": "2026-01-14", "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "workbook_sha256": hashlib.sha256(payload).hexdigest(),
        "normalized_csv_sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        "rows": len(rows), "banned_rows": sum(row["banned"] for row in rows),
        "credit": "Silver Bulletin / Nate Silver and Eli McKown-Dawson",
    }
    (DESTINATION / "silver_2026_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
