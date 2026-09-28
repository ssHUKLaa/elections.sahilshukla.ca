"""Test a previous-incumbent-district prior on documented House moves.

This is a paired diagnostic, not a production model change. It does not know
how voters were reallocated across changed geographic boundaries.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage4_poll_model as m
from pipeline.load_stage6_wayback_polls import load as load_wayback_polls
from pipeline.run_stage6_calibration import district_continuity, run_cell


def main() -> None:
    with sqlite3.connect(ROOT / "data/processed/stage2.sqlite") as connection:
        connection.row_factory = sqlite3.Row
        races = m.stage3.load_historical_races(connection)
        calibration_questions = m.load_historical_questions(connection)
    polls, _ = load_wayback_polls(races)
    transitions = m.stage3.build_transitions(races, use_candidate_move_prior=False)
    continuity = district_continuity(races, transitions)
    prior_winners = defaultdict(list)
    for race in races:
        if race.office != "house":
            continue
        winner = max(race.candidates, key=lambda candidate: candidate.votes)
        key = (race.cycle, race.state, m.stage3.first_last_key(winner.name))
        prior_winners[key].append(race)
    def rekey(transition):
        if transition.office != "house":
            return transition, None
        matches = {
            prior.source_race_id: prior
            for candidate in transition.target.candidates
            for prior in prior_winners[(transition.prior_cycle, transition.state,
                                        m.stage3.first_last_key(candidate.name))]
            if prior.district != transition.target.district
        }
        if len(matches) != 1:
            return transition, None
        previous = next(iter(matches.values()))
        return replace(transition, prior=previous,
                       prior_alr=m.stage3.alr(m.stage3.group_shares(previous))), previous
    output = []
    for cycle in (2022, 2024):
        training = [t for t in transitions if t.target_cycle < cycle]
        models = m.stage3.fit_office_models(training)
        allocation = m.stage3.fit_candidate_allocation(races, max_cycle=cycle-1)
        covariances = {office: m.stage3.residual_covariance(
            [t for t in training if t.office == office], models[office]
        ) for office in m.OFFICES}
        bias = m.fit_bias_model(calibration_questions,
                                {r.source_race_id: r for r in races},
                                training_cycle=2018, senate_training_through=cycle-2)
        bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
        original, replacement, examples = [], [], []
        for transition in transitions:
            if transition.target_cycle != cycle or transition.office != "house":
                continue
            if continuity[transition.target.source_race_id] != "documented_candidate_move":
                continue
            revised, previous = rekey(transition)
            if previous is None:
                continue
            original.append(transition)
            replacement.append(revised)
            examples.append({"target_race_id": transition.target.source_race_id,
                             "state": transition.state, "target_district": transition.target.district,
                             "same_number_prior_race": transition.prior.source_race_id,
                             "moved_winner_prior_race": previous.source_race_id,
                             "moved_winner_prior_district": previous.district})
        baseline = run_cell(cycle, 7, original, polls, models, allocation, covariances,
                            bias, 1500, continuity)
        moved = run_cell(cycle, 7, replacement, polls, models, allocation, covariances,
                         bias, 1500, continuity)
        output.append({"cycle": cycle, "paired_races": len(original),
                       "same_number": baseline["strata"]["all"]["methods"]["combined"],
                       "moved_winner_previous_district": moved["strata"]["all"]["methods"]["combined"],
                       "examples": examples})
        print(cycle, len(original), output[-1]["same_number"],
              output[-1]["moved_winner_previous_district"], flush=True)
    report = {"design": "Paired seven-day test only where a target House candidate won a different district in the prior cycle. Candidate identity is matched by canonical name within state; ambiguity is excluded. Polls and random seed are held fixed. This does not replace a geographic crosswalk.",
              "cycles": output}
    # Select the identity-continuity rule from 2022, then apply it to the
    # untouched 2024 cycle including both training and held-out transitions.
    training = [t for t in transitions if t.target_cycle < 2024]
    holdout = [t for t in transitions if t.target_cycle == 2024]
    corrected_training = [rekey(t)[0] for t in training]
    corrected_holdout = [rekey(t)[0] for t in holdout]
    allocation = m.stage3.fit_candidate_allocation(races, max_cycle=2022)
    bias = m.fit_bias_model(calibration_questions,
                            {r.source_race_id: r for r in races},
                            training_cycle=2018, senate_training_through=2022)
    bias.half_life_days = m.CURRENT_POLL_HALF_LIFE_DAYS
    full = {}
    for label, fitted_training, scored_holdout in (
        ("same_number", training, holdout),
        ("candidate_continuity", corrected_training, corrected_holdout),
    ):
        models = m.stage3.fit_office_models(fitted_training)
        covariances = {office: m.stage3.residual_covariance(
            [t for t in fitted_training if t.office == office], models[office]
        ) for office in m.OFFICES}
        cell = run_cell(2024, 7, scored_holdout, polls, models, allocation,
                        covariances, bias, 1500, continuity)
        full[label] = {name: cell["strata"][name]["methods"]["combined"]
                       for name in ("all", "office:house",
                                    "district_continuity:documented_candidate_move",
                                    "district_continuity:same_district_candidate")}
    report["untouched_2024_full_cycle"] = {
        "training_rekeyed": sum(rekey(t)[1] is not None for t in training),
        "holdout_rekeyed": sum(rekey(t)[1] is not None for t in holdout),
        "methods": full,
    }
    path = ROOT / "artifacts/calibration/stage6_moved_prior_sensitivity.json"
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("2024 full-cycle", json.dumps(report["untouched_2024_full_cycle"]))


if __name__ == "__main__":
    main()
