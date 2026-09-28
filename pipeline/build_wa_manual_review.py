"""Record Washington House candidates transcribed from certified PDF pages 1-2.

Both pages were visually inspected at 2x rendering after OCR suggested the
names. Washington's printed party preference is not a party nomination.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from build_official_ballot_subset import add_entry


SOURCE_URL = "https://www.sos.wa.gov/sites/default/files/2026-08/2026%20Certification%20of%20Candidates%20to%20General%20Election.pdf"
ROWS = [
    (1, "Suzan DelBene", "Democratic", 1), (1, "Mary Silva", "Republican", 1),
    (2, "Rick Larsen", "Democratic", 1), (2, "Edwin H. Feller", "Republican", 1),
    (3, "John Braun", "Republican", 1), (3, "Marie Gluesenkamp Perez", "Democratic", 1),
    (4, "Amanda McKinney", "Republican", 1), (4, "John Duresky", "Democratic", 1),
    (5, "Michael Baumgartner", "Republican", 1), (5, "Carmela Conroy", "Democratic", 1),
    (6, "Emily Randall", "Democratic", 2), (6, "Teresa Fox", "Republican", 2),
    (7, "Pramila Jayapal", "Democratic", 2), (7, "Nirav Sheth", "Republican", 2),
    (8, "Kim Schrier", "Democratic", 2), (8, "Spencer Meline", "Republican", 2),
    (9, "Adam Smith", "Democratic", 2), (9, "Doug Basler", "Republican", 2),
    (10, "Marilyn Strickland", "Democratic", 2), (10, "Chris D. Chung", "Republican", 2),
]


def main() -> None:
    snapshot = max(
        path for path in Path("data/raw/state_ballots").iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
        and (path / "WA_general_certified.pdf").exists()
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    metadata = manifest["files"]["WA_general_certified.pdf"]
    if metadata["url"] != SOURCE_URL:
        raise ValueError("Washington source URL differs from reviewed document")
    entries = []
    for district, name, party, page in ROWS:
        add_entry(entries, f"H-2026-WA-{district:02d}", name, party,
                  "wa_certified_visual", "certified_general", f"PDF page {page}",
                  "Source calls the party a candidate preference, not a nomination.")
        entries[-1]["source_party_label"] = f"Prefers {party} Party"
    assert len(entries) == 20 and len({e["race_id"] for e in entries}) == 10
    document = {
        "version": "0.1-manual",
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": snapshot.as_posix(),
        "sources": {"wa_certified_visual": metadata},
        "entries": entries,
    }
    output = Path("data/reference/ballot_entries_wa_reviewed_2026.json")
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}: {len(entries)} entries")


if __name__ == "__main__":
    main()
