"""Joint historical cutoff replay on House, Senate, governor races.

This preserves shared national/office/state shocks and uses only earlier-cycle
training. Unopposed seats without vote shares enter the chamber count as known
outcomes; early ballot rosters remain retrospective.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as stage3
from modeling import stage4_poll_model as stage4
from modeling import stage5_outcome_model as stage5
from modeling import national_environment as national
from modeling import fundamentals_features_2026 as features
from modeling import governor_local_lean as governor_local
from modeling import historical_pollster_quality as ratings
from modeling import senate_minor_share
from pipeline.load_stage6_wayback_polls import load as load_wayback

DATABASE = ROOT / "data/processed/stage2.sqlite"
SNAPSHOTS = ROOT / "artifacts/calibration/stage6_national_snapshots.json"
OUTPUT = ROOT / "artifacts/calibration/stage6_joint_replay.json"
MAP_SHIFTS = ROOT / "data/reference/stage6_historical_house_map_shifts.json"
UNOPPOSED_OUTCOME_ONLY = {
    2020: (("FL", "25", "R", "Mario Diaz-Balart"),),
    2022: (("FL", "05", "R", "John H. Rutherford"),
           ("LA", "04", "R", "Mike Johnson")),
    2024: (("FL", "20", "D", "Sheila Cherfilus-McCormick"),
           ("OK", "03", "R", "Frank D. Lucas")),
}


def national_center(cycle: int, lead: int, snapshots: dict, house: dict[int, float],
                    approval_rows: list[dict], hyper: dict) -> dict:
    snap = snapshots[(cycle, lead)]
    generic = snap["generic_ballot"]
    approval = snap["presidential_approval"]
    if generic["status"] != "available" or approval["status"] != "available":
        raise ValueError(f"Missing national signal {cycle} {lead}")
    train = [row for row in approval_rows if row["year"] < cycle]
    model = national.fit(train, hyper["half_life_years"], hyper["ridge_alpha"], cycle)
    party = -1 if cycle == 2020 else 1
    row = {"year": cycle, "previous_margin": house[cycle-2],
           "president_party": party, "midterm": int(cycle % 4 == 2),
           "signed_approval_net": party * approval["mean"]}
    approval_margin = float(model.predict(national.features([row]))[0])
    approval_center = stage4.margin_to_logratio(approval_margin)
    previous_generic = [snapshots[(year, 7)]["generic_ballot"]["terminal_margin_error"]
                        for year in (2018, 2020, 2022) if year < cycle]
    error_scale = math.sqrt(float(np.mean(np.square(previous_generic))))
    generic_sd = math.sqrt(generic["poll_dispersion_sd"]**2 /
                           max(generic["effective_poll_count"], 1.0)
                           + (2*error_scale)**2)
    approval_sd = 2*hyper["rolling_rmse"] / max(1-approval_margin**2, 0.01)
    center, variance = stage4.blend_national_signals(
        generic["mean"], generic_sd, approval_center, approval_sd,
        stage4.APPROVAL_BLEND_WEIGHT)
    return {"center_logratio": center, "variance": variance,
            "generic_mean_logratio": generic["mean"],
            "generic_sd_logratio": generic_sd,
            "approval_prior_margin": approval_margin,
            "generic_training_cycles": [year for year in (2018, 2020, 2022) if year < cycle],
            "generic_poll_count": generic["poll_count"],
            "approval_poll_count": approval["poll_count"]}


def synthetic_item(transition: stage3.Transition) -> dict:
    race = transition.target
    candidates = stage3.historical_candidate_dicts(race)
    for candidate in candidates:
        candidate["ballot_entry_id"] = candidate["candidate_key"]
    return {"race": {"race_id": race.source_race_id, "office": race.office,
                     "state": race.state, "district_code": race.district},
            "candidates": candidates, "prior_shares": stage3.inv_alr(transition.prior_alr),
            "fundamental": {"uncertainty_multiplier": 1.0}}


def historic_local_shift(transition: stage3.Transition, effects: dict,
                         historical: list, cutoff, governor_approvals: dict,
                         include_legacy_governor_shift: bool = False) -> dict:
    race = transition.target
    winner = features._winner(transition.prior)
    prior_key = ((stage3.first_last_key(winner.name), winner.group) if winner else None)
    past = features._past_winners([r for r in historical if r.state == race.state], race.cycle)
    _, experience, running = features._candidate_features(
        [(c.name, c.group) for c in race.candidates], prior_key, past)
    beta = effects[race.office]["coefficients"]
    open_seat = (1 if winner.group == "D" else -1) if winner and not running else 0
    candidate_shift = (float(beta[0]*open_seat + beta[1]*experience)
                       if race.office == "governor" and include_legacy_governor_shift
                       else 0.0 if race.office == "governor"
                       else float(beta[0]*open_seat + beta[1]*experience))
    approval_shift = 0.0
    approval_quarter = None
    if race.office == "governor" and winner and running and len(beta) > 2:
        eligible = [(quarter, value) for (state, year, quarter), value in governor_approvals.items()
                    if state == race.state and year == race.cycle and quarter * 3 <= cutoff.month-1]
        if eligible:
            approval_quarter, net = max(eligible)
            approval_shift = float(beta[2]*(1 if winner.group == "D" else -1)*net)
    return {"open_seat_candidate_experience": candidate_shift,
            "governor_approval": approval_shift,
            "approval_quarter": approval_quarter}


def governor_approval_history() -> dict:
    import csv
    out = {}
    path = features.APPROVAL / "sead_governor_quarterly_v1.csv"
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            state = features.STATES.get(row["state"])
            if state and row["Approval_Smoothed"] and row["Disapproval_Smoothed"]:
                out[(state, int(row["year"]), int(row["quarter"]))] = (
                    float(row["Approval_Smoothed"])-float(row["Disapproval_Smoothed"])) / 100
    return out


def counting_evidence(connection: sqlite3.Connection, cycles: tuple[int, ...]) -> dict:
    """Pin final-round winners and fit transfer rules only on earlier cycles."""
    pairs = stage5.paired_runoffs(connection)
    runoff_winners = {}
    for pair in pairs:
        rows = connection.execute(
            "SELECT source_candidate_id,candidate_name,votes FROM historical_results WHERE source_race_id=? AND votes IS NOT NULL",
            (pair["runoff_race_id"],)).fetchall()
        if rows:
            winner = max(rows, key=lambda row: row["votes"])
            runoff_winners[pair["first_race_id"]] = (winner["source_candidate_id"] or
                                                      stage3.first_last_key(winner["candidate_name"]))
    ranked_choice_winners = {}
    for race_id, in connection.execute(
        """SELECT source_race_id FROM historical_results WHERE result_round IS NOT NULL
        AND result_round NOT IN ('','1') GROUP BY source_race_id"""):
        rows = connection.execute(
            "SELECT source_candidate_id,candidate_name,votes,result_round FROM historical_results WHERE source_race_id=? AND votes IS NOT NULL",
            (race_id,)).fetchall()
        final_round = max((int(row["result_round"]) for row in rows if row["result_round"] and
                           str(row["result_round"]).isdigit()), default=1)
        finalists = [row for row in rows if row["result_round"] and
                     str(row["result_round"]).isdigit() and int(row["result_round"]) == final_round]
        if final_round > 1 and finalists:
            winner = max(finalists, key=lambda row: row["votes"])
            ranked_choice_winners[race_id] = (winner["source_candidate_id"] or
                                              stage3.first_last_key(winner["candidate_name"]))
    return {
        "runoff_winners": runoff_winners,
        "ranked_choice_winners": ranked_choice_winners,
        "runoff_models": {cycle: stage5.fit_runoff_model(
            [pair for pair in pairs if pair["cycle"] < cycle]) for cycle in cycles},
        "rcv_profiles": {cycle: stage5.rcv_transfer_evidence(connection, before_cycle=cycle)[0]
                         for cycle in cycles},
        "training_pairs": {cycle: sum(pair["cycle"] < cycle for pair in pairs) for cycle in cycles},
    }


def run_cell(cycle: int, lead: int, holdout: list, questions: list, training: list,
             history: list, calibration_questions: list, snapshots: dict,
             house: dict, approval_rows: list, hyper: dict, governor_approvals: dict,
             governor_specification: str, governor_alpha: float,
             draws: int, counting: dict, map_shifts: dict[str, dict[str, float]],
             no_governor_approval: bool = False,
             national_logratio_sd_floor: float = 0.0,
             use_governor_local_lean: bool = True,
             governor_uncertainty_predictions: list[dict] | None = None) -> dict:
    rng = np.random.default_rng(20261001 + cycle*100 + lead)
    cutoff = national.election_date(cycle) - timedelta(days=lead)
    models = stage3.fit_office_models(training)
    allocation = stage3.fit_candidate_allocation(history, max_cycle=cycle-1)
    decomposition = stage3.decompose_covariance(training, models)
    structural = stage4.structural.fit(training, models, stage3)
    effect_fit = features.fit_effects(training, models, [r for r in history if r.cycle < cycle])
    presidential = governor_local.load_presidential()
    local_training = governor_local.training_rows(training, history, house, presidential)
    governor_model = (governor_local.fit_model(local_training, governor_specification, governor_alpha)
                      if local_training else None)
    bias = stage4.fit_bias_model(calibration_questions,
                                 {r.source_race_id: r for r in history},
                                 training_cycle=2018, senate_training_through=cycle-2)
    bias.half_life_days = stage4.CURRENT_POLL_HALF_LIFE_DAYS
    quality, rating_meta = ratings.load(cycle)
    national_fit = national_center(cycle, lead, snapshots, house, approval_rows, hyper)
    if national_logratio_sd_floor > 0:
        national_fit["variance"] = max(national_fit["variance"], national_logratio_sd_floor**2)
        national_fit["forensic_sd_floor"] = national_logratio_sd_floor
    prior_global = rng.multivariate_normal(np.zeros(2), decomposition["global"], size=draws)
    prior_office = {office: rng.multivariate_normal(np.zeros(2), decomposition["office"][office], size=draws)
                    for office in stage3.OFFICES}
    prior_state = {state: rng.multivariate_normal(np.zeros(2), decomposition["state"], size=draws)
                   for state in sorted({t.state for t in holdout})}
    candidate_prior = {}
    items = {}
    for transition in holdout:
        item = synthetic_item(transition)
        race = transition.target
        office = race.office
        mean = stage3.transition_predict(models[office], transition)
        local = rng.multivariate_normal(np.zeros(2), decomposition["race"][office], size=draws)
        if office == "house":
            gap = transition.target_cycle - transition.prior_cycle
            if gap > 4:
                local[:, 0] *= math.sqrt(gap / 2.0)
            extra = stage3.historical_prior_extra_sd(transition, models[office])
            if extra > 0:
                local[:, 0] += rng.normal(0.0, extra, draws)
        ballot = stage4.structural.ballot_class({c.group for c in race.candidates},
                                                float(item["prior_shares"][2]))
        if ballot == "other_debut":
            for coordinate in (0, 1):
                local[:, coordinate] *= structural["other_debut"][str(coordinate)]["local_sd_multiplier"]
        latent = mean + (prior_global + prior_office[office] + prior_state[race.state] + local) * (
            decomposition["office_coordinate_normalization"][office])
        target_other = stage3.transition_other_share_target(models[office], transition)
        if target_other is not None:
            latent = stage3.calibrate_other_share(latent, target_other)
        if ballot == "one_major_plus_other":
            fit = structural["one_major_plus_other"]
            latent[:, 1] = (stage4.structural.one_major_log_odds(item, structural, stage3)
                            + rng.normal(0, fit["residual_sd"], draws))
        candidate_prior[race.source_race_id] = stage3.simulate_candidates(
            latent, item["candidates"], allocation[office]["incumbent_log_utility"],
            allocation[office]["within_group_sigma"], rng,
            allocation[office]["write_in_share_samples"])
        items[race.source_race_id] = item
    house_ids = [t.target.source_race_id for t in holdout if t.office == "house"]
    dem, rep = np.zeros(draws), np.zeros(draws)
    for race_id in house_ids:
        samples = candidate_prior[race_id]
        for index, candidate in enumerate(items[race_id]["candidates"]):
            group = stage3.party_group(candidate["party"])
            if group == "D": dem += samples[:, index]
            if group == "R": rep += samples[:, index]
    prior_national = np.log(np.maximum(dem, 1e-9) / np.maximum(rep, 1e-9))
    prior_mean, prior_sd = float(prior_national.mean()), float(prior_national.std(ddof=1))
    transformed = national_fit["center_logratio"] + (prior_national-prior_mean) * (
        math.sqrt(national_fit["variance"]) / max(prior_sd, 1e-6))
    shift = transformed - prior_national
    by_race = defaultdict(list)
    for question in questions:
        if stage4.eligible_at_cutoff(question, lead):
            by_race[question.race_key].append(question)
    minor_fit = senate_minor_share.fit(history, questions, cycle-2,
                                       lambda item, qs, weights: stage5.senate_contender_screen(item, qs, weights)) if cycle > 2020 else None
    seats = {office: {group: np.zeros(draws, dtype=np.int16) for group in stage3.GROUPS}
             for office in stage3.OFFICES}
    actual = {office: Counter() for office in stage3.OFFICES}
    office_races = Counter()
    poll_coverage = Counter()
    local_coverage = Counter()
    result_races = []
    for transition in holdout:
        race = transition.target
        race_id = race.source_race_id
        item = items[race_id]
        samples = candidate_prior[race_id]
        groups = [candidate.group for candidate in race.candidates]
        for index, group in enumerate(groups):
            if group == "D": samples[:, index] *= np.exp(shift/2)
            elif group == "R": samples[:, index] *= np.exp(-shift/2)
        samples /= samples.sum(axis=1, keepdims=True)
        governor_uncertainty_diagnostic = None
        local = historic_local_shift(
            transition, effect_fit, history, cutoff, governor_approvals,
            include_legacy_governor_shift=not use_governor_local_lean,
        )
        if no_governor_approval:
            local["governor_approval"] = 0.0
        if local["approval_quarter"] is not None:
            local_coverage["governor_approval"] += 1
        samples = features.shift_candidate_shares(
            samples, item["candidates"],
            local["open_seat_candidate_experience"] + local["governor_approval"]
            + map_shifts.get(str(cycle), {}).get(str(race_id), 0.0))
        fitted_governor_lean = None
        governor_row = []
        if race.office == "governor" and governor_model is not None:
            governor_row = governor_local.training_rows(
                [transition], history, house, presidential,
            )
            if governor_row and use_governor_local_lean:
                fitted_governor_lean = governor_local.predict_row(
                    governor_model, governor_row[0], governor_specification,
                )
                uncertainty = governor_local.calibrated_uncertainty(
                    governor_uncertainty_predictions or [], governor_row[0], before_year=cycle,
                )
                samples, governor_uncertainty_diagnostic = governor_local.recenter_candidate_draws(
                    samples, groups, transformed, fitted_governor_lean,
                    uncertainty["logratio_residual_sd"],
                    int.from_bytes(hashlib.sha256(
                        f"20261001:{cycle}:{lead}:{race_id}".encode("utf-8")
                    ).digest()[:8], "big"),
                )
                local_coverage["governor_local_lean"] += 1
        if race.office == "house" and str(race_id) in map_shifts.get(str(cycle), {}):
            local_coverage["house_presidential_map_shift"] += 1
        race_questions = by_race.get(race_id, [])
        if race_questions:
            keys = [candidate.candidate_key for candidate in race.candidates]
            rows, values, variances, diagnostics = stage4.poll_contrasts(
                race_questions, keys, groups, bias,
                race_questions[0].election_date - timedelta(days=lead),
                quality_weights=quality, apply_election_day_bias=False)
            if rows:
                updated = stage4.affine_update_draws(samples, rows, values, variances)
                samples = stage4.preserve_unpolled_candidate_mass(
                    samples, updated, keys, diagnostics["polled_candidate_keys"])
                poll_coverage[race.office] += 1
        if minor_fit and race.office == "senate" and race.state not in {"AK", "GA"}:
            screen = stage5.senate_contender_screen(
                {"race": {"office": "senate", "counting_rule": "plurality"},
                 "candidates": item["candidates"]}, race_questions, quality)
            samples = senate_minor_share.apply(samples, screen, minor_fit)
        if race_id in counting["runoff_winners"]:
            winners, _ = stage5.runoff_winners(
                samples, item["candidates"], counting["runoff_models"][cycle], rng)
            local_coverage["runoff_rule"] += 1
            rule = "majority_then_runoff"
        elif race_id in counting["ranked_choice_winners"]:
            winners, _ = stage5.rcv_winners(
                samples, item["candidates"], counting["rcv_profiles"][cycle], rng)
            local_coverage["ranked_choice_rule"] += 1
            rule = "ranked_choice"
        elif race.office == "governor" and race.state == "VT":
            winners, _ = stage5.vermont_winners(samples, item["candidates"])
            local_coverage["vermont_assembly_rule"] += 1
            rule = "majority_then_legislative_selection"
        else:
            winners = np.argmax(samples, axis=1)
            rule = "plurality"
        for index, group in enumerate(groups):
            seats[race.office][group] += winners == index
        final_key = (counting["runoff_winners"].get(race_id) or
                     counting["ranked_choice_winners"].get(race_id))
        true_winner = (next((candidate for candidate in race.candidates
                             if candidate.candidate_key == final_key), None) if final_key else None)
        if true_winner is None:
            if final_key:
                raise ValueError(f"Final-round winner absent from first-round roster: {cycle} {race_id} {final_key}")
            true_winner = max(race.candidates, key=lambda candidate: candidate.votes)
        actual[race.office][true_winner.group] += 1
        office_races[race.office] += 1
        governor_share = None
        if race.office == "governor" and "D" in groups and "R" in groups:
            d_votes = sum(candidate.votes or 0 for candidate in race.candidates if candidate.group == "D")
            r_votes = sum(candidate.votes or 0 for candidate in race.candidates if candidate.group == "R")
            if d_votes + r_votes > 0:
                d_draws = samples[:, [i for i, group in enumerate(groups) if group == "D"]].sum(axis=1)
                r_draws = samples[:, [i for i, group in enumerate(groups) if group == "R"]].sum(axis=1)
                margin_draws = (d_draws-r_draws)/np.maximum(d_draws+r_draws, 1e-12)
                governor_share = {
                    "actual_margin": float((d_votes-r_votes)/(d_votes+r_votes)),
                    "mean_margin": float(np.mean(margin_draws)),
                    "interval80": [float(value) for value in np.quantile(margin_draws, [0.1, 0.9])],
                    "interval95": [float(value) for value in np.quantile(margin_draws, [0.025, 0.975])],
                    "cross_party_incumbent": bool(
                        governor_row and governor_row[0]["cross_party_incumbent"]
                    ),
                }
        result_races.append({"race_id": race_id, "office": race.office, "counting_rule": rule,
                             "actual_group": true_winner.group,
                             "actual_winner": true_winner.candidate_key,
                             "winner_probability": float(np.mean(winners == next(
                                 i for i, c in enumerate(race.candidates)
                                 if c.candidate_key == true_winner.candidate_key))),
                             "governor_local_lean": fitted_governor_lean,
                             "governor_share": governor_share,
                             "governor_uncertainty": governor_uncertainty_diagnostic})
    # Certified unopposed winners have no numeric vote total in the archive.
    # Count their seats, but never invent a share for candidate calibration.
    for state, district, group, name in UNOPPOSED_OUTCOME_ONLY.get(cycle, ()):
        seats["house"][group] += 1
        actual["house"][group] += 1
        office_races["house"] += 1
        result_races.append({"race_id": f"unopposed:{state}:{district}",
                             "office": "house", "actual_group": group,
                             "actual_winner": name, "winner_probability": 1.0,
                             "outcome_only_no_vote_total": True})
    summaries = {}
    for office in stage3.OFFICES:
        values = seats[office]["D"]
        observed = actual[office]["D"]
        summaries[office] = {"race_count": office_races[office],
                             "actual_D_wins": observed,
                             "predicted_D_wins_mean": float(np.mean(values)),
                             "predicted_D_wins_sd": float(np.std(values, ddof=1)),
                             "interval80": [int(x) for x in np.quantile(values, [0.1, 0.9])],
                             "interval95": [int(x) for x in np.quantile(values, [0.025, 0.975])],
                             "actual_percentile": float(np.mean(values <= observed)),
                             "point_probability": float(np.mean(values == observed)),
                             "poll_updated_races": poll_coverage[office]}
    return {"cycle": cycle, "lead_days": lead, "draws": draws,
            "national": national_fit, "pollster_rating_edition": rating_meta["rating_edition"],
            "local_feature_coverage": dict(local_coverage),
            "office_seats": summaries,
            "house_senate_D_wins_correlation": float(np.corrcoef(
                seats["house"]["D"], seats["senate"]["D"])[0, 1]),
            "races": result_races}


def governor_cell_metrics(cell: dict) -> dict:
    races = [race for race in cell["races"]
             if race.get("office") == "governor" and race.get("actual_group") in {"D", "R"}]
    shares = [race["governor_share"] for race in races if race.get("governor_share")]
    def coverage(rows: list[dict], level: str) -> float | None:
        interval = "interval80" if level == "80" else "interval95"
        if not rows:
            return None
        return float(np.mean([row[interval][0] <= row["actual_margin"] <= row[interval][1]
                              for row in rows]))
    def subset_metrics(rows: list[dict]) -> dict:
        if not rows:
            return {"n": 0, "coverage80": None, "coverage95": None,
                    "mean_interval80_width": None}
        return {
            "n": len(rows),
            "coverage80": coverage(rows, "80"),
            "coverage95": coverage(rows, "95"),
            "mean_interval80_width": float(np.mean([
                row["interval80"][1]-row["interval80"][0] for row in rows
            ])),
        }
    winner_losses = []
    for race in races:
        winner_losses.append(-math.log(max(float(race["winner_probability"]), 1e-12)))
    cross_party = [row for row in shares if row["cross_party_incumbent"]]
    return {
        "race_count": len(races),
        "winner_log_loss": float(np.mean(winner_losses)) if winner_losses else None,
        "margin_intervals": subset_metrics(shares),
        "cross_party_incumbent_margin_intervals": subset_metrics(cross_party),
    }


def non_governor_probabilities_equal(old: dict, new: dict) -> bool:
    old_races = {race["race_id"]: race for race in old["races"] if race["office"] != "governor"}
    new_races = {race["race_id"]: race for race in new["races"] if race["office"] != "governor"}
    return old_races.keys() == new_races.keys() and all(
        old_races[race_id]["winner_probability"] == new_races[race_id]["winner_probability"]
        for race_id in old_races
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--snapshots", type=Path, default=SNAPSHOTS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--draws", type=int, default=2000)
    parser.add_argument("--map-shifts", type=Path, default=MAP_SHIFTS)
    parser.add_argument("--no-map-shift", action="store_true")
    parser.add_argument("--no-governor-approval", action="store_true",
                        help="Paired diagnostic: zero the incumbent approval shift in replay races")
    parser.add_argument("--national-logratio-sd-floor", type=float, default=0.0,
                        help="Forensic sensitivity only: apply a later-known national SD floor")
    parser.add_argument("--paired-governor-output", type=Path,
                        default=ROOT / "artifacts/calibration/governor_local_lean_paired_replay.json",
                        help="Write same-seed old-versus-revised governor replay comparison")
    parser.add_argument("--cycles", type=int, nargs="+", default=(2020, 2022, 2024))
    parser.add_argument("--leads", type=int, nargs="+", default=(90, 30, 7))
    args = parser.parse_args()
    if args.draws < 1000:
        parser.error("At least 1000 draws required")
    if args.national_logratio_sd_floor < 0:
        parser.error("National SD floor cannot be negative")
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        history = stage3.load_historical_races(connection)
        calibration_questions = stage4.load_historical_questions(connection)
        for cycle, seats in UNOPPOSED_OUTCOME_ONLY.items():
            for state, district, group, name in seats:
                rows = connection.execute("""SELECT candidate_name,ballot_party,votes
                    FROM historical_results WHERE cycle=? AND office='house'
                    AND state=? AND district=? AND stage IN ('general','jungle primary') AND special=0""",
                    (cycle, state, district)).fetchall()
                if len(rows) != 1 or rows[0]["candidate_name"] != name or rows[0]["votes"] is not None \
                        or stage3.party_group(rows[0]["ballot_party"]) != group:
                    raise ValueError(f"Outcome-only winner changed: {cycle} {state}-{district}")
    questions, poll_meta = load_wayback(history)
    transitions = stage3.build_transitions(history)
    snapshot_data = json.loads(args.snapshots.read_text(encoding="utf-8"))
    snapshots = {(s["cycle"], s["lead_days"]): s for s in snapshot_data["snapshots"]}
    house = national.parse_house()
    approvals = national.parse_approval()
    approval_rows = national.cycle_rows(house, approvals)
    hyper = national.evaluate(approval_rows)["chosen"]
    governor_approvals = governor_approval_history()
    governor_presidential = governor_local.load_presidential()
    governor_training = governor_local.training_rows(
        transitions, history, house, governor_presidential,
    )
    governor_evaluation = governor_local.evaluate(governor_training)
    governor_specification = governor_evaluation["selected"]["specification"]
    governor_alpha = governor_evaluation["selected"]["ridge_alpha"]
    governor_oof_predictions = governor_evaluation["selected_prediction_rows"]
    map_report = json.loads(args.map_shifts.read_text(encoding="utf-8"))
    if map_report["stage2_database_sha256"] != hashlib.sha256(args.database.read_bytes()).hexdigest():
        raise ValueError("Historical House map shifts use a different Stage 2 database")
    if map_report["crosswalk_sha256"] != hashlib.sha256(
            (ROOT / "data/reference/stage6_house_population_crosswalk.json").read_bytes()).hexdigest():
        raise ValueError("Historical House map shifts use a different population crosswalk")
    map_shifts = {} if args.no_map_shift else map_report["race_shifts"]
    with sqlite3.connect(args.database) as connection:
        connection.row_factory = sqlite3.Row
        counting = counting_evidence(connection, tuple(args.cycles))
    cells = []
    paired_cells = []
    for cycle in args.cycles:
        training = [t for t in transitions if t.target_cycle < cycle]
        holdout = [t for t in transitions if t.target_cycle == cycle]
        past_errors = [row["error_logratio"] for row in governor_oof_predictions
                       if row["year"] < cycle]
        uncertainty_sd = (float(np.sqrt(np.mean(np.square(past_errors))))
                          if past_errors else 0.0)
        for lead in args.leads:
            shared_args = (
                cycle, lead, holdout, questions, training, history, calibration_questions,
                snapshots, house, approval_rows, hyper, governor_approvals,
                governor_specification, governor_alpha, args.draws, counting, map_shifts,
                args.no_governor_approval, args.national_logratio_sd_floor,
            )
            old_cell = run_cell(*shared_args, use_governor_local_lean=False)
            new_cell = run_cell(*shared_args, use_governor_local_lean=True,
                                governor_uncertainty_predictions=governor_oof_predictions)
            cells.append(new_cell)
            paired_cells.append({
                "cycle": cycle,
                "lead_days": lead,
                "governor_uncertainty_logratio_sd_from_prior_oof": uncertainty_sd,
                "non_governor_winner_probabilities_exactly_equal": non_governor_probabilities_equal(
                    old_cell, new_cell,
                ),
                "old_model": governor_cell_metrics(old_cell),
                "revised_model": governor_cell_metrics(new_cell),
            })
            print(cycle, lead, {office: new_cell["office_seats"][office]["race_count"]
                                for office in stage3.OFFICES}, flush=True)
    report = {"design": {"estimand": "winner if election occurred at each historical cutoff",
                         "validation_target": "terminal certified winners, an imperfect proxy at earlier cutoffs",
                         "shared_draws": "global, office, state and race residuals are aligned across races",
                         "source_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
                         "national_snapshot_sha256": hashlib.sha256(args.snapshots.read_bytes()).hexdigest(),
                         "historical_house_map_shifts_sha256": hashlib.sha256(args.map_shifts.read_bytes()).hexdigest(),
                         "historical_house_map_shifts_enabled": not args.no_map_shift,
                         "governor_approval_enabled": not args.no_governor_approval,
                         "governor_local_lean": {
                             "enabled": True,
                             "selected_specification": governor_specification,
                             "ridge_alpha": governor_alpha,
                             "tuning_scores": governor_evaluation["scores"],
                             "training_rows": len(governor_training),
                             "subgroup_scores": governor_evaluation["subgroup_scores"],
                             "uncertainty_calibration": governor_evaluation["uncertainty_calibration"],
                             "holdout_limitation": "Historical terminal results proxy held-today governor support.",
                         },
                         "forensic_national_logratio_sd_floor": args.national_logratio_sd_floor,
                         "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                         "stage3_code_sha256": hashlib.sha256((ROOT / "modeling/stage3_results_baseline.py").read_bytes()).hexdigest(),
                         "stage4_code_sha256": hashlib.sha256((ROOT / "modeling/stage4_poll_model.py").read_bytes()).hexdigest(),
                         "stage5_code_sha256": hashlib.sha256((ROOT / "modeling/stage5_outcome_model.py").read_bytes()).hexdigest(),
                         "governor_local_lean_code_sha256": hashlib.sha256((ROOT / "modeling/governor_local_lean.py").read_bytes()).hexdigest(),
                         "poll_source": poll_meta,
                         "counting_rule_training_pairs": counting["training_pairs"],
                         "limitations": ["Verified unopposed House winners in 2020, 2022, and 2024 are included as certain seat outcomes without invented vote shares.",
                                         "Races use final ballot candidate rosters at all cutoffs.",
                                         "Historical runoff and ranked-choice rules use only pre-cycle fitted transfers; final candidate rosters are still retrospectively applied at early cutoffs.",
                                         "Historical governor-approval quarters may contain retrospective smoothing revisions.",
                                         "Historical presidential map shifts are computed from rounded district vote percentages and population-weighted old-map overlaps, not ballot-level retabulations.",
                                         "Archived polls could contain retrospective row revisions."]},
              "cells": cells}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    paired_report = {
        "design": {
            "comparison": "Old governor fundamentals versus revised local-lean prior, rerun in-process with identical seeds and sorted state draw order.",
            "old_governor_method": "Legacy fitted open-seat/candidate-experience shift.",
            "new_governor_method": "Selected local-lean model and historical out-of-fold uncertainty floor.",
            "non_governor_check": "All non-governor race winner probabilities must match exactly within each paired cell.",
        },
        "source_database_sha256": hashlib.sha256(args.database.read_bytes()).hexdigest(),
        "source_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "cells": paired_cells,
        "all_non_governor_probabilities_equal": all(
            cell["non_governor_winner_probabilities_exactly_equal"] for cell in paired_cells
        ),
    }
    paired_summary = {}
    for model_key in ("old_model", "revised_model"):
        total_races = sum(cell[model_key]["race_count"] for cell in paired_cells)
        summary = {
            "race_cutoffs": total_races,
            "winner_log_loss": sum(
                cell[model_key]["winner_log_loss"] * cell[model_key]["race_count"]
                for cell in paired_cells
            ) / total_races if total_races else None,
        }
        for key in ("margin_intervals", "cross_party_incumbent_margin_intervals"):
            count = sum(cell[model_key][key]["n"] for cell in paired_cells)
            summary[key] = {
                "n": count,
                "coverage80": sum(
                    (cell[model_key][key]["coverage80"] or 0.0) * cell[model_key][key]["n"]
                    for cell in paired_cells
                ) / count if count else None,
                "coverage95": sum(
                    (cell[model_key][key]["coverage95"] or 0.0) * cell[model_key][key]["n"]
                    for cell in paired_cells
                ) / count if count else None,
                "mean_interval80_width": sum(
                    (cell[model_key][key]["mean_interval80_width"] or 0.0) * cell[model_key][key]["n"]
                    for cell in paired_cells
                ) / count if count else None,
            }
        paired_summary[model_key] = summary
    paired_report["summary"] = paired_summary
    args.paired_governor_output.parent.mkdir(parents=True, exist_ok=True)
    args.paired_governor_output.write_text(json.dumps(paired_report, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Wrote {args.paired_governor_output}")


if __name__ == "__main__":
    main()
