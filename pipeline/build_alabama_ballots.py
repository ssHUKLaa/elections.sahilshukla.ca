"""Record Alabama federal and governor nominees from state certifications.

The source PDFs are scans. The candidate tables were OCRed after rotation and
then checked against rendered pages. The independent certification contains no
federal or governor candidate.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from build_official_ballot_subset import add_entry


SOURCES = {
    "al_democratic_certified": "AL_general_democratic_certified.pdf",
    "al_republican_certified": "AL_general_republican_certified.pdf",
    "al_independent_certified": "AL_general_independent_certified.pdf",
}

# (race_id, name, party, source key, PDF page)
ROWS = [
    ("S-2026-AL-II-regular", "Everett Wess", "Democratic", "al_democratic_certified", 3),
    ("S-2026-AL-II-regular", "Barry Moore", "Republican", "al_republican_certified", 2),
    ("G-2026-AL", "Doug Jones", "Democratic", "al_democratic_certified", 3),
    ("G-2026-AL", "Tommy Tuberville", "Republican", "al_republican_certified", 2),
    ("H-2026-AL-01", "Clyde Jones", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-01", "Jerry Carl", "Republican", "al_republican_certified", 14),
    ("H-2026-AL-02", "Shomari C. Figures", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-02", "Rhett Marques", "Republican", "al_republican_certified", 14),
    ("H-2026-AL-03", "Lee McInnis", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-03", "Mike Rogers", "Republican", "al_republican_certified", 2),
    ("H-2026-AL-04", "Amanda N. Pusczek", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-04", "Robert B. Aderholt", "Republican", "al_republican_certified", 2),
    ("H-2026-AL-05", "Andrew Sneed", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-05", "Dale W. Strong", "Republican", "al_republican_certified", 2),
    ("H-2026-AL-06", "Maurice Mercer", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-06", "Gary Palmer", "Republican", "al_republican_certified", 14),
    ("H-2026-AL-07", "Terri Sewell", "Democratic", "al_democratic_certified", 3),
    ("H-2026-AL-07", "Ammie Akin", "Republican", "al_republican_certified", 14),
]


def main() -> None:
    snapshot = max(
        path for path in Path("data/raw/state_ballots").iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
        and all((path / filename).exists() for filename in SOURCES.values())
    )
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    source_metadata = {}
    for key, filename in SOURCES.items():
        source_metadata[key] = manifest["files"][filename]

    entries = []
    for race_id, name, party, source_key, page in ROWS:
        add_entry(
            entries, race_id, name, party, source_key, "certified_general",
            f"PDF page {page}", "State certification; scanned table visually reviewed.",
        )
    assert len(entries) == 18
    assert len({entry["race_id"] for entry in entries}) == 9
    assert all(sum(e["race_id"] == race_id for e in entries) == 2
               for race_id in {entry["race_id"] for entry in entries})

    document = {
        "version": "0.1-manual",
        "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": snapshot.as_posix(),
        "sources": source_metadata,
        "scope_note": (
            "The separately certified independent list was reviewed and contains "
            "only state legislative candidates, so it adds no entry in this project scope."
        ),
        "entries": entries,
    }
    output = Path("data/reference/ballot_entries_al_2026.json")
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}: {len(entries)} entries across 9 races")


if __name__ == "__main__":
    main()
