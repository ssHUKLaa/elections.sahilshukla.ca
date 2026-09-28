"""Audit historical generic-ballot trendline error at the live lead time."""

import csv
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

import national_environment as national

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "reference" / "local_lean" / "generic_topline_historical.csv"


def rows(cutoff_days: int = 43):
    house = national.parse_house()
    history = {}
    with SOURCE.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            day = datetime.strptime(row["modeldate"], "%m/%d/%Y").date()
            year = day.year if day.year % 2 == 0 else day.year+1
            if year not in house:
                continue
            cutoff = national.election_date(year)-timedelta(days=cutoff_days)
            if day > cutoff or day < cutoff-timedelta(days=180):
                continue
            d, r = float(row["dem_estimate"]), float(row["rep_estimate"])
            if d <= 0 or r <= 0:
                continue
            old = history.get(year)
            if old is None or day > old["date"]:
                history[year] = {"year": year, "date": day, "poll_margin": (d-r)/(d+r),
                                 "actual_margin": house[year], "days_old": (cutoff-day).days}
    return [{**row, "date": row["date"].isoformat(),
             "error": row["poll_margin"]-row["actual_margin"]}
            for _, row in sorted(history.items())]


def report() -> dict:
    observations = rows()
    errors = np.asarray([row["error"] for row in observations])
    return {"rows": observations, "cycles": len(observations),
            "mean_error": float(errors.mean()), "rmse": math.sqrt(float(np.mean(errors**2))),
            "error_sd": float(errors.std(ddof=1)),
            "note": "538's historical reconstructed trendline may embed retrospective methodology; verify no future-poll smoothing before using as an as-of likelihood."}


if __name__ == "__main__":
    result = report()
    path = ROOT / "artifacts" / "generic_history_research.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
