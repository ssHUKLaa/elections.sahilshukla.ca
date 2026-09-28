"""Write a concise Markdown view of the paired 2026 fundamentals ablation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=Path("artifacts/nowcast"))
    args = parser.parse_args()
    folder = args.artifact_dir
    impact = json.loads((folder/"fundamentals_impact_2026.json").read_text(encoding="utf-8"))
    forecast = json.loads((folder/"forecast_2026.json").read_text(encoding="utf-8"))
    rows = impact["summary"]
    labels = {
        "baseline":"Base model, including governor local lean",
        "district_map":"+ 2026 House district maps",
        "governor_approval":"+ governor approval",
        "open_seat_candidate_experience":"+ open seats and candidate experience",
    }
    out = [
        "# 2026 fundamentals impact",
        "",
        f"Poll cutoff: **{forecast['metadata']['information_cutoff_utc']}**. "
        f"Simulation: **{forecast['metadata']['simulation_draws']:,} paired draws**.",
        "",
            "Each row adds one input to the preceding row using the same polls and simulated draws. "
            "These are first-stage leader comparisons; ranked-choice and runoff rules are applied to the final forecast below.",
        "",
        "| Addition | House D seats, mean | House D 218+ | Senate D seats up, mean | Senate D 51+ if O caucuses D | Governor D wins, mean |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        out.append(f"| {labels[row['step']]} | {row['house_D_expected_seats']:.2f} | "
                   f"{row['house_D_218_probability_first_stage']:.1%} | "
                   f"{row['senate_D_expected_elected_seats']:.2f} | "
                   f"{row['senate_D_51_caucus_probability_all_O_to_D_first_stage']:.1%} | "
                   f"{row['governor_D_expected_wins']:.2f} |")
    out += ["", "## Incremental changes", "",
            "| Addition | House D seats | House control | Senate D seats up | Senate control scenario | Governor D wins |",
            "|---|---:|---:|---:|---:|---:|"]
    cols = ("house_D_expected_seats", "house_D_218_probability_first_stage",
            "senate_D_expected_elected_seats", "senate_D_51_caucus_probability_all_O_to_D_first_stage",
            "governor_D_expected_wins")
    for previous, row in zip(rows, rows[1:]):
        changes = [row[key]-previous[key] for key in cols]
        out.append(f"| {labels[row['step']]} | {changes[0]:+.2f} | {changes[1]:+.1%} | "
                   f"{changes[2]:+.2f} | {changes[3]:+.1%} | {changes[4]:+.2f} |")
    governor_local = impact.get("governor_local_lean", {})
    governor_races = governor_local.get("current_race_impacts", [])
    out += ["", "## Governor local-lean model", "",
            f"The 2026 governor baseline uses **{governor_local.get('selected_specification', 'unavailable')}** "
            f"with ridge penalty **{governor_local.get('selected_ridge_alpha', 'unavailable')}**, selected on "
            "expanding-cycle errors through 2018. It predicts state governor lean relative to the drawn national House margin. "
            "The previous governor open-seat adjustment is disabled for governor races; open-seat status is not added a second time.",
            "", "The table compares the post-national, pre-poll governor baseline before and after local-lean recentering:", "",
            "| Race | Predicted local lean | Pre-poll D-R before | Pre-poll D-R after | D leader chance before | D leader chance after |",
            "|---|---:|---:|---:|---:|---:|"]
    ranked_governors = sorted(governor_races, key=lambda race: abs(
        race["pre_poll_margin_after"] - race["pre_poll_margin_before"]), reverse=True)
    for race in ranked_governors:
        out.append(f"| {race['state']} | {race['predicted_local_lean']*100:+.1f} points | "
                   f"{race['pre_poll_margin_before']*100:+.1f} points | "
                   f"{race['pre_poll_margin_after']*100:+.1f} points | "
                   f"{race['pre_poll_D_leader_probability_before']:.1%} | "
                   f"{race['pre_poll_D_leader_probability_after']:.1%} |")
    out += ["", "The historical terminal-result replay is an imperfect proxy for a forecast made at its historical cutoff. "
            "See `artifacts/calibration/governor_local_lean_audit.json` for the full expanding-cycle comparison."]
    house = forecast["joint_summaries"]["house"]["control"]
    senate = forecast["joint_summaries"]["senate"]["full_chamber"]["caucus_scenarios"]
    out += ["", "## Final forecast with counting rules", "",
            f"- House Democratic control: **{house['D_control_probability']:.1%}**.",
            f"- Senate Democratic control: **{senate['all_other_winners_caucus_D']['D_control_probability']:.1%}** "
            "if all elected independent or other winners caucus with Democrats; "
            f"**{senate['other_winners_unaligned']['D_control_probability']:.1%}** if they remain unaligned.",
            "- The Senate has no single overall control estimate while independent caucus choices remain unresolved.",
            "", "## Most affected races", ""]
    impacts = impact["race_impacts"]
    for step, previous in (("district_map","baseline"),
                           ("governor_approval","district_map"),
                           ("open_seat_candidate_experience","governor_approval")):
        ranked = sorted(impacts, key=lambda r: abs(r["steps"][step]["mean_D_minus_R_share_points"]-
                                                 r["steps"][previous]["mean_D_minus_R_share_points"]), reverse=True)
        out += [f"### {labels[step]}", "", "| Race | D–R mean share change | D first-stage leader change |",
                "|---|---:|---:|"]
        for race in ranked[:10]:
            change = race["steps"][step]["mean_D_minus_R_share_points"]-race["steps"][previous]["mean_D_minus_R_share_points"]
            lead = race["steps"][step]["D_first_stage_leader_probability"]-race["steps"][previous]["D_first_stage_leader_probability"]
            out.append(f"| {race['race_id']} | {change:+.2f} points | {lead:+.1%} |")
        out.append("")
    source = impact["input_metadata"]
    out += ["## Inputs and fitted terms", "",
            f"- District map: [The Downballot 2026 map]({source['map']['new_url']}) compared with "
            f"[the 2024 map]({source['map']['old_url']}); {source['map']['districts']} districts matched. "
            "Change in 2024 presidential Democratic-versus-Republican vote odds is added to the same-label prior House result.",
            f"- Governor approval: [Morning Consult]({source['approval_url']}) net approval, "
            f"surveys ending {source['approval_survey_end']}. It applies only when the prior governor is running again; "
            f"{source['coverage'].get('governor_approval_races',0)} races qualify. This snapshot is older than the poll cutoff.",
            "- Open seat and experience (House and Senate): a seat is open when the prior winner is absent from the ballot. "
            "Experience means the candidate previously won a general election for House, Senate, or governor in the same state. "
            "The seat and experience effects are estimated from historical transitions after removing election-wide residuals.",
            "", "| Office | Open-seat fitted coefficient | Prior elected winner coefficient | Active in 2026 nowcast | Training races |",
            "|---|---:|---:|---|---:|"]
    for office, fitted in impact["training"].items():
        beta = fitted["coefficients"]
        active = ("Yes" if fitted.get("active_in_2026_nowcast", True)
                  else "No; governor local-lean model is used")
        out.append(f"| {office} | {beta[0]:+.3f} | {beta[1]:+.3f} | {active} | "
                   f"{fitted['training_rows']} |")
    out += ["", "Coefficients are shifts in D/R log vote odds. The approval coefficient is per unit of net approval "
            "on a −1 to +1 scale. Poll updates attenuate these shifts in well-polled races.",
            "", "The first-stage ablation uses the current ballot registry and holds its candidate list fixed. "
            "The same-label map comparison can be less reliable where redistricting reassigned an incumbent to another district; "
            "inspect individual race rows in the JSON before treating large changes as definitive.", ""]
    (folder/"fundamentals_impact_2026.md").write_text("\n".join(out),encoding="utf-8")
    print(folder/"fundamentals_impact_2026.md")


if __name__ == "__main__":
    main()
