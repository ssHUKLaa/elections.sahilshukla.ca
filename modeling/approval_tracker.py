"""Audit a contemporaneous approval-to-generic-ballot change signal."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("stage4_for_approval_tracker", ROOT / "modeling" / "stage4_poll_model.py")
stage4 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = stage4
SPEC.loader.exec_module(stage4)


def approval_by_day(stage1_path: Path, cutoff: datetime) -> dict[datetime, float]:
    connection = sqlite3.connect(stage1_path)
    try:
        rows = connection.execute(
            "SELECT date,answer,AVG(CAST(pct AS REAL)) FROM approval_averages WHERE date<=? "
            "AND answer IN ('Approve','Disapprove') GROUP BY date,answer",
            (cutoff.strftime("%Y-%m-%d"),),
        ).fetchall()
    finally:
        connection.close()
    by_date = defaultdict(dict)
    for day, answer, pct in rows:
        by_date[datetime.strptime(day, "%Y-%m-%d")][answer] = pct / 100.0
    return {day: values["Approve"] - values["Disapprove"]
            for day, values in by_date.items() if len(values) == 2}


def audit(stage2_path: Path, stage1_path: Path, cutoff: datetime) -> dict:
    connection = sqlite3.connect(stage2_path)
    connection.row_factory = sqlite3.Row
    try:
        generic = stage4.generic_observations(connection, stage1_path, cutoff)
    finally:
        connection.close()
    approval = approval_by_day(stage1_path, cutoff)
    grouped = defaultdict(list)
    for item in generic:
        week = item["end_date"] - timedelta(days=item["end_date"].weekday())
        grouped[week].append(item["logratio"])
    weeks = sorted(week for week, values in grouped.items() if len(values) >= 2)
    generic_week = {week: float(np.mean(grouped[week])) for week in weeks}
    approval_dates = sorted(approval)
    approval_week = {}
    for week in weeks:
        candidates = [day for day in approval_dates if day <= week + timedelta(days=6)]
        if candidates:
            approval_week[week] = approval[candidates[-1]]
    points = []
    for week in weeks:
        previous = week - timedelta(days=14)
        if week in approval_week and previous in approval_week and previous in generic_week:
            points.append((week, approval_week[week]-approval_week[previous],
                           generic_week[week]-generic_week[previous]))
    if len(points) < 20:
        raise ValueError(f"Only {len(points)} paired approval/generic changes")
    x = np.asarray([point[1] for point in points])
    y = np.asarray([point[2] for point in points])
    beta = float(np.dot(x, y) / np.dot(x, x))
    years = sorted({point[0].year for point in points})
    by_year = {}
    for year in years:
        train = np.asarray([point[0].year != year for point in points])
        test = ~train
        slope = float(np.dot(x[train], y[train]) / np.dot(x[train], x[train]))
        by_year[str(year)] = {
            "held_out_pairs": int(test.sum()), "train_beta": slope,
            "zero_change_rmse": float(np.sqrt(np.mean(y[test]**2))),
            "approval_change_rmse": float(np.sqrt(np.mean((y[test]-slope*x[test])**2))),
        }
    return {"pairs": len(points), "beta": beta, "approval_change_sd": float(np.std(x)),
            "generic_change_sd": float(np.std(y)), "leave_year_out": by_year,
            "first_week": weeks[0].date().isoformat(), "last_week": weeks[-1].date().isoformat()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2", type=Path, default=Path("data/processed/stage2.sqlite"))
    parser.add_argument("--stage1", type=Path, default=Path("data/processed/stage1.sqlite"))
    parser.add_argument("--cutoff", default="2026-09-21")
    args = parser.parse_args()
    result = audit(args.stage2, args.stage1, datetime.strptime(args.cutoff, "%Y-%m-%d"))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
