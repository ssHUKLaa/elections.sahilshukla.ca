"""Cycle-balanced Senate D/R poll error calibration from historical polls.

The target is poll D/R log ratio minus the eventual D/R log ratio. For a
43-day forecast, this includes any movement between poll fieldwork and the
election. The archive is an internal research input; its raw rows are not
redistributed in model artifacts.
"""

from __future__ import annotations

import csv
import argparse
import hashlib
import json
import math
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pipeline.build_stage2 import STATE_NAMES

SOURCE = ROOT / "data" / "reference" / "poll_error"
HALF_LIFE_DAYS = 30.0
MAX_POLL_AGE_DAYS = 180
ALPHAS = (10.0, 100.0, 1000.0)
SPECS = ("zero", "pooled", "pollster_population")


@dataclass(frozen=True)
class Observation:
    cycle: int
    race_key: str
    pollster: str
    population: str
    sample_size: float
    end_date: datetime
    cutoff: datetime
    error_logratio: float
    pct_d: float
    pct_r: float

    @property
    def weight(self) -> float:
        age = max(0, (self.cutoff-self.end_date).days)
        return 2.0**(-age/HALF_LIFE_DAYS)*math.sqrt(max(self.sample_size, 100)/600)


@dataclass
class FittedBias:
    specification: str
    alpha: float | None
    vectorizer: DictVectorizer | None
    regression: Ridge | None
    cycle_count: int
    race_count: int
    poll_count: int

    def predict(self, pollster: str, population: str, sample_size: float) -> float:
        if self.regression is None or self.vectorizer is None:
            return 0.0
        features = feature_row(pollster, population, sample_size, self.specification)
        return float(self.regression.predict(self.vectorizer.transform([features]))[0])


def election_day(year: int) -> datetime:
    november_first = datetime(year, 11, 1)
    first_monday = november_first + timedelta(days=(-november_first.weekday()) % 7)
    return first_monday + timedelta(days=1)


def canonical_pollster(value: str) -> str:
    value = re.sub(r"\*+$", "", value.strip())
    value = re.sub(r"\s*\(([DR])\)$", "", value)
    return value.casefold().strip()


def feature_row(pollster: str, population: str, sample_size: float, specification: str) -> dict[str, str | float]:
    if specification == "pooled":
        return {"constant": 1.0}
    if specification == "pollster_population":
        return {
            "constant": 1.0,
            "pollster": canonical_pollster(pollster),
            "population": (population or "unknown").upper(),
            "log_n": math.log(max(sample_size, 100))/10,
        }
    if specification == "zero":
        return {}
    raise ValueError(specification)


