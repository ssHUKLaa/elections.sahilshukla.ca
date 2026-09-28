"""Derive historical presidential-vote changes across House district maps.

The source sheets are credited to The Downballot. Only D/R log-odds
differences are published here, not the underlying district vote tables.
"""

from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as stage3
SOURCE = ROOT / "data/raw/census_districts"
OUTPUT = ROOT / "data/reference/stage6_historical_house_map_shifts.json"
DATABASE = ROOT / "data/processed/stage2.sqlite"
SHEETS = {
    "2018": ("downballot_2016_pres_2018_districts.csv", 3, 4,
             "https://docs.google.com/spreadsheets/d/1zLNAuRqPauss00HDz4XbTH2HqsCzMe0pR8QmD1K8jk8/edit?gid=0"),
    "2020": ("downballot_2020_pres_2020_districts.csv", 3, 4,
             "https://docs.google.com/spreadsheets/d/1XbUXnI9OyfAuhP5P3vWtMuGc5UJlrhXbzZo3AwMuHtk/edit?gid=0"),
    "2020_2016_vote": ("downballot_2020_pres_2020_districts.csv", 5, 6,
             "https://docs.google.com/spreadsheets/d/1XbUXnI9OyfAuhP5P3vWtMuGc5UJlrhXbzZo3AwMuHtk/edit?gid=0"),
    "2022": ("downballot_2020_pres_2022_districts.csv", 3, 4,
             "https://docs.google.com/spreadsheets/d/1CKngqOp8fzU22JOlypoxNsxL6KSAH920Whc-rd7ebuM/edit?gid=1871835782"),
    "2024": ("downballot_2020_pres_2024_districts.csv", 6, 7,
             "https://docs.google.com/spreadsheets/d/1ng1i_Dm_RMDnEvauH44pgE6JCUsapcuu8F2pCfeLWFo/edit?gid=620838163"),
}


def read_sheet(name: str) -> tuple[dict[str, tuple[float, float]], dict]:
    filename, d_column, r_column, url = SHEETS[name]
    path = SOURCE / filename
    odds = {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.reader(stream):
            if not row or len(row[0]) != 5 or row[0][2] != "-":
                continue
            district = row[0]
            d, r = float(row[d_column]), float(row[r_column])
            if d <= 0 or r <= 0 or district in odds:
                raise ValueError(f"Invalid presidential row: {name} {district}")
            odds[district] = d, r
    if len(odds) != 435:
        raise ValueError(f"Expected 435 districts in {filename}: {len(odds)}")
    return odds, {"url": url, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                  "districts": len(odds)}


def district_code(state: str, district: str) -> str:
    return f"{state}-{'AL' if district in ('AL', '00') else district.zfill(2)}"


def source_code(table: dict, state: str, district: str) -> str:
    code = district_code(state, district)
    if code not in table and f"{state}-AL" in table:
        return f"{state}-AL"
    return code


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DATABASE)
    args = parser.parse_args()
    tables, sources = {}, {}
    for name in SHEETS:
        tables[name], sources[name] = read_sheet(name)
    shifts = {}
    pairs = ((2020, "2018", "2020_2016_vote"), (2022, "2020", "2022"),
             (2024, "2022", "2024"))
    for cycle, old, new in pairs:
        shared = tables[old].keys() & tables[new].keys()
        shifts[str(cycle)] = {district: round(math.log(tables[new][district][0]/tables[new][district][1])
                                                - math.log(tables[old][district][0]/tables[old][district][1]), 8)
                              for district in sorted(shared)}
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        transitions = stage3.build_transitions(stage3.load_historical_races(connection))
    crosswalk, state_codes = stage3.house_population_crosswalk()
    race_shifts = {}
    coverage = {}
    for cycle, old, new in pairs:
        rows = {}
        missing = []
        for transition in transitions:
            if transition.office != "house" or transition.target_cycle != cycle:
                continue
            target = transition.target
            target_district = source_code(tables[new], target.state, target.district)
            if target_district not in tables[new]:
                missing.append(target.source_race_id)
                continue
            if transition.prior_selection.startswith("population_weighted"):
                row = crosswalk.get((cycle, state_codes[target.state], target.district))
                if row is None:
                    missing.append(target.source_race_id)
                    continue
                components = [(item["population"], source_code(tables[old], target.state, item["prior_district"]))
                              for item in row["overlaps"]]
                available = [(weight, tables[old][district]) for weight, district in components
                             if district in tables[old]]
                total = sum(weight for weight, _ in available)
                if not total:
                    missing.append(target.source_race_id)
                    continue
                old_d = sum(weight*votes[0] for weight, votes in available)/total
                old_r = sum(weight*votes[1] for weight, votes in available)/total
            else:
                prior = transition.prior
                old_district = source_code(tables[old], prior.state, prior.district)
                if old_district not in tables[old]:
                    missing.append(target.source_race_id)
                    continue
                old_d, old_r = tables[old][old_district]
            new_d, new_r = tables[new][target_district]
            rows[str(target.source_race_id)] = round(math.log(new_d/new_r)-math.log(old_d/old_r), 8)
        race_shifts[str(cycle)] = rows
        coverage[str(cycle)] = {"numeric_house_transitions": sum(t.office == "house" and t.target_cycle == cycle
                                                                  for t in transitions),
                                "map_shift_races": len(rows), "missing_source_race_ids": missing}
    report = {
        "method": "Change in Democratic/Republican presidential vote log odds on each House transition's selected prior versus the target district map. Population-crosswalk priors use the same old-district population weights. Source percentages are rounded.",
        "sources": sources,
        "source_credit": "The Downballot (https://www.the-downballot.com/p/data)",
        "limitations": [
            "Same-number districts can have changed boundaries; a disappeared or newly numbered district has no matched shift.",
            "The 2024-map source reports whole percentage points, so 2024 changes include rounding noise.",
            "These are presidential-vote shifts between maps, not House vote retabulations."],
        "districts_with_shift": {cycle: len(rows) for cycle, rows in shifts.items()},
        "shifts": shifts,
        "race_shifts": race_shifts,
        "race_coverage": coverage,
        "stage2_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "crosswalk_sha256": hashlib.sha256((ROOT / "data/reference/stage6_house_population_crosswalk.json").read_bytes()).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUTPUT), "coverage": report["districts_with_shift"]}))


if __name__ == "__main__":
    main()
