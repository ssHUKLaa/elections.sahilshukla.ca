"""Check local-lean source coverage, official 2024 totals, and time ordering."""

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "modeling"))
import senate_local_lean as local


def main():
    local.verify_sources()
    source = defaultdict(list)
    with (local.SOURCE / "presidential_results.csv").open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["stage"] == "general" and row["cycle"] == "2024" and row["state_abbrev"] and row["votes"]:
                source[row["state_abbrev"]].append(row)
    totals = {}
    for state, rows in source.items():
        nominees = {local.name_key(row["candidate_name"]): local.group(row["ballot_party"])
                    for row in rows if local.group(row["ballot_party"]) and row["candidate_name"]}
        totals[state] = defaultdict(int)
        for row in rows:
            party = nominees.get(local.name_key(row["candidate_name"]))
            if party:
                totals[state][party] += int(row["votes"])
    workbook = openpyxl.load_workbook(local.SOURCE / "fec_2024_presidential.xlsx", read_only=True, data_only=True)
    fec_rows = list(workbook.active.values)
    header = fec_rows[0]
    differences = []
    for row in fec_rows[1:]:
        state = row[0]
        if state in totals and row[header.index("HARRIS")] and row[header.index("TRUMP")]:
            differences.extend([abs(totals[state]["D"]-row[header.index("HARRIS")]),
                                abs(totals[state]["R"]-row[header.index("TRUMP")])])
    training = local.training_rows()
    assert len(differences) == 102, len(differences)
    assert max(differences) <= 100, max(differences)
    assert all(row["presidential_year"] < row["year"] for row in training)
    assert all(row["year"]-6 in range(1976, 2025, 2) for row in training)
    report = json.loads((ROOT / "artifacts" / "senate_local_lean_research.json").read_text())
    assert report["selected"]["specification"] == "combined"
    assert report["selected"]["later_rmse"] < min(
        row["later_rmse"] for row in report["grid"] if row["specification"] == "previous"
    )
    print(json.dumps({"status": "passed", "presidential_jurisdictions": 51,
                      "max_major_party_vote_difference_from_FEC": max(differences),
                      "training_races": len(training), "selected": report["selected"]}, indent=2))


if __name__ == "__main__":
    main()
