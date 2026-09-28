"""Historical ballot-structure adjustments for the current-support prior.

Only past election results enter the fit. Poll weights are never multiplied:
the ordinary Gaussian update gives more weight to polls when its prior widens.
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

import numpy as np


RIDGE_GRID = (0.1, 1.0, 10.0, 100.0, 1000.0, math.inf)


def ballot_class(groups: set[str], prior_other_share: float) -> str:
    if "O" not in groups:
        return "ordinary"
    if len(groups & {"D", "R"}) == 1:
        return "one_major_plus_other"
    if {"D", "R"} <= groups and prior_other_share < 1e-8:
        return "other_debut"
    return "ordinary"


def _design(transition: Any, stage3: Any) -> np.ndarray:
    target_groups = {candidate.group for candidate in transition.target.candidates}
    major = next(iter(target_groups & {"D", "R"}))
    signed_lean = float(transition.prior_alr[0]) * (1 if major == "D" else -1)
    return np.array([1.0, np.clip(signed_lean, -5.0, 5.0),
                     float(transition.office == "senate"),
                     float(transition.office == "governor")])


def _ridge_fit(x: np.ndarray, y: np.ndarray, ridge: float) -> np.ndarray:
    if math.isinf(ridge):
        return np.array([float(np.mean(y)), 0.0, 0.0, 0.0])
    penalty = np.diag([0.0, ridge, ridge, ridge])
    return np.linalg.solve(x.T @ x + penalty, x.T @ y)


def fit(transitions: list[Any], models: dict[str, Any], stage3: Any) -> dict[str, Any]:
    """Estimate novelty variance and single-major-party share from past races."""
    records: dict[int, list[tuple[Any, float, bool]]] = defaultdict(list)
    for transition in transitions:
        old = {candidate.group for candidate in transition.prior.candidates}
        new = {candidate.group for candidate in transition.target.candidates}
        debut = {"D", "R", "O"} <= new and "O" not in old
        for coordinate in (0, 1):
            eligible = ({"D", "R"} <= old and {"D", "R"} <= new and
                        (coordinate == 0 or "O" in new and ("O" in old or debut)))
            if eligible:
                prediction = stage3.transition_predict(models[transition.office], transition)
                records[coordinate].append((transition,
                                            float(transition.target_alr[coordinate]-prediction[coordinate]),
                                            debut))
    novelty = {}
    for coordinate, rows in records.items():
        cycle_office: dict[tuple[int, str], list[float]] = defaultdict(list)
        for transition, residual, _ in rows:
            cycle_office[(transition.target_cycle, transition.office)].append(residual)
        means = {key: float(np.mean(values)) for key, values in cycle_office.items()}
        state_cycle: dict[tuple[int, str], list[float]] = defaultdict(list)
        for transition, residual, _ in rows:
            state_cycle[(transition.target_cycle, transition.state)].append(
                residual-means[(transition.target_cycle, transition.office)])
        state_means = {key: float(np.mean(values)) for key, values in state_cycle.items()}
        local = [(transition, residual-means[(transition.target_cycle, transition.office)]
                  -state_means[(transition.target_cycle, transition.state)], debut)
                 for transition, residual, debut in rows]
        office_scale = {office: float(np.std([value for tr, value, _ in local if tr.office == office], ddof=1))
                        for office in stage3.OFFICES}
        debut_values = [value/office_scale[tr.office] for tr, value, debut in local if debut]
        usual_values = [value/office_scale[tr.office] for tr, value, debut in local if not debut]
        ratio = float(np.std(debut_values, ddof=1)/np.std(usual_values, ddof=1))
        novelty[str(coordinate)] = {"local_sd_multiplier": max(1.0, ratio),
                                   "unconstrained_sd_ratio": ratio,
                                   "debut_count": len(debut_values),
                                   "comparison_count": len(usual_values)}

    structural = [tr for tr in transitions
                  if len({candidate.group for candidate in tr.target.candidates} & {"D", "R"}) == 1
                  and "O" in {candidate.group for candidate in tr.target.candidates}]
    x = np.vstack([_design(tr, stage3) for tr in structural])
    y = np.array([tr.target_alr[1] for tr in structural])
    cycles = sorted({tr.target_cycle for tr in structural})
    scores = {}
    for ridge in RIDGE_GRID:
        errors = []
        for cycle in cycles:
            train = np.array([tr.target_cycle != cycle for tr in structural])
            if train.sum() < 20 or (~train).sum() == 0:
                continue
            coefficient = _ridge_fit(x[train], y[train], ridge)
            errors.extend((y[~train]-x[~train] @ coefficient).tolist())
        scores[str(ridge)] = float(np.mean(np.square(errors)))
    selected = min(RIDGE_GRID, key=lambda ridge: scores[str(ridge)])
    coefficient = _ridge_fit(x, y, selected)
    residual_sd = float(np.std(y-x @ coefficient, ddof=4))
    return {"other_debut": novelty,
            "one_major_plus_other": {"coefficient": coefficient.tolist(),
                                     "residual_sd": residual_sd,
                                     "ridge": "intercept_only" if math.isinf(selected) else selected,
                                     "ridge_cycle_cv_mse": scores,
                                     "training_count": len(structural),
                                     "office_counts": {office: sum(tr.office == office for tr in structural)
                                                       for office in stage3.OFFICES}}}


def one_major_log_odds(item: dict[str, Any], fit_result: dict[str, Any], stage3: Any) -> float:
    groups = {stage3.party_group(candidate["party"]) for candidate in item["candidates"]}
    major = next(iter(groups & {"D", "R"}))
    signed_lean = float(stage3.alr(item["prior_shares"])[0]) * (1 if major == "D" else -1)
    x = np.array([1.0, np.clip(signed_lean, -5.0, 5.0),
                  float(item["race"]["office"] == "senate"),
                  float(item["race"]["office"] == "governor")])
    return float(x @ fit_result["one_major_plus_other"]["coefficient"])
