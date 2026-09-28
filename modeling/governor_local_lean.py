"""Historically fitted governor lean relative to the national House vote."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import Ridge

ROOT = Path(__file__).resolve().parents[1]
MODELING = ROOT / "modeling"
if str(MODELING) not in sys.path:
    sys.path.insert(0, str(MODELING))

try:
    from modeling import fundamentals_features_2026 as fundamentals
    from modeling import stage3_results_baseline as stage3
except ModuleNotFoundError:
    import fundamentals_features_2026 as fundamentals
    import stage3_results_baseline as stage3

from national_environment import parse_house
from senate_local_lean import load_presidential

FEATURES = {
    "previous_governor": ("prior_governor_lean",),
    "presidential": ("presidential_lean",),
    "previous_and_presidential": ("prior_governor_lean", "presidential_lean"),
    "previous_presidential_open": ("prior_governor_lean", "presidential_lean", "open_seat_signed"),
    "previous_presidential_incumbent": (
        "prior_governor_lean", "presidential_lean", "incumbent_signed",
    ),
    "previous_presidential_open_experience": (
        "prior_governor_lean", "presidential_lean", "open_seat_signed",
        "other_prior_elected_winner_signed",
    ),
    "previous_presidential_open_incumbent_experience": (
        "prior_governor_lean", "presidential_lean", "open_seat_signed",
        "incumbent_signed", "other_prior_elected_winner_signed",
    ),
}
RIDGE_GRID = (0.01, 0.1, 1.0, 10.0)
UNCERTAINTY_GROUP_MIN_N = 5


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def two_party_margin(shares: np.ndarray | list[float]) -> float | None:
    values = np.asarray(shares, dtype=float)
    total = float(values[0] + values[1])
    if not np.isfinite(total) or total <= 0:
        return None
    return float((values[0] - values[1]) / total)


def prior_presidential_lean(presidential: dict[int, dict[str, float]],
                            year: int, state: str) -> tuple[int, float] | None:
    eligible = [cycle for cycle in presidential if cycle < year and state in presidential[cycle]]
    if not eligible:
        return None
    cycle = max(eligible)
    return cycle, float(presidential[cycle][state])


def _feature_row(prior: Any, target: Any, house: dict[int, float],
                 presidential: dict[int, dict[str, float]],
                 by_state: dict[str, list[Any]]) -> dict[str, Any] | None:
    prior_groups = {candidate.group for candidate in prior.candidates}
    target_groups = {candidate.group for candidate in target.candidates}
    if not {"D", "R"} <= prior_groups or not {"D", "R"} <= target_groups:
        return None
    previous_margin = two_party_margin(stage3.group_shares(prior))
    target_margin = two_party_margin(stage3.group_shares(target))
    if previous_margin is None or target_margin is None:
        return None
    if prior.cycle not in house or target.cycle not in house:
        return None
    pres = prior_presidential_lean(presidential, target.cycle, target.state)
    if pres is None:
        return None
    winner = fundamentals._winner(prior)
    if winner is None:
        return None
    prior_key = stage3.first_last_key(winner.name), winner.group
    _, experience, running = fundamentals._candidate_features(
        [(candidate.name, candidate.group) for candidate in target.candidates],
        prior_key, fundamentals._past_winners(by_state[target.state], target.cycle),
    )
    open_seat = (0.0 if running or winner.group not in {"D", "R"}
                 else (1.0 if winner.group == "D" else -1.0))
    incumbent = (1.0 if winner.group == "D" else -1.0) if running and winner.group in {"D", "R"} else 0.0
    presidential_lean = pres[1]
    return {
        "year": target.cycle,
        "state": target.state,
        "prior_race_id": prior.source_race_id,
        "prior_cycle": prior.cycle,
        "prior_margin": previous_margin,
        "target_margin": target_margin,
        "prior_governor_lean": previous_margin - house[prior.cycle],
        "presidential_lean": presidential_lean,
        "presidential_year": pres[0],
        "open_seat_signed": open_seat,
        "incumbent_signed": incumbent,
        "incumbent_running": bool(running),
        "cross_party_incumbent": bool(
            incumbent and presidential_lean and np.sign(incumbent) != np.sign(presidential_lean)
        ),
        "signals_disagree": bool((previous_margin - house[prior.cycle]) * presidential_lean < 0),
        "strongly_partisan": bool(abs(presidential_lean) >= 0.15),
        "target_house_margin": house[target.cycle],
        "other_prior_elected_winner_signed": experience,
        "target_lean": target_margin - house[target.cycle],
    }


def training_rows(transitions: list[Any], historical: list[Any],
                  house: dict[int, float] | None = None,
                  presidential: dict[int, dict[str, float]] | None = None,
                  exclusions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    house = house if house is not None else parse_house()
    presidential = presidential if presidential is not None else load_presidential()
    by_state = fundamentals._history_index(historical)
    rows = []
    for transition in transitions:
        if transition.office != "governor" or transition.target_cycle >= 2026:
            continue
        prior_groups = {candidate.group for candidate in transition.prior.candidates}
        target_groups = {candidate.group for candidate in transition.target.candidates}
        if not {"D", "R"} <= prior_groups or not {"D", "R"} <= target_groups:
            if exclusions is not None:
                exclusions.append({
                    "state": transition.state,
                    "target_cycle": transition.target_cycle,
                    "prior_cycle": transition.prior_cycle,
                    "reason": "prior_or_target_missing_democratic_or_republican_candidate",
                    "prior_groups": sorted(prior_groups),
                    "target_groups": sorted(target_groups),
                })
            continue
        row = _feature_row(transition.prior, transition.target, house, presidential, by_state)
        if row is not None:
            rows.append(row)
    return rows


def _matrix(rows: list[dict[str, Any]], specification: str) -> np.ndarray:
    columns = FEATURES[specification]
    return np.asarray([[row[column] for column in columns] for row in rows], dtype=float)


def _fit(rows: list[dict[str, Any]], specification: str, alpha: float) -> Ridge:
    return Ridge(alpha=alpha, fit_intercept=True).fit(
        _matrix(rows, specification), [row["target_lean"] for row in rows]
    )


def fit_model(rows: list[dict[str, Any]], specification: str, alpha: float) -> Ridge:
    if specification not in FEATURES:
        raise ValueError(f"Unknown governor local-lean specification: {specification}")
    if not rows:
        raise ValueError("Cannot fit governor local lean without training rows")
    return _fit(rows, specification, alpha)


def predict_row(model: Ridge, row: dict[str, Any], specification: str) -> float:
    return float(model.predict(_matrix([row], specification))[0])


def recenter_candidate_draws(draws: np.ndarray, groups: list[str],
                             national_logratio: float | np.ndarray,
                             predicted_local_lean: float,
                             uncertainty_logratio_sd: float | None = None,
                             uncertainty_seed: int = 0) -> tuple[np.ndarray, dict[str, float]]:
    """Recenter D/R draws and enforce the historical out-of-cycle error floor."""
    d_indices = [index for index, group in enumerate(groups) if group == "D"]
    r_indices = [index for index, group in enumerate(groups) if group == "R"]
    if not d_indices or not r_indices:
        return draws, {"applied": 0.0}
    d = draws[:, d_indices].sum(axis=1)
    r = draws[:, r_indices].sum(axis=1)
    existing = np.log(np.clip(d, 1e-9, None) / np.clip(r, 1e-9, None))
    national = np.broadcast_to(np.asarray(national_logratio, dtype=float), existing.shape)
    local_residual = existing - national
    local_residual -= local_residual.mean()
    residual_sd_before = float(local_residual.std(ddof=1)) if len(local_residual) > 1 else 0.0
    target_residual_sd = float(uncertainty_logratio_sd or 0.0)
    uncertainty_multiplier: float | None = 1.0
    if target_residual_sd > residual_sd_before:
        if residual_sd_before > 1e-12:
            uncertainty_multiplier = target_residual_sd / residual_sd_before
            local_residual *= uncertainty_multiplier
        elif target_residual_sd > 0:
            rng = np.random.default_rng(uncertainty_seed)
            local_residual = rng.normal(0.0, target_residual_sd, size=len(existing))
            local_residual -= local_residual.mean()
            realized_sd = float(local_residual.std(ddof=1)) if len(local_residual) > 1 else 0.0
            if realized_sd > 0:
                local_residual *= target_residual_sd / realized_sd
            uncertainty_multiplier = None
    target_margin = np.clip(np.tanh(national / 2) + predicted_local_lean, -0.95, 0.95)
    desired = np.log((1 + target_margin) / (1 - target_margin)) + local_residual
    adjustment = desired - existing
    for index, group in enumerate(groups):
        if group == "D":
            draws[:, index] *= np.exp(adjustment / 2)
        elif group == "R":
            draws[:, index] *= np.exp(-adjustment / 2)
    draws /= draws.sum(axis=1, keepdims=True)
    return draws, {
        "applied": 1.0,
        "mean_logratio_adjustment": float(np.mean(adjustment)),
        "mean_target_local_lean": float(predicted_local_lean),
        "local_residual_sd_before": residual_sd_before,
        "local_residual_sd_target": target_residual_sd,
        "local_residual_sd_after": float(local_residual.std(ddof=1)) if len(local_residual) > 1 else 0.0,
        "uncertainty_multiplier": uncertainty_multiplier,
    }


def _metrics(errors: list[float]) -> dict[str, float | int | None]:
    if not errors:
        return {"n": 0, "rmse": None, "mae": None, "mean_error": None}
    values = np.asarray(errors, dtype=float)
    return {"n": int(len(values)), "rmse": float(np.sqrt(np.mean(values ** 2))),
            "mae": float(np.mean(np.abs(values))), "mean_error": float(np.mean(values))}


def calibrated_uncertainty(prediction_rows: list[dict[str, Any]], target: dict[str, Any],
                           *, before_year: int | None = None,
                           from_year: int | None = None) -> dict[str, Any]:
    """Use expanding-cycle residual RMS, with pooled subgroup floors when supported."""
    rows = [row for row in prediction_rows
            if row.get("error_logratio") is not None
            and (before_year is None or row["year"] < before_year)
            and (from_year is None or row["year"] >= from_year)]
    errors = [float(row["error_logratio"]) for row in rows]
    base_sd = float(np.sqrt(np.mean(np.square(errors)))) if errors else 0.0
    selected_sd = base_sd
    components = [{"source": "all_eligible_oof_rows", "n": len(errors), "sd": base_sd}]
    for feature in ("cross_party_incumbent", "signals_disagree"):
        if not target.get(feature):
            continue
        group_errors = [float(row["error_logratio"]) for row in rows if row.get(feature)]
        if len(group_errors) < UNCERTAINTY_GROUP_MIN_N:
            components.append({"source": feature, "n": len(group_errors),
                              "sd": None, "used": False,
                              "minimum_rows": UNCERTAINTY_GROUP_MIN_N})
            continue
        group_sd = float(np.sqrt(np.mean(np.square(group_errors))))
        selected_sd = max(selected_sd, group_sd)
        components.append({"source": feature, "n": len(group_errors),
                           "sd": group_sd, "used": group_sd >= base_sd,
                           "minimum_rows": UNCERTAINTY_GROUP_MIN_N})
    return {
        "logratio_residual_sd": selected_sd,
        "pooled_logratio_residual_sd": base_sd,
        "n": len(errors),
        "components": components,
        "before_year": before_year,
        "from_year": from_year,
    }


def evaluate(rows: list[dict[str, Any]], minimum_training_rows: int = 60) -> dict[str, Any]:
    """Expanding-cycle forecast; later cycles are reported separately from tuning."""
    cycles = sorted({row["year"] for row in rows})
    predictions: dict[str, list[dict[str, Any]]] = {}
    scores: dict[str, dict[str, Any]] = {}
    for specification in FEATURES:
        for alpha in RIDGE_GRID:
            key = f"{specification}|ridge={alpha:g}"
            cells = []
            for year in cycles:
                training = [row for row in rows if row["year"] < year]
                testing = [row for row in rows if row["year"] == year]
                if len(training) < minimum_training_rows or not testing:
                    continue
                model = _fit(training, specification, alpha)
                values = model.predict(_matrix(testing, specification))
                cells.extend({"year": year, "state": row["state"],
                              "predicted_lean": float(value),
                              "actual_lean": row["target_lean"],
                              "predicted_margin": float(np.clip(value + row["target_house_margin"], -0.95, 0.95)),
                              "actual_margin": row["target_margin"],
                              "error_logratio": float(
                                  2 * (np.arctanh(np.clip(row["target_margin"], -0.95, 0.95))
                                       - np.arctanh(np.clip(value + row["target_house_margin"], -0.95, 0.95)))
                              ),
                              "incumbent_running": row["incumbent_running"],
                              "cross_party_incumbent": row["cross_party_incumbent"],
                              "signals_disagree": row["signals_disagree"],
                              "strongly_partisan": row["strongly_partisan"],
                              "error": float(value - row["target_lean"])}
                             for row, value in zip(testing, values))
            tuning = [cell["error"] for cell in cells if cell["year"] <= 2018]
            later = [cell["error"] for cell in cells if cell["year"] >= 2020]
            scores[key] = {"specification": specification, "ridge_alpha": alpha,
                           "tuning": _metrics(tuning), "later_cycles": _metrics(later)}
            scores[key]["subgroups"] = {}
            for label, predicate in (
                ("incumbent_running", lambda row: row["incumbent_running"]),
                ("open_seat", lambda row: not row["incumbent_running"]),
                ("cross_party_incumbent", lambda row: row["cross_party_incumbent"]),
                ("local_signals_disagree", lambda row: row["signals_disagree"]),
                ("strongly_partisan_presidential_lean", lambda row: row["strongly_partisan"]),
            ):
                subset = [cell for cell in cells if predicate(cell)]
                scores[key]["subgroups"][label] = {
                    "tuning": _metrics([cell["error"] for cell in subset if cell["year"] <= 2018]),
                    "later_cycles": _metrics([cell["error"] for cell in subset if cell["year"] >= 2020]),
                }
            predictions[key] = cells
    eligible = [(key, value) for key, value in scores.items()
                if value["tuning"]["rmse"] is not None]
    if not eligible:
        raise ValueError("Insufficient governor history for expanding-cycle evaluation")
    selected_key, selected_score = min(
        eligible, key=lambda pair: (pair[1]["tuning"]["rmse"],
                                    len(FEATURES[pair[1]["specification"]]),
                                    pair[1]["ridge_alpha"]),
    )
    selected_rows = predictions[selected_key]
    subgroup_scores = {}
    for label, predicate in (
        ("incumbent_running", lambda row: row["incumbent_running"]),
        ("open_seat", lambda row: not row["incumbent_running"]),
        ("cross_party_incumbent", lambda row: row["cross_party_incumbent"]),
        ("local_signals_disagree", lambda row: row["signals_disagree"]),
        ("strongly_partisan_presidential_lean", lambda row: row["strongly_partisan"]),
    ):
        subset = [row for row in selected_rows if predicate(row)]
        subgroup_scores[label] = {
            "tuning": _metrics([row["error"] for row in subset if row["year"] <= 2018]),
            "later_cycles": _metrics([row["error"] for row in subset if row["year"] >= 2020]),
        }
    uncertainty_calibration = calibrated_uncertainty(selected_rows, {}, from_year=2020)
    uncertainty_calibration.update({
        "source": "expanding-cycle out-of-fold residuals from 2020-2024; terminal results proxy held-today outcomes",
        "minimum_subgroup_rows": UNCERTAINTY_GROUP_MIN_N,
        "mean_logratio_error": float(np.mean([
            row["error_logratio"] for row in selected_rows if row["year"] >= 2020
        ])) if any(row["year"] >= 2020 for row in selected_rows) else None,
        "by_cycle": {},
        "by_subgroup": {},
    })
    for year in sorted({row["year"] for row in selected_rows if row["year"] >= 2020}):
        errors = [row["error_logratio"] for row in selected_rows if row["year"] == year]
        uncertainty_calibration["by_cycle"][str(year)] = {
            "n": len(errors),
            "logratio_residual_sd": float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
        }
    for feature in ("cross_party_incumbent", "signals_disagree"):
        errors = [row["error_logratio"] for row in selected_rows
                  if row["year"] >= 2020 and row.get(feature)]
        uncertainty_calibration["by_subgroup"][feature] = {
            "n": len(errors),
            "logratio_residual_sd": float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
        }
    return {
        "minimum_training_rows": minimum_training_rows,
        "tuning_through_cycle": 2018,
        "later_check_from_cycle": 2020,
        "selected_key": selected_key,
        "selected": selected_score,
        "subgroup_scores": subgroup_scores,
        "uncertainty_calibration": uncertainty_calibration,
        "scores": scores,
        "predictions": predictions,
        "selected_prediction_rows": selected_rows,
    }


def current_inputs(current: list[dict[str, Any]], historical: list[Any],
                   house: dict[int, float] | None = None,
                   presidential: dict[int, dict[str, float]] | None = None) -> dict[str, dict[str, Any]]:
    house = house if house is not None else parse_house()
    presidential = presidential if presidential is not None else load_presidential()
    by_state = fundamentals._history_index(historical)
    races = {race.source_race_id: race for race in historical}
    out = {}
    for item in current:
        race = item["race"]
        if race["office"] != "governor":
            continue
        fundamental = item["fundamental"]
        prior_cycle = int(fundamental["baseline_cycle"])
        source_race = races.get(str(fundamental["baseline_source_race_id"]))
        if source_race is None:
            continue
        prior_margin = two_party_margin([fundamental["dem_share"], fundamental["rep_share"]])
        pres = prior_presidential_lean(presidential, 2026, race["state"])
        if prior_margin is None or pres is None or prior_cycle not in house:
            continue
        winner = fundamentals._winner(source_race)
        if winner is None:
            continue
        prior_key = stage3.first_last_key(winner.name), winner.group
        candidates = item["candidates"]
        candidate_rows = [(candidate["name"], stage3.party_group(candidate["party"]))
                          for candidate in candidates]
        if not {"D", "R"} <= {group for _, group in candidate_rows}:
            continue
        _, experience, running = fundamentals._candidate_features(
            candidate_rows, prior_key,
            fundamentals._past_winners(by_state[race["state"]], 2026),
        )
        open_seat = (0.0 if running or winner.group not in {"D", "R"}
                     else (1.0 if winner.group == "D" else -1.0))
        incumbent = (1.0 if winner.group == "D" else -1.0) if running and winner.group in {"D", "R"} else 0.0
        presidential_lean = pres[1]
        out[race["race_id"]] = {
            "year": 2026, "state": race["state"], "prior_race_id": source_race.source_race_id,
            "prior_cycle": prior_cycle, "prior_margin": prior_margin,
            "prior_governor_lean": prior_margin - house[prior_cycle],
            "presidential_lean": presidential_lean, "presidential_year": pres[0],
            "open_seat_signed": open_seat,
            "incumbent_signed": incumbent,
            "incumbent_running": bool(running),
            "cross_party_incumbent": bool(
                incumbent and presidential_lean and np.sign(incumbent) != np.sign(presidential_lean)
            ),
            "signals_disagree": bool((prior_margin - house[prior_cycle]) * presidential_lean < 0),
            "strongly_partisan": bool(abs(presidential_lean) >= 0.15),
            "other_prior_elected_winner_signed": experience,
        }
    return out


def predict_current(current: list[dict[str, Any]], historical: list[Any],
                    transitions: list[Any],
                    database_path: Path | None = None
                    ) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    house = parse_house()
    presidential = load_presidential()
    exclusions: list[dict[str, Any]] = []
    rows = training_rows(transitions, historical, house, presidential, exclusions)
    evaluation = evaluate(rows)
    specification = evaluation["selected"]["specification"]
    alpha = evaluation["selected"]["ridge_alpha"]
    model = _fit(rows, specification, alpha)
    inputs = current_inputs(current, historical, house, presidential)
    predictions = {}
    for race_id, values in inputs.items():
        predicted = float(model.predict(_matrix([values], specification))[0])
        uncertainty = calibrated_uncertainty(
            evaluation["selected_prediction_rows"], values, from_year=2020,
        )
        predictions[race_id] = {
            "predicted_lean": predicted,
            "inputs": values,
            "uncertainty_logratio_sd": uncertainty["logratio_residual_sd"],
            "uncertainty_calibration": uncertainty,
        }
    database_path = database_path or (ROOT / "data/processed/stage2.sqlite")
    report = {
        "training_rows": len(rows),
        "excluded_missing_major_party_rows": len(exclusions),
        "excluded_missing_major_party_examples": exclusions[:20],
        "training_cycles": sorted({row["year"] for row in rows}),
        "selected_specification": specification,
        "selected_ridge_alpha": alpha,
        "coefficients": {"intercept": float(model.intercept_),
                         "features": dict(zip(FEATURES[specification],
                                              [float(value) for value in model.coef_]))},
        "expanding_cycle_evaluation": evaluation,
        "subgroup_scores": evaluation["subgroup_scores"],
        "uncertainty_calibration": evaluation["uncertainty_calibration"],
        "source_hashes": {
            "presidential_results": sha256(ROOT / "data/reference/local_lean/presidential_results.csv"),
            "house_votes": sha256(ROOT / "data/reference/national_environment/house_votes.csv"),
            "stage2_database": sha256(database_path),
        },
        "current_predictions": predictions,
    }
    return predictions, report
