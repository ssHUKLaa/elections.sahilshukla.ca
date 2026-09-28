"""Repair malformed candidate delimiters in the pinned Wikipedia catalog.

This is a local migration for the existing snapshot. Fresh snapshots use the
corrected split-based parser in build_wikipedia_ballots.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from build_official_ballot_subset import add_entry, slug

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/reference/ballot_entries_wikipedia_2026.json"
REPORT = ROOT / "artifacts/calibration/ballot_name_repair_2026.json"
PARTY = {"Democratic": "DEM", "Republican": "REP", "Libertarian": "LIB",
         "Independent": "IND", "Green": "GRE"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    document = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not any("▌" in entry["name"] for entry in document["entries"]):
        if REPORT.exists() and json.loads(REPORT.read_text(encoding="utf-8"))["after_sha256"] == sha(SOURCE):
            print("Ballot names already repaired")
            return
        raise ValueError("No malformed names found; rebuild from the source snapshot instead")
    before = sha(SOURCE)
    changes = []
    additions = []
    for entry in document["entries"]:
        old = entry["name"]
        if "▌" not in old:
            continue
        parts = [part.strip() for part in old.split("▌") if part.strip()]
        if not parts:
            raise ValueError(f"Empty candidate name in {entry['race_id']}")
        clean = parts[-1]
        if "(" in clean or ")" in clean or not clean:
            raise ValueError(f"Unexpected retained name {clean!r} in {entry['race_id']}")
        for extra in parts[:-1]:
            match = re.fullmatch(r"(.+?)\s+\(([^()]+)\)", extra)
            if not match or match.group(2) not in PARTY:
                raise ValueError(f"Cannot recover preceding candidate {extra!r}")
            name, label = match.groups()
            added = []
            add_entry(added, entry["race_id"], name, label, entry["source_key"],
                      entry["status"], entry["source_record"], entry["note"])
            additions.extend(added)
        entry["name"] = clean
        entry["ballot_entry_id"] = f"{entry['race_id']}:{slug(clean)}"
        entry["candidate_id"] = f"PERSON-{entry['race_id'].split('-')[2]}-{slug(clean)}"
        changes.append({"race_id": entry["race_id"], "old_name": old, "new_name": clean})
    document["entries"] = sorted(document["entries"] + additions,
                                 key=lambda entry: entry["ballot_entry_id"])
    ids = [entry["ballot_entry_id"] for entry in document["entries"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Candidate ID collision after name repair")
    if any("▌" in entry["name"] for entry in document["entries"]):
        raise ValueError("A malformed candidate delimiter remains")
    SOURCE.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report = {"before_sha256": before, "after_sha256": sha(SOURCE),
              "source_snapshot": document["source_snapshot"],
              "names_repaired": len(changes), "candidates_recovered": len(additions),
              "changes": changes,
              "recovered": [{"race_id": entry["race_id"], "name": entry["name"],
                             "party": entry["ballot_party"]} for entry in additions]}
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"names_repaired": len(changes), "candidates_recovered": len(additions)}))


if __name__ == "__main__":
    main()
