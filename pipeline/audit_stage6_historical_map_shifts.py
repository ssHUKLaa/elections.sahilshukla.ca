"""Paired diagnostic for House presidential geography shifts in the replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as stage3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--map-shifts", type=Path,
                        default=ROOT / "data/reference/stage6_historical_house_map_shifts.json")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/calibration/stage6_historical_map_shift_audit.json")
    args = parser.parse_args()
    source = json.loads(args.map_shifts.read_text(encoding="utf-8"))
    if source["stage2_database_sha256"] != hashlib.sha256(args.database.read_bytes()).hexdigest():
        raise ValueError("Map shifts do not match Stage 2 database")
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        transitions = stage3.build_transitions(stage3.load_historical_races(connection))
    cells = {}
    for cycle in (2020, 2022, 2024):
        model = stage3.fit_office_models([t for t in transitions if t.target_cycle < cycle])["house"]
        rows = []
        shifts = source["race_shifts"][str(cycle)]
        for transition in transitions:
            if transition.office != "house" or transition.target_cycle != cycle or not stage3.coordinate_eligible(transition, 0):
                continue
            delta = shifts.get(str(transition.target.source_race_id))
            if delta is None:
                raise ValueError(f"Missing map shift for {cycle} {transition.target.source_race_id}")
            residual = float(transition.target_alr[0] - stage3.transition_predict(model, transition)[0])
            rows.append((delta, residual))
        values = np.asarray(rows)
        before = float(np.sqrt(np.mean(values[:, 1]**2)))
        after = float(np.sqrt(np.mean((values[:, 1]-values[:, 0])**2)))
        cells[str(cycle)] = {"eligible_races": len(rows),
                             "DR_logratio_RMSE_without_map_shift": before,
                             "DR_logratio_RMSE_with_unit_map_shift": after,
                             "paired_RMSE_improvement": before-after,
                             "descriptive_residual_slope": float(np.dot(values[:, 0], values[:, 1])/
                                                                  np.dot(values[:, 0], values[:, 0]))}
    report = {"purpose": "Terminal-result diagnostic for a deterministic geographic feature; not direct held-today calibration or pristine selection.",
              "database_sha256": source["stage2_database_sha256"],
              "map_shifts_sha256": hashlib.sha256(args.map_shifts.read_bytes()).hexdigest(),
              "cells": cells}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(cells, indent=2))


if __name__ == "__main__":
    main()
