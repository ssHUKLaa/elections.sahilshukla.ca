"""Test 2020-population weighted district priors on historical House cutoffs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m
from pipeline.load_stage6_wayback_polls import load as load_wayback_polls
from pipeline.run_stage6_calibration import district_continuity, run_cell
from pipeline.test_stage6_house_crosswalk import score, state_codes

DB = ROOT / "data/processed/stage2.sqlite"
CROSSWALK = ROOT / "data/reference/stage6_house_population_crosswalk.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_house_population_crosswalk_test.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB)
    parser.add_argument("--draws", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
        calibration_questions = m.load_historical_questions(connection)
    questions, _ = load_wayback_polls(races)
    transitions = m.stage3.build_transitions(races, use_population_crosswalk=False)
    continuity = district_continuity(races, transitions)
    codes = state_codes()
    crosswalk = json.loads(CROSSWALK.read_text(encoding="utf-8"))
    walks = {(int(name.split("_to_")[1]), row["state_fips"], row["target_district"]): row
             for name, rows in crosswalk["transitions"].items() for row in rows}
    previous = {(race.cycle, race.state, race.district): race for race in races if race.office == "house"}
    changes = defaultdict(int)

    def weight_prior(transition):
        if transition.office != "house" or transition.target_cycle not in (2022, 2024):
            return transition
        if transition.prior_selection != "same_district_label":
            return transition  # Preserve documented candidate continuity.
        row = walks.get((transition.target_cycle, codes[transition.state], transition.target.district))
        if row is None:
            return transition
        components = []
        for overlap in row["overlaps"]:
            prior = previous.get((transition.prior_cycle, transition.state, overlap["prior_district"]))
            if prior is not None:
                components.append((overlap["population"], m.stage3.group_shares(prior)))
        if not components:
            return transition
        population = sum(value for value, _ in components)
        if population / row["population_2020"] < .95:
            return transition
        shares = sum(value * shares for value, shares in components) / population
        changes[transition.target_cycle] += 1
        return replace(transition, prior_alr=m.stage3.alr(shares),
                       prior_selection="population_weighted_overlap")

    weighted_transitions = [weight_prior(transition) for transition in transitions]

    def evaluate(cycle, weighted):
        selected = weighted_transitions if weighted else transitions
        training = [transition for transition in selected if transition.target_cycle < cycle]
        holdout = [transition for transition in selected if transition.target_cycle == cycle and transition.office == "house"]
        models = m.stage3.fit_office_models(training)
        allocation = m.stage3.fit_candidate_allocation(races, max_cycle=cycle-1)
        covariances = {office: m.stage3.residual_covariance(
            [transition for transition in training if transition.office == office], models[office]
        ) for office in m.OFFICES}
        bias = m.fit_bias_model(calibration_questions, {race.source_race_id: race for race in races},
                                training_cycle=2018, senate_training_through=cycle-2)
        bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
        cell = run_cell(cycle, 7, holdout, questions, models, allocation,
                        covariances, bias, args.draws, continuity)
        return {"scores": score(cell), "weighted_holdout_races": sum(
            transition.prior_selection == "population_weighted_overlap" for transition in holdout)}

    results = {str(cycle): {name: evaluate(cycle, name == "population_weighted")
                            for name in ("baseline", "population_weighted")}
               for cycle in (2022, 2024)}
    baseline_2022 = results["2022"]["baseline"]["scores"]["all"]["log_score"]
    weighted_2022 = results["2022"]["population_weighted"]["scores"]["all"]["log_score"]
    baseline_2024 = results["2024"]["baseline"]["scores"]["all"]["log_score"]
    weighted_2024 = results["2024"]["population_weighted"]["scores"]["all"]["log_score"]
    report = {
        "design": "Predefined population-weighted old-district group-share prior; candidate continuity takes precedence. Select on 2022 seven-day terminal winner log score, inspect 2024 for noninferiority. 2024 was previously inspected for area-overlap variants and is not a pristine final holdout.",
        "database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "crosswalk_sha256": hashlib.sha256(CROSSWALK.read_bytes()).hexdigest(),
        "draws_per_cell": args.draws,
        "weighted_transition_counts": dict(changes),
        "results": results,
        "selection_2022_improves": weighted_2022 < baseline_2022,
        "diagnostic_2024_noninferior": weighted_2024 <= baseline_2024 + 0.01,
        "promotion_passed": weighted_2022 < baseline_2022 and weighted_2024 <= baseline_2024 + 0.01,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"2022": [baseline_2022, weighted_2022],
                      "2024": [baseline_2024, weighted_2024],
                      "promotion_passed": report["promotion_passed"]}, indent=2))


if __name__ == "__main__":
    main()
