"""Extract active federal/governor candidates from the Illinois SBE export."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_official_ballot_subset import add_entry


def main() -> None:
    snapshot = max(
        path for path in Path("data/raw/state_ballots").iterdir()
        if path.is_dir() and path.name.endswith("-IL") and (path / "manifest.json").exists()
    )
    meta = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    entries = []
    with (snapshot / "IL_candidate_export.bin").open(encoding="utf-8-sig", newline="") as stream:
        for row_number, row in enumerate(csv.DictReader(stream, delimiter="\t"), 2):
            if row["CandidateStatus"] != "Active":
                continue
            office = row["OfficeName"]
            if office == "UNITED STATES SENATOR":
                race_id = "S-2026-IL-II-regular"
            elif office == "GOVERNOR AND LIEUTENANT GOVERNOR":
                if row["AffiliateCommittee"]:
                    continue  # Running mate; not a competing governor candidate.
                race_id = "G-2026-IL"
            else:
                match = re.fullmatch(r"(\d+)(?:ST|ND|RD|TH) CONGRESS", office)
                if not match:
                    continue
                race_id = f"H-2026-IL-{int(match.group(1)):02d}"
            name = (row["FirstName"] + " " + row["LastName"]).strip()
            add_entry(entries, race_id, name, row["PartyName"], "il_sbe_export",
                      "active_general_listed", f"TSV row {row_number}")
            entries[-1]["source_candidate_id"] = row["CandidateID"]
            entries[-1]["candidate_id"] = f"PERSON-IL-SBE-{row['CandidateID']}"
    race_ids = {entry["race_id"] for entry in entries}
    expected = {f"H-2026-IL-{number:02d}" for number in range(1, 18)} | {
        "S-2026-IL-II-regular", "G-2026-IL"
    }
    if race_ids != expected or len({e["ballot_entry_id"] for e in entries}) != len(entries):
        raise ValueError(f"Illinois missing or duplicate races: {sorted(expected - race_ids)}")
    document = {
        "version": "0.1-state-export",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_snapshot": snapshot.as_posix(),
        "sources": {"il_sbe_export": meta},
        "status_note": "State export is updated every 15 minutes and warns records may change or contain errors; retain Active status and source timestamp.",
        "counts_by_office": dict(Counter(e["race_id"][0] for e in entries)),
        "entries": sorted(entries, key=lambda e: e["ballot_entry_id"]),
    }
    output = Path("data/reference/ballot_entries_il_2026.json")
    output.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output}: {len(entries)} entries across {len(race_ids)} races")


if __name__ == "__main__":
    main()
