"""Export prior same-numbered House seat winners for map flip indicators."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROUP = {"D": "D", "DEM": "D", "R": "R", "REP": "R"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reference/house_seat_baselines_2026.json")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        rows = connection.execute(
            """SELECT race_id, prior_winner_party, baseline_cycle
               FROM race_fundamentals WHERE race_id LIKE 'H-2026-%'
               ORDER BY race_id"""
        ).fetchall()
    if len(rows) != 435 or len({row[0] for row in rows}) != 435:
        raise ValueError("Expected 435 unique House prior-seat winners")
    if any(row[1] not in GROUP for row in rows):
        raise ValueError(f"Unreviewed House prior party: {set(row[1] for row in rows) - GROUP.keys()}")
    report = {
        "meaning": "Prior winner of the same numbered House seat; a flip is a change from this group. District boundaries may differ after redistricting.",
        "stage2_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "seats": {race_id: {"prior_winner_party": party,
                             "prior_winner_group": GROUP[party], "baseline_cycle": cycle}
                  for race_id, party, cycle in rows},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} House seat baselines to {args.output}")


if __name__ == "__main__":
    main()
