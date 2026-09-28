"""Trace historical House model misses to candidate moves across district labels."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m


def main() -> None:
    with sqlite3.connect(ROOT / "data/processed/stage2.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
    transitions = m.stage3.build_transitions(races)
    prior_locations = defaultdict(set)
    for race in races:
        if race.office == "house":
            for candidate in race.candidates:
                name_key = m.stage3.first_last_key(candidate.name)
                prior_locations[(race.cycle, race.state, name_key)].add(race.district)
    stage6 = json.loads((ROOT / "artifacts/calibration/stage6_report.json").read_text())
    worst = {
        (cell["cycle"], row["race_id"]): row
        for cell in stage6["cells"] if cell["lead_days"] == 7
        for row in cell["largest_winner_misses"] if row["office"] == "house"
    }
    results = []
    counts = Counter()
    for transition in transitions:
        if transition.office != "house" or transition.target_cycle not in (2022, 2024):
            continue
        target = transition.target
        moves = []
        same_district = []
        for candidate in target.candidates:
            name_key = m.stage3.first_last_key(candidate.name)
            previous = prior_locations[(transition.prior_cycle, target.state, name_key)]
            if previous:
                item = {"candidate": candidate.name,
                        "prior_districts": sorted(previous), "target_district": target.district}
                if any(district != target.district for district in previous):
                    moves.append(item)
                else:
                    same_district.append(item)
        classification = ("documented_candidate_move" if moves else
                          "same_district_candidate" if same_district else
                          "no_candidate_continuity_evidence")
        counts[(target.cycle, classification)] += 1
        miss = worst.get((target.cycle, target.source_race_id))
        if miss:
            results.append({"cycle": target.cycle, "race_id": target.source_race_id,
                            "state": target.state, "district": target.district,
                            "classification": classification, "candidate_moves": moves,
                            "same_district_candidates": same_district,
                            "winner_probability": miss["winner_probability"],
                            "brier": miss["brier"]})
    output = {"scope": "historical House targets in 2022 and 2024",
              "interpretation": "Candidate movement across a district label is evidence that the prior same-number race is not comparable. Absence of such movement does not establish unchanged boundaries.",
              "counts": {f"{cycle}:{label}": value for (cycle, label), value in sorted(counts.items())},
              "largest_winner_misses": sorted(results, key=lambda row: (row["cycle"], -row["brier"]))}
    path = ROOT / "artifacts/calibration/stage6_district_continuity.json"
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": output["counts"],
                      "moved_worst_miss_count": sum(bool(row["candidate_moves"]) for row in results)}, indent=2))


if __name__ == "__main__":
    main()
