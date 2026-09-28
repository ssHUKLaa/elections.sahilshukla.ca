"""Poll-conditioned share model for minor Senate ballot candidates."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

import numpy as np

try:
    from modeling import stage4_poll_model as stage4
except ModuleNotFoundError:
    import stage4_poll_model as stage4


def fit(
    races: list[Any], questions: list[stage4.PollQuestion], max_cycle: int,
    screen_fn: Callable[[dict[str, Any], list[Any], dict[str, float] | None], dict[str, Any]],
    *, lead_days: int = 30,
) -> dict[str, Any]:
    """Fit y = alpha + beta*x + empirical residual on earlier cycles.

    x is mean candidate poll share across distinct eligible polls, counting
    absence from a poll as zero. y is certified final vote share. The final
    result is an imperfect proxy for support at the cutoff; this is a small
    candidate-allocation prior, not a partisan election-day correction.
    """
    by_race: dict[str, list[stage4.PollQuestion]] = defaultdict(list)
    for question in questions:
        if question.office == "senate" and stage4.eligible_at_cutoff(question, lead_days):
            by_race[question.race_key].append(question)
    observations = []
    cycles = set()
    for race in races:
        if (race.office != "senate" or race.cycle > max_cycle
                or race.cycle not in {2020, 2022, 2024} or race.state in {"AK", "GA"}):
            continue
        item = {"race": {"office": "senate", "counting_rule": "plurality"},
                "candidates": [{"ballot_entry_id": c.candidate_key, "party": c.party}
                               for c in race.candidates]}
        screen = screen_fn(item, by_race[race.source_race_id], None)
        if not screen["applied"]:
            continue
        total = sum(c.votes for c in race.candidates)
        if total <= 0:
            continue
        cycles.add(race.cycle)
        for candidate in race.candidates:
            key = candidate.candidate_key
            if key in screen["excluded_candidates"]:
                observations.append((
                    screen["poll_mean_pct"][key]/100.0,
                    candidate.votes/total,
                ))
    if len(observations) < 10:
        raise ValueError("Too few screened historical Senate candidates to fit minor-share model")
    x = np.array([row[0] for row in observations], dtype=float)
    y = np.array([row[1] for row in observations], dtype=float)
    design = np.column_stack((np.ones(len(x)), x))
    alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
    alpha, beta = max(float(alpha), 0.0), max(float(beta), 0.0)
    residuals = np.sort(y - alpha - beta*x)
    return {
        "method": "nonnegative intercept/slope least squares plus empirical residual quantiles",
        "training_cycles": sorted(cycles),
        "lead_days": lead_days,
        "n_candidate_observations": len(observations),
        "alpha": alpha,
        "beta": beta,
        "residuals": residuals.tolist(),
    }


def apply(draws: np.ndarray, screen: dict[str, Any], fitted: dict[str, Any]) -> np.ndarray:
    if not screen["applied"]:
        return draws
    result = np.array(draws, copy=True)
    residuals = np.asarray(fitted["residuals"], dtype=float)
    ranks = np.empty(draws.shape[0], dtype=float)
    for index, key in enumerate(screen["candidate_keys"]):
        if key not in screen["excluded_candidates"]:
            continue
        order = np.argsort(draws[:, index], kind="stable")
        ranks[order] = (np.arange(draws.shape[0])+0.5)/draws.shape[0]
        noise = np.quantile(residuals, ranks)
        center = fitted["alpha"] + fitted["beta"]*screen["poll_mean_pct"][key]/100.0
        result[:, index] = np.maximum(center + noise, 0.0)
    excluded_indices = [index for index, key in enumerate(screen["candidate_keys"])
                        if key in screen["excluded_candidates"]]
    retained_indices = screen["retained_indices"]
    # Keep every ballot option, giving screened candidates a small uncertain
    # share; scale the active contenders within the remaining vote mass.
    minor_total = result[:, excluded_indices].sum(axis=1)
    minor_scale = np.minimum(0.95/np.maximum(minor_total, 1e-12), 1.0)
    result[:, excluded_indices] *= minor_scale[:, None]
    available = 1.0-result[:, excluded_indices].sum(axis=1)
    major = draws[:, retained_indices]
    result[:, retained_indices] = major * (
        available/np.maximum(major.sum(axis=1), 1e-12)
    )[:, None]
    return result
