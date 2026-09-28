"""Render the Stage 3 Senate internals as a readable Markdown report."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path


def markdown(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def percent(value: float | None) -> str:
    return "—" if value is None else f"{100*value:.1f}%"


def pmf_stats(pmf: dict[str, float]) -> tuple[float, int, int, int]:
    ordered = sorted((int(key), probability) for key, probability in pmf.items())
    mean = sum(value*probability for value, probability in ordered)

    def quantile(target: float) -> int:
        cumulative = 0.0
        for value, probability in ordered:
            cumulative += probability
            if cumulative >= target:
                return value
        return ordered[-1][0]

    return mean, quantile(0.1), quantile(0.5), quantile(0.9)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", type=Path, default=Path("artifacts/stage3/model_parameters.json"))
    parser.add_argument("--forecast", type=Path, default=Path("artifacts/stage3/forecast_2026.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/stage3_senate_internals.md"))
    args = parser.parse_args()

    parameters = json.loads(args.parameters.read_text(encoding="utf-8"))
    forecast = json.loads(args.forecast.read_text(encoding="utf-8"))
    transition = parameters["parameters"]["party_group_transition"]["senate"]
    allocation = parameters["parameters"]["candidate_allocation"]["senate"]
    covariance = parameters["parameters"]["covariance"]
    backtest = parameters["backtest"]["by_office"]["senate"]
    senate_joint = forecast["joint_summaries"]["senate"]
    senate_races = sorted(
        (race for race in forecast["races"] if race["office"] == "senate"),
        key=lambda race: (race["state"], race["race_id"]),
    )

    coefficient = transition["coefficient"]
    lines = [
        "# Stage 3 Senate internals",
        "",
        f"**Artifact cutoff:** `{forecast['metadata']['information_cutoff_utc']}`  ",
        f"**Model:** `{forecast['metadata']['model_version']}`  ",
        f"**Simulation:** {forecast['metadata']['simulation_draws']:,} joint draws with seed `{forecast['metadata']['random_seed']}`  ",
        "**Status:** internal results-only baseline; not a public forecast",
        "",
        "## Read this first",
        "",
        "These probabilities expose the Stage 3 machinery before polling, ballot-rule transfers, final candidate qualification, or Senate caucus accounting. Independent and same-party fields remain sparsely identified, so this 35-seat first-stage distribution is unsuitable as a chamber forecast by itself.",
        "",
        "The Senate output covers only the 35 modeled 2026 races. It does not add the 65 seats that are not up for election and therefore does not calculate Senate control.",
        "",
        "## Fitted transition",
        "",
        "The model uses these two coordinates:",
        "",
        "```text",
        "x1 = log(D / R)",
        "x2 = log((D + R) / O)",
        "```",
        "",
        "The fitted Senate equations are:",
        "",
        "```text",
        f"x1_next = {coefficient[0][0]:.6f} + {coefficient[1][0]:.6f} * x1_previous",
        f"x2_next = {coefficient[0][1]:.6f} + {coefficient[2][1]:.6f} * x2_previous",
        "```",
        "",
        f"They use {transition['training_transitions']} Senate transitions. The fitted persistence coefficients are constrained to one; leave-one-cycle-out ridge results are retained as diagnostics. Other-party debuts use {transition['other_debut_transitions']} eligible transitions and a mean share of {percent(transition['other_debut_share_mean'])}.",
        "",
        "| Coordinate | Ridge | Cross-validated MSE |",
        "| --- | ---: | ---: |",
    ]
    coordinate_names = {"0": "log(D/R)", "1": "log((D+R)/O)"}
    for coordinate, scores in transition["ridge_cv_mse"].items():
        for ridge, mse in scores.items():
            lines.append(f"| {coordinate_names[coordinate]} | {ridge} | {mse:.6f} |")

    odds = math.exp(allocation["incumbent_log_utility"])
    lines += [
        "",
        "## Candidate allocation",
        "",
        f"Within the same party group, the fitted incumbent utility is `{allocation['incumbent_log_utility']:.6f}`, equivalent to about `{odds:.2f}` times the softmax weight before candidate noise. The residual within-group standard deviation is `{allocation['within_group_sigma']:.6f}`.",
        "",
        f"There were {allocation['multi_candidate_groups']} historical multi-candidate groups, but only **{allocation['informative_incumbent_groups']}** contained both an incumbent and a non-incumbent. The apparent incumbency effect is therefore weakly identified and should not be given a strong substantive interpretation.",
        "",
        "## Residual covariance",
        "",
        "Values below are standard deviations on the two log-odds coordinates. They are shared across the election as indicated, then added before converting back to candidate shares.",
        "",
        "| Component | SD for `log(D/R)` | SD for `log((D+R)/O)` |",
        "| --- | ---: | ---: |",
    ]
    covariance_rows = [
        ("National cycle", covariance["global"]),
        ("Senate office cycle", covariance["office"]["senate"]),
        ("State cycle", covariance["state"]),
        ("Senate race", covariance["race"]["senate"]),
    ]
    for label, matrix in covariance_rows:
        lines.append(f"| {label} | {math.sqrt(matrix[0][0]):.3f} | {math.sqrt(matrix[1][1]):.3f} |")

    lines += [
        "",
        "The covariance components preserve shared election, office, state, and race uncertainty. Stage 4 updates these draws with polling and calibrates posterior covariance on a separate historical cycle.",
        "",
        "## Senate-only 2024 holdout",
        "",
        "| Metric | Stage 3 | Previous-result baseline |",
        "| --- | ---: | ---: |",
    ]
    labels = {
        "log_score": "Winner log score",
        "brier": "Multiclass Brier",
        "share_mae": "Candidate-share MAE",
        "coverage80": "80% interval coverage",
        "coverage95": "95% interval coverage",
    }
    for key, label in labels.items():
        model_value = backtest["model"][key]
        baseline_value = backtest["simple_previous_result"][key]
        if key.startswith("coverage"):
            lines.append(f"| {label} | {percent(model_value)} | {percent(baseline_value)} |")
        else:
            lines.append(f"| {label} | {model_value:.4f} | {baseline_value:.4f} |")

    lines += [
        "",
        "The Senate subset improves winner log score and share MAE. Its 95% coverage is below nominal, which remains a limitation of this small office-level holdout even though the all-office acceptance gate passes.",
        "",
        "## Joint distribution across the 35 modeled seats",
        "",
        "These are first-stage candidate leaders grouped by ballot party. They are not projected final Senate membership.",
        "",
        "| Leader group | Mean seats | Median | 80% interval |",
        "| --- | ---: | ---: | ---: |",
    ]
    for group, label in (("D", "Democratic"), ("R", "Republican"), ("O", "Independent/other")):
        mean, low, median, high = pmf_stats(senate_joint["marginal_distributions"][group])
        lines.append(f"| {label} | {mean:.2f} | {median} | {low}–{high} |")

    lines += [
        "",
        "## Race internals",
        "",
        "`Leader` is the probability of finishing first at the modeled voting stage. `Eventual win` is populated only when Stage 3 treats the listed stage as directly decisive.",
    ]
    for race in senate_races:
        lines += [
            "",
            f"### {markdown(race['state'])} — `{markdown(race['race_id'])}`",
            "",
            f"Rule: `{markdown(race['counting_rule'])}` · Ballot status: `{markdown(race['ballot_status'])}` · Baseline: `{markdown(race['baseline_source'])}` · Uncertainty multiplier: `{race['uncertainty_multiplier']:.2f}`",
            "",
            "| Candidate | Party | Group | Mean share | 80% interval | Leader | Eventual win |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        candidates = sorted(
            race["candidates"],
            key=lambda candidate: (-candidate["first_stage_leader_probability"], candidate["name"]),
        )
        for candidate in candidates:
            share = candidate["share"]
            lines.append(
                f"| {markdown(candidate['name'])} | {markdown(candidate['party'])} | {candidate['party_group']} "
                f"| {percent(share['mean'])} | {percent(share['interval80_low'])}–{percent(share['interval80_high'])} "
                f"| {percent(candidate['first_stage_leader_probability'])} | {percent(candidate['eventual_win_probability'])} |"
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "output": str(args.output), "senate_races": len(senate_races)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
