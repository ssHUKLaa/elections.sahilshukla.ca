"""Provisional cycle-blocked generic-ballot / approval ablation.

Historical 538 generic estimates were rebuilt in 2020, so the 1996-2016
exercise is a research diagnostic, not an as-of release gate.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from sklearn.linear_model import Ridge

import generic_history
import national_environment as national

ROOT = Path(__file__).resolve().parents[1]
RAW_2020 = ROOT / "data/raw/historical/20260921T204524Z/538_archive_generic_ballot_polls.csv"
OUTPUT = ROOT / "artifacts/national_signal_ablation.json"
RIDGE_ALPHA = 2.0


def make_rows() -> list[dict]:
    approval = {r["year"]: r for r in national.cycle_rows(
        national.parse_house(), national.parse_approval(), cutoff_days=43
    )}
    result = []
    for poll in generic_history.rows(cutoff_days=43):
        row = approval[poll["year"]]
        result.append({
            "year": poll["year"], "generic_margin": 100 * poll["poll_margin"],
            "actual_margin": 100 * poll["actual_margin"],
            "previous_house_margin": 100 * row["previous_margin"],
            "signed_approval_net": 100 * row["signed_approval_net"],
            "approval_age_days": row["approval_age_days"],
            "generic_date": poll["date"], "approval_last_end": row["approval_last_end"],
        })
    return result


def predict(train: list[dict], test: dict, use_approval: bool,
            alpha: float = RIDGE_ALPHA) -> float:
    """Predict eventual vote as generic plus a learned historical correction."""
    residual = np.array([r["actual_margin"] - r["generic_margin"] for r in train])
    correction = float(residual.mean())
    if use_approval:
        x = np.array([r["signed_approval_net"] for r in train], dtype=float)
        center = float(x.mean())
        scale = float(x.std(ddof=0))
        if scale > 1e-9:
            model = Ridge(alpha=alpha, fit_intercept=True)
            model.fit(((x-center)/scale).reshape(-1, 1), residual)
            correction = float(model.predict(
                np.array([[(test["signed_approval_net"]-center)/scale]])
            )[0])
    return test["generic_margin"] + correction


def score(predictions: list[dict], key: str) -> dict:
    errors = np.array([p[key] - p["actual_margin"] for p in predictions])
    return {"n": len(errors), "mae_points": float(np.mean(np.abs(errors))),
            "rmse_points": float(np.sqrt(np.mean(errors**2))),
            "mean_error_points": float(np.mean(errors))}


def predict_current_generic(train: list[dict], test: dict, use_approval: bool,
                            alpha: float = RIDGE_ALPHA) -> float:
    """Predict the cutoff-date generic reading from prior election and approval."""
    fields = ["previous_house_margin"]
    if use_approval:
        fields.append("signed_approval_net")
    x = np.array([[r[field] for field in fields] for r in train], dtype=float)
    center, scale = x.mean(axis=0), x.std(axis=0)
    scale[scale < 1e-9] = 1.0
    model = Ridge(alpha=alpha, fit_intercept=True)
    model.fit((x-center)/scale, [r["generic_margin"] for r in train])
    test_x = np.array([[test[field] for field in fields]], dtype=float)
    return float(model.predict((test_x-center)/scale)[0])


def score_generic(predictions: list[dict], key: str) -> dict:
    errors = np.array([p[key] - p["generic_margin"] for p in predictions])
    return {"n": len(errors), "mae_points": float(np.mean(np.abs(errors))),
            "rmse_points": float(np.sqrt(np.mean(errors**2))),
            "mean_error_points": float(np.mean(errors))}


def raw_2020_check(train: list[dict]) -> dict:
    """Distinct 2020 source/method: 30-day raw LV/RV poll mean, one row per poll."""
    cutoff = national.election_date(2020) - timedelta(days=43)
    latest_by_poll = {}
    with RAW_2020.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row["cycle"] != "2020" or row["population"] not in ("lv", "rv"):
                continue
            end = datetime.strptime(row["end_date"], "%m/%d/%y").date()
            if not cutoff-timedelta(days=30) <= end <= cutoff:
                continue
            created = datetime.strptime(row["created_at"], "%m/%d/%y %H:%M").date()
            if created > cutoff:
                continue
            try:
                dem, rep = float(row["dem"]), float(row["rep"])
            except ValueError:
                continue
            if dem <= 0 or rep <= 0:
                continue
            old = latest_by_poll.get(row["poll_id"])
            if old is None or (row["population"] == "lv" and old["population"] != "lv"):
                latest_by_poll[row["poll_id"]] = {"population": row["population"],
                                                   "margin": 100*(dem-rep)/(dem+rep)}
    generic = float(np.mean([r["margin"] for r in latest_by_poll.values()]))
    national_row = {r["year"]: r for r in national.cycle_rows(
        national.parse_house(), national.parse_approval(), cutoff_days=43
    )}[2020]
    test = {"year": 2020, "generic_margin": generic,
            "signed_approval_net": 100*national_row["signed_approval_net"],
            "actual_margin": 100*national_row["margin"]}
    return {"poll_count": len(latest_by_poll), "cutoff": cutoff.isoformat(),
            "source_method": "raw 538 LV/RV polls, unweighted 30-day mean; not comparable to reconstructed trendline",
            **test, "generic_calibrated": predict(train, test, False),
            "generic_plus_approval": predict(train, test, True),
            "current_generic_from_previous_house": predict_current_generic(
                train, {**test, "previous_house_margin": 100*national_row["previous_margin"]}, False),
            "current_generic_from_previous_house_and_approval": predict_current_generic(
                train, {**test, "previous_house_margin": 100*national_row["previous_margin"]}, True)}


def report() -> dict:
    national.verify_sources()
    rows = make_rows()
    predictions = []
    for index, row in enumerate(rows):
        if index < 5:
            continue
        train = rows[:index]
        predictions.append({**row,
            "generic_raw": row["generic_margin"],
            "generic_calibrated": predict(train, row, False),
            "generic_plus_approval": predict(train, row, True),
            "current_generic_from_previous_house": predict_current_generic(train, row, False),
            "current_generic_from_previous_house_and_approval": predict_current_generic(train, row, True)})
    paired = np.array([
        abs(p["generic_plus_approval"]-p["actual_margin"])
        - abs(p["generic_calibrated"]-p["actual_margin"])
        for p in predictions
    ])
    sensitivity = {}
    for alpha in (0.5, 2.0, 8.0):
        comparison = []
        for index, row in enumerate(rows):
            if index < 5:
                continue
            train = rows[:index]
            comparison.append({**row,
                "generic_plus_approval": predict(train, row, True, alpha),
                "current_generic_from_previous_house": predict_current_generic(train, row, False, alpha),
                "current_generic_from_previous_house_and_approval": predict_current_generic(train, row, True, alpha)})
        sensitivity[str(alpha)] = {
            "approval_after_generic": score(comparison, "generic_plus_approval"),
            "current_generic_previous_house": score_generic(comparison, "current_generic_from_previous_house"),
            "current_generic_previous_house_and_approval": score_generic(
                comparison, "current_generic_from_previous_house_and_approval"),
        }
    return {
        "design": {"target": "eventual national House two-party margin, not held-today support",
                   "historical_cutoff_days": 43, "expanding_train_min_cycles": 5,
                   "training_for_each_test": "all earlier generic-ballot cycles only",
                   "approval_feature": "president-party-signed net approval, as of cutoff",
                   "approval_model": "ridge on outcome-minus-generic residual; alpha fixed at 2 after standardizing approval",
                   "source_warning": "1996-2016 538 trendline reconstructed in 2020; its as-of behavior is unverified"},
        "overlap_cycles": [r["year"] for r in rows],
        "rolling_predictions": predictions,
        "rolling_scores": {name: score(predictions, name) for name in
                           ("generic_raw", "generic_calibrated", "generic_plus_approval")},
        "current_generic_proxy_scores": {name: score_generic(predictions, name) for name in
            ("current_generic_from_previous_house", "current_generic_from_previous_house_and_approval")},
        "approval_minus_calibrated_generic_absolute_error_points_by_cycle": paired.tolist(),
        "approval_better_cycle_count": int(np.sum(paired < 0)),
        "ridge_sensitivity": sensitivity,
        "raw_2020_separate_check": raw_2020_check(rows),
    }


if __name__ == "__main__":
    result = report()
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"rolling_scores": result["rolling_scores"],
                      "current_generic_proxy_scores": result["current_generic_proxy_scores"],
                      "approval_better_cycle_count": result["approval_better_cycle_count"],
                      "raw_2020_separate_check": result["raw_2020_separate_check"]}, indent=2))
