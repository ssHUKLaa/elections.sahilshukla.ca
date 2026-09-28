"""Identify House seats absent from the 2020 and 2022 joint replays."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as stage3

DB = ROOT / "data/processed/stage2.sqlite"
CROSSWALK = ROOT / "data/reference/stage6_house_population_crosswalk.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_historical_chamber_gaps.json"
AT_LARGE = {"AK", "DE", "ND", "SD", "VT", "WY"}


def district_key(state: str, district: str) -> tuple[str, str]:
    return state, "00" if state in AT_LARGE else district


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        history = stage3.load_historical_races(connection)
        transitions = stage3.build_transitions(history)
        crosswalk = json.loads(CROSSWALK.read_text(encoding="utf-8"))
        state_to_fips = stage3.house_population_crosswalk()[1]
        fips_to_state = {code: state for state, code in state_to_fips.items()}
        rows = crosswalk["transitions"]["2020_to_2022"]
        seat_universe = {
            2020: {(fips_to_state[row["state_fips"]], overlap["prior_district"])
                   for row in rows for overlap in row["overlaps"]},
            2022: {(fips_to_state[row["state_fips"]], row["target_district"])
                   for row in rows},
        }
        report = {"source_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
                  "source_crosswalk_sha256": hashlib.sha256(CROSSWALK.read_bytes()).hexdigest(),
                  "cycles": {}}
        for cycle in (2020, 2022):
            modeled = {district_key(t.state, t.target.district) for t in transitions
                       if t.office == "house" and t.target_cycle == cycle}
            if len(seat_universe[cycle]) != 435 or not modeled <= seat_universe[cycle]:
                raise ValueError(f"House seat universe mismatch for {cycle}")
            missing = []
            for state, district in sorted(seat_universe[cycle] - modeled):
                archive_districts = (district, "01") if state in AT_LARGE else (district,)
                placeholders = ",".join("?" for _ in archive_districts)
                archive = [dict(row) for row in connection.execute(
                    f"""SELECT source_race_id,stage,special,candidate_name,ballot_party,votes,
                    result_round,winner FROM historical_results WHERE cycle=? AND office='house'
                    AND state=? AND district IN ({placeholders}) ORDER BY source_race_id,result_round""",
                    (cycle, state, *archive_districts))]
                numeric = [race for race in history if race.cycle == cycle and race.office == "house"
                           and district_key(race.state, race.district) == (state, district)]
                reconciliation = [dict(row) for row in connection.execute(
                    """SELECT status,reason,official_votes,archive_votes FROM result_reconciliation
                    WHERE cycle=? AND office='house' AND state=? AND district=?""",
                    (cycle, state, district))]
                reason = ("missing_comparable_prior" if numeric else
                          "unopposed_without_numeric_vote_total" if archive and all(
                              row["votes"] is None for row in archive) else
                          "official_archive_result_unresolved" if reconciliation and any(
                              row["status"] not in ("exact", "within_tolerance") for row in reconciliation) else
                          "no_usable_numeric_result")
                missing.append({"state": state, "district": district, "reason": reason,
                                "archive_rows": archive, "reconciliation": reconciliation,
                                "numeric_result_available": bool(numeric)})
            report["cycles"][str(cycle)] = {"seat_universe": len(seat_universe[cycle]),
                                            "modeled_seats": len(modeled),
                                            "missing_seats": missing}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({cycle: [(row["state"], row["district"], row["reason"])
                              for row in details["missing_seats"]]
                      for cycle, details in report["cycles"].items()}, indent=2))


if __name__ == "__main__":
    main()
