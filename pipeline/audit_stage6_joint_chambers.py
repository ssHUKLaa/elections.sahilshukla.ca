"""Compare live joint seat draws with independent-race and chamber baselines."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
FORECAST = ROOT / "artifacts/nowcast/forecast_2026.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_joint_chamber_audit.json"


def moments(pmf: dict[str, float]) -> tuple[float, float]:
    mean = sum(int(k) * v for k, v in pmf.items())
    variance = sum((int(k) - mean) ** 2 * v for k, v in pmf.items())
    return mean, variance


def independent_binary(probs: list[float]) -> np.ndarray:
    pmf = np.array([1.0])
    for p in probs:
        pmf = np.convolve(pmf, [1 - p, p])
    return pmf


def independent_senate(races: list[dict]) -> np.ndarray:
    pmf = np.zeros((36, 36))
    pmf[0, 0] = 1.0
    for race in races:
        p = {group: sum(c["eventual_win_probability"] for c in race["candidates"]
                        if c["party_group"] == group) for group in ("D", "R", "O")}
        next_pmf = pmf * p["O"]
        next_pmf[1:, :] += pmf[:-1, :] * p["D"]
        next_pmf[:, 1:] += pmf[:, :-1] * p["R"]
        pmf = next_pmf
    return pmf


def main() -> None:
    forecast = json.loads(FORECAST.read_text(encoding="utf-8"))
    joint = forecast["joint_summaries"]
    house_races = [r for r in forecast["races"] if r["office"] == "house"]
    senate_races = [r for r in forecast["races"] if r["office"] == "senate"]
    house_probs = [sum(c["eventual_win_probability"] for c in r["candidates"]
                       if c["party_group"] == "D") for r in house_races]
    independent_house = independent_binary(house_probs)
    independent_senate_pmf = independent_senate(senate_races)
    house_mean, house_var = moments(joint["house"]["marginal_distributions"]["D"])
    senate_mean, senate_var = moments(joint["senate"]["marginal_distributions"]["D"])
    independent_house_var = sum(p * (1 - p) for p in house_probs)
    independent_senate_probs = [sum(c["eventual_win_probability"] for c in r["candidates"]
                                    if c["party_group"] == "D") for r in senate_races]
    independent_senate_var = sum(p * (1 - p) for p in independent_senate_probs)
    house_control = joint["house"]["control"]["D_control_probability"]
    cross = joint["cross_chamber"]
    scenarios = {}
    for name, to_d in (("other_winners_unaligned", 0), ("all_other_winners_caucus_D", 1),
                       ("all_other_winners_caucus_R", 0)):
        independent_control = sum(
            float(prob) for d, r, prob in (
                (d, r, independent_senate_pmf[d, r]) for d in range(36) for r in range(36)
            ) if 34 + d + to_d * (35 - d - r) >= 51
        )
        model_control = joint["senate"]["full_chamber"]["caucus_scenarios"][name]["D_control_probability"]
        both = cross["house_D_control_senate_D_control_by_caucus_scenario"][name]
        scenarios[name] = {
            "model_senate_D_control": model_control,
            "independent_race_senate_D_control": independent_control,
            "model_both_chambers_D_control": both,
            "independent_chamber_both_D_control_given_model_marginals": house_control * model_control,
            "conditional_senate_D_control_given_house_D_control": both / house_control,
        }
    report = {
        "forecast_sha256": hashlib.sha256(FORECAST.read_bytes()).hexdigest(),
        "model_version": forecast["metadata"]["model_version"],
        "interpretation": "Independent-race probabilities hold each marginal win chance fixed and remove shared draw dependence. This is a structural sensitivity, not a historically calibrated alternative.",
        "house_D_seats": {
            "model_mean": house_mean, "model_sd": math.sqrt(house_var),
            "independent_race_sd": math.sqrt(independent_house_var),
            "variance_ratio_model_to_independent": house_var / independent_house_var,
            "model_D_control": house_control,
            "independent_race_D_control": float(independent_house[218:].sum()),
        },
        "senate_D_elected_seats": {
            "model_mean": senate_mean, "model_sd": math.sqrt(senate_var),
            "independent_race_sd": math.sqrt(independent_senate_var),
            "variance_ratio_model_to_independent": senate_var / independent_senate_var,
        },
        "cross_chamber_D_seat_correlation": cross["house_D_senate_D_elected_seat_correlation"],
        "senate_caucus_scenarios": scenarios,
    }
    assert abs(independent_house.sum() - 1) < 1e-10
    assert abs(independent_senate_pmf.sum() - 1) < 1e-10
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
