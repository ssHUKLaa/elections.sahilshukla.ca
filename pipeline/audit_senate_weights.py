"""Print a compact Senate forecast decomposition across Stages 3 through 5."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modeling import stage3_results_baseline as stage3
from modeling import stage4_poll_model as stage4


def load(stage: str) -> dict:
    return json.loads(
        (ROOT / "artifacts" / stage / "forecast_2026.json").read_text(
            encoding="utf-8"
        )
    )


def party_probability(race: dict, field: str, party: str) -> float:
    return sum(
        float(candidate.get(field) or 0.0)
        for candidate in race["candidates"]
        if candidate["party_group"] == party
    )


def stage4_poll_count(race: dict) -> int:
    return int(race.get("poll_diagnostics", {}).get("poll_count", 0))


def main() -> None:
    forecasts = {stage: load(stage) for stage in ("stage3", "stage4", "stage5")}
    races = {
        stage: {
            race["race_id"]: race
            for race in forecast["races"]
            if race["office"] == "senate"
        }
        for stage, forecast in forecasts.items()
    }

    print("state  polls  stage3_D  stage4_D  stage5_D  s4-s3  s5-s4")
    rows = []
    for race_id, race3 in races["stage3"].items():
        race4 = races["stage4"][race_id]
        race5 = races["stage5"][race_id]
        p3 = party_probability(race3, "first_stage_leader_probability", "D")
        p4 = party_probability(race4, "first_stage_leader_probability", "D")
        p5 = party_probability(race5, "eventual_win_probability", "D")
        rows.append(
            (
                race3["state"],
                stage4_poll_count(race4),
                p3,
                p4,
                p5,
                p4 - p3,
                p5 - p4,
            )
        )
    for row in sorted(rows, key=lambda item: item[4]):
        print(
            f"{row[0]:>5} {row[1]:>6} {row[2]:>9.1%} {row[3]:>9.1%} "
            f"{row[4]:>9.1%} {row[5]:>7.1%} {row[6]:>7.1%}"
        )

    print("\nExpected Democratic winners among the 35 elections:")
    for stage, field in (
        ("stage3", "first_stage_leader_probability"),
        ("stage4", "first_stage_leader_probability"),
        ("stage5", "eventual_win_probability"),
    ):
        expected = sum(
            party_probability(race, field, "D") for race in races[stage].values()
        )
        print(f"  {stage}: {expected:.3f}")

    print("\nP(D wins at least 17 of the 35 elections):")
    for stage in ("stage3", "stage4"):
        distribution = forecasts[stage]["joint_summaries"]["senate"][
            "marginal_distributions"
        ]["D"]
        probability = sum(
            float(probability)
            for seats, probability in distribution.items()
            if int(seats) >= 17
        )
        print(f"  {stage}: {probability:.1%}")

    scenarios = forecasts["stage5"]["joint_summaries"]["senate"][
        "full_chamber"
    ]["caucus_scenarios"]
    print("\nStage 5 control scenarios:")
    for scenario, summary in scenarios.items():
        print(
            f"  {scenario}: D {summary['D_control_probability']:.1%}, "
            f"R {summary['R_control_probability']:.1%}, "
            f"unresolved {summary['unresolved_probability']:.1%}"
        )

    print("\nPoll-only diagnostic for the most competitive Senate races:")
    connection = sqlite3.connect(ROOT / "data" / "processed" / "stage2.sqlite")
    connection.row_factory = sqlite3.Row
    try:
        historical_races = stage3.load_historical_races(connection)
        historical_by_id = {race.source_race_id: race for race in historical_races}
        historical_questions = stage4.load_historical_questions(connection)
        bias_model = stage4.fit_bias_model(historical_questions, historical_by_id)
        parameters = json.loads(
            (ROOT / "artifacts" / "stage4" / "model_parameters.json").read_text(
                encoding="utf-8"
            )
        )
        bias_model.half_life_days = float(
            parameters["current_poll_recency"]["half_life_days"]
        )
        current_questions = stage4.load_current_questions(
            connection, ROOT / "data" / "processed" / "stage1.sqlite"
        )
    finally:
        connection.close()
    by_race: dict[str, list] = {}
    for question in current_questions:
        by_race.setdefault(question.race_key, []).append(question)
    cutoff = stage4.datetime.fromisoformat("2026-09-21T20:45:24")
    rng = np.random.default_rng(20260922)
    for state in ("AK", "IA", "ME", "MI", "OH", "TX"):
        race = next(race for race in races["stage4"].values() if race["state"] == state)
        keys = [candidate["ballot_entry_id"] for candidate in race["candidates"]]
        groups = [candidate["party_group"] for candidate in race["candidates"]]
        rows, values, variances, _ = stage4.poll_contrasts(
            by_race.get(race["race_id"], []), keys, groups, bias_model, cutoff
        )
        poll_draws = stage4.flat_poll_draws(
            len(keys), rows, values, variances, 50_000, rng
        )
        d_share = poll_draws[:, [group == "D" for group in groups]].sum(axis=1)
        r_share = poll_draws[:, [group == "R" for group in groups]].sum(axis=1)
        print(
            f"  {state}: mean D-R margin {(d_share-r_share).mean():+.1%}; "
            f"P(D share > R share) {np.mean(d_share > r_share):.1%}"
        )
        contrasts = []
        for question in by_race.get(race["race_id"], []):
            observed = {
                option.party_group: option.pct
                for option in question.options
                if option.candidate_key in keys
                and option.party_group in {"D", "R"}
                and option.pct > 0
            }
            if not {"D", "R"} <= observed.keys():
                continue
            age = max(0, (cutoff-question.end_date).days)
            weight = np.exp(-np.log(2)*age/bias_model.half_life_days) * np.sqrt(
                max(question.sample_size, 100.0)/600.0
            )
            raw_logratio = np.log(observed["D"]/observed["R"])
            correction = stage4.poll_pair_bias(bias_model, question, "D", "R")
            contrasts.append((raw_logratio, raw_logratio-correction, weight))
        if contrasts:
            raw_logratio = np.average([item[0] for item in contrasts], weights=[item[2] for item in contrasts])
            corrected_logratio = np.average([item[1] for item in contrasts], weights=[item[2] for item in contrasts])
            print(
                f"       D/R named-poll margin: raw {100*np.tanh(raw_logratio/2):+.1f}pt; "
                f"bias-adjusted {100*np.tanh(corrected_logratio/2):+.1f}pt"
            )
        recent = sorted(
            by_race.get(race["race_id"], []), key=lambda question: question.end_date,
            reverse=True,
        )[:5]
        for question in recent:
            d_value = sum(
                option.pct for option in question.options if option.party_group == "D"
            )
            r_value = sum(
                option.pct for option in question.options if option.party_group == "R"
            )
            print(
                f"       {question.end_date:%Y-%m-%d} {question.pollster[:28]:<28} "
                f"{question.population:<3} D-R {d_value-r_value:+.1f}"
            )
        for half_life in (14.0, 30.0, 60.0, 120.0):
            margins = []
            weights = []
            for question in by_race.get(race["race_id"], []):
                d_value = sum(
                    option.pct for option in question.options if option.party_group == "D"
                )
                r_value = sum(
                    option.pct for option in question.options if option.party_group == "R"
                )
                if d_value <= 0 or r_value <= 0:
                    continue
                age = max(0, (cutoff-question.end_date).days)
                weight = np.exp(-np.log(2)*age/half_life) * np.sqrt(
                    max(question.sample_size, 100.0)/600.0
                )
                margins.append(d_value-r_value)
                weights.append(weight)
            print(
                f"       raw {half_life:>3.0f}d half-life: "
                f"D-R {np.average(margins, weights=weights):+.1f}"
            )


if __name__ == "__main__":
    main()