def load_observations(races: list[Any], cutoff_days: int = 43) -> tuple[list[Observation], dict[str, Any]]:
    manifest = json.loads((SOURCE / "source_manifest.json").read_text(encoding="utf-8"))["senate_polls"]
    path = SOURCE / manifest["path"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("Historical Senate poll archive differs from its frozen manifest")
    by_location: dict[tuple[int, str], list[tuple[str, float]]] = defaultdict(list)
    for race in races:
        if race.office != "senate":
            continue
        votes = Counter()
        for candidate in race.candidates:
            votes[candidate.group] += candidate.votes
        if votes["D"] > 0 and votes["R"] > 0:
            by_location[(race.cycle, race.state)].append((
                race.source_race_id, math.log(votes["D"]/votes["R"])
            ))
    observations = []
    excluded = Counter()
    seen = set()
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            try:
                cycle = int(row["year"])
                state = STATE_NAMES[row["state"].strip().upper()]
                dem, rep = float(row["dem"]), float(row["rep"])
                end_date = datetime.strptime(row["end_date"], "%Y/%m/%d")
                sample_size = float(row["sample_size"] or 600)
            except (KeyError, TypeError, ValueError):
                excluded["invalid_field"] += 1
                continue
            matches = by_location[(cycle, state)]
            if len(matches) != 1 or row["overlapping_special_election"]:
                excluded["ambiguous_or_special_race"] += 1
                continue
            cutoff = election_day(cycle)-timedelta(days=cutoff_days)
            age = (cutoff-end_date).days
            if age < 0 or age > MAX_POLL_AGE_DAYS or dem <= 0 or rep <= 0:
                excluded["outside_cutoff_or_missing_major_party"] += 1
                continue
            key = (matches[0][0], canonical_pollster(row["pollster"]), row["start_date"], row["end_date"], dem, rep)
            if key in seen:
                excluded["duplicate"] += 1
                continue
            seen.add(key)
            observations.append(Observation(
                cycle, matches[0][0], row["pollster"], row["sample_type"],
                sample_size, end_date, cutoff, math.log(dem/rep)-matches[0][1],
                dem, rep,
            ))
    return observations, {
        "source_url": manifest["url"], "source_sha256": manifest["sha256"],
        "cutoff_days": cutoff_days, "max_age_days": MAX_POLL_AGE_DAYS,
        "eligible_polls": len(observations),
        "eligible_races": len({row.race_key for row in observations}),
        "polls_by_cycle": dict(sorted(Counter(row.cycle for row in observations).items())),
        "excluded": dict(excluded),
    }


def fit(rows: list[Observation], specification: str, alpha: float | None = None) -> FittedBias:
    if not rows:
        raise ValueError("No historical Senate polls supplied")
    cycles = {row.cycle for row in rows}
    races = {(row.cycle, row.race_key) for row in rows}
    if specification == "zero":
        return FittedBias(specification, None, None, None, len(cycles), len(races), len(rows))
    vectorizer = DictVectorizer(sparse=False)
    x = vectorizer.fit_transform([
        feature_row(row.pollster, row.population, row.sample_size, specification)
        for row in rows
    ])
    y = np.asarray([row.error_logratio for row in rows])
    races_per_cycle = Counter(cycle for cycle, _ in races)
    weight_per_race = defaultdict(float)
    for row in rows:
        weight_per_race[(row.cycle, row.race_key)] += row.weight
    weights = np.asarray([
        row.weight / (races_per_cycle[row.cycle]*weight_per_race[(row.cycle, row.race_key)])
        for row in rows
    ])
    weights *= len(rows)/weights.sum()
    regression = Ridge(alpha=float(alpha or 10.0)).fit(x, y, sample_weight=weights)
    return FittedBias(specification, alpha, vectorizer, regression, len(cycles), len(races), len(rows))


def score_predictor(rows: list[Observation], predictor: Any) -> dict[str, float | int]:
    by_race = defaultdict(list)
    for row in rows:
        by_race[row.race_key].append((
            row.error_logratio - predictor(row),
            row.weight,
        ))
    errors = np.asarray([
        np.average([value for value, _ in values], weights=[weight for _, weight in values])
        for values in by_race.values()
    ])
    return {
        "races": len(by_race), "polls": len(rows),
        "mean_error_margin_points_approx": float(50*errors.mean()),
        "rmse_margin_points_approx": float(50*np.sqrt(np.mean(errors**2))),
        "mae_margin_points_approx": float(50*np.mean(np.abs(errors))),
    }


def score(model: FittedBias, rows: list[Observation]) -> dict[str, float | int]:
    return score_predictor(
        rows, lambda row: model.predict(row.pollster, row.population, row.sample_size)
    )


def select_and_validate(rows: list[Observation]) -> tuple[FittedBias, dict[str, Any]]:
    selected, grid = choose_spec(rows, 2022)
    pre_2024 = [row for row in rows if row.cycle < 2024]
    held_2024 = [row for row in rows if row.cycle == 2024]
    model_2024 = fit(pre_2024, selected["specification"], selected["alpha"])
    zero_2024 = score(fit(pre_2024, "zero"), held_2024)
    selected_2024 = score(model_2024, held_2024)
    final = fit(rows, selected["specification"], selected["alpha"])
    return final, {
        "selection_rule": "lowest mean whole-cycle race-level RMSE on rolling 2016-2022 folds",
        "grid": grid, "selected": selected,
        "held_out_2024": {"selected": selected_2024, "no_correction": zero_2024},
        "training": {"cycles": final.cycle_count, "races": final.race_count, "polls": final.poll_count},
        "current_default_correction_logratio": final.predict("unknown", "LV", 600),
    }


def choose_spec(rows: list[Observation], latest_tuning_cycle: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cycles = sorted({row.cycle for row in rows})
    tuning_cycles = [cycle for cycle in cycles if 2016 <= cycle <= latest_tuning_cycle]
    candidate_specs = [("zero", None), ("pooled", 10.0)] + [
        ("pollster_population", alpha) for alpha in ALPHAS
    ]
    grid = []
    for specification, alpha in candidate_specs:
        folds = []
        for cycle in tuning_cycles:
            train = [row for row in rows if row.cycle < cycle]
            holdout = [row for row in rows if row.cycle == cycle]
            if len({row.cycle for row in train}) < 3 or not holdout:
                continue
            fitted = fit(train, specification, alpha)
            folds.append({"cycle": cycle, **score(fitted, holdout)})
        grid.append({
            "specification": specification, "alpha": alpha, "folds": folds,
            "mean_cycle_rmse": float(np.mean([fold["rmse_margin_points_approx"] for fold in folds])),
        })
    selected = min(grid, key=lambda item: item["mean_cycle_rmse"])
    return {"specification": selected["specification"], "alpha": selected["alpha"]}, grid


def fit_through_cycle(rows: list[Observation], max_cycle: int) -> tuple[FittedBias, dict[str, Any]]:
    subset = [row for row in rows if row.cycle <= max_cycle]
    selected, grid = choose_spec(subset, min(max_cycle, 2022))
    return fit(subset, selected["specification"], selected["alpha"]), {
        "training_through_cycle": max_cycle, "selected": selected, "grid": grid,
    }


def serialize(model: FittedBias) -> dict[str, Any]:
    output: dict[str, Any] = {
        "specification": model.specification, "alpha": model.alpha,
        "cycle_count": model.cycle_count, "race_count": model.race_count,
        "poll_count": model.poll_count,
    }
    if model.regression is not None and model.vectorizer is not None:
        output["intercept"] = float(model.regression.intercept_)
        output["coefficients"] = {
            name: float(value)
            for name, value in zip(model.vectorizer.get_feature_names_out(), model.regression.coef_)
            if abs(value) > 1e-10
        }
    return output


def restore_source() -> None:
    manifest = json.loads((SOURCE / "source_manifest.json").read_text(encoding="utf-8"))["senate_polls"]
    path = SOURCE / manifest["path"]
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sha256"]:
        print(json.dumps({"status": "verified", "path": str(path)}))
        return
    content = urllib.request.urlopen(manifest["url"], timeout=60).read()
    if hashlib.sha256(content).hexdigest() != manifest["sha256"]:
        raise RuntimeError("Historical Senate poll archive has changed from frozen snapshot")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    print(json.dumps({"status": "restored", "path": str(path)}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", action="store_true", required=True)
    parser.parse_args()
    restore_source()
