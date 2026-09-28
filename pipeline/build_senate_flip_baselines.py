"""Export the prior winner's party for 2026 Senate seat flip indicators."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--output", type=Path, default=ROOT / "data/reference/senate_seat_baselines_2026.json")
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        rows = connection.execute(
            """SELECT f.race_id, r.state, f.prior_winner_party, f.baseline_cycle
               FROM race_fundamentals f JOIN races r ON r.race_id=f.race_id
               WHERE r.office='senate' AND r.stage='general'
               ORDER BY r.state"""
        ).fetchall()
    if len(rows) != 35 or len({row[1] for row in rows}) != 35:
        raise ValueError("Expected one prior winner for each of 35 Senate election states")
    group = {"D": "D", "DFL": "D", "DEM/IP/WF": "D", "R": "R"}
    if any(row[2] not in group for row in rows):
        raise ValueError(f"Unreviewed prior party labels: {sorted({row[2] for row in rows} - group.keys())}")
    report = {
        "meaning": "Party that won the prior election for this Senate seat, from Stage 2 race fundamentals.",
        "stage2_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "seats": {
            race_id: {"state": state, "prior_winner_party": raw_party,
                      "prior_winner_group": group[raw_party], "baseline_cycle": cycle}
            for race_id, state, raw_party, cycle in rows
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} Senate seat baselines to {args.output}")


if __name__ == "__main__":
    main()
