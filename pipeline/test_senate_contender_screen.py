"""Check the proposed other-party contender screen on archived Senate polls."""

from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import stage3_results_baseline as stage3
from modeling import stage4_poll_model as stage4
from modeling.stage5_outcome_model import senate_contender_screen
from pipeline import load_stage6_wayback_polls

DB = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "artifacts/calibration/senate_contender_screen_historical.json"


def main() -> None:
    with sqlite3.connect(DB) as connection:
        races = stage3.load_historical_races(connection)
    questions, _ = load_stage6_wayback_polls.load(races)
    senate = [race for race in races if race.office == "senate"
              and race.cycle in {2020, 2022, 2024} and race.state not in {"AK", "GA"}]
    cells = []
    for lead_days in (90, 30, 7):
        available = defaultdict(list)
        for question in questions:
            if question.office == "senate" and stage4.eligible_at_cutoff(question, lead_days):
                available[question.race_key].append(question)
        evaluated = screened = excluded = excluded_winners = 0
        examples = []
        screened_shares = []
        unpolled_shares = []
        polled_shares = []
        for race in senate:
            candidates = [
                {"ballot_entry_id": candidate.candidate_key, "party": candidate.party}
                for candidate in race.candidates
            ]
            item = {"race": {"office": "senate", "counting_rule": "plurality"},
                    "candidates": candidates}
            screen = senate_contender_screen(item, available[race.source_race_id], None)
            if screen["usable_poll_count"] < 3:
                continue
            evaluated += 1
            if not screen["applied"]:
                continue
            screened += 1
            excluded_keys = set(screen["excluded_candidates"])
            total_votes = sum(candidate.votes for candidate in race.candidates)
            mentioned = {option.candidate_key for question in available[race.source_race_id]
                         for option in question.options if option.candidate_key}
            for candidate in race.candidates:
                if candidate.candidate_key not in excluded_keys:
                    continue
                excluded += 1
                share = candidate.votes/total_votes
                screened_shares.append(share)
                (polled_shares if candidate.candidate_key in mentioned else unpolled_shares).append(share)
                if candidate.winner:
                    excluded_winners += 1
                    examples.append({"cycle": race.cycle, "state": race.state,
                                     "name": candidate.name,
                                     "polls": screen["usable_poll_count"]})
        cells.append({
            "lead_days": lead_days,
            "eligible_senate_races_at_least_3_polls": evaluated,
            "races_with_screened_candidate": screened,
            "candidate_entries_screened": excluded,
            "actual_winners_screened": excluded_winners,
            "winner_failures": examples,
            "screened_share_median": statistics.median(screened_shares) if screened_shares else None,
            "screened_share_max": max(screened_shares) if screened_shares else None,
            "unpolled_n": len(unpolled_shares),
            "unpolled_share_median": statistics.median(unpolled_shares) if unpolled_shares else None,
            "unpolled_share_mean": statistics.mean(unpolled_shares) if unpolled_shares else None,
            "unpolled_share_max": max(unpolled_shares) if unpolled_shares else None,
            "polled_n": len(polled_shares),
            "polled_share_median": statistics.median(polled_shares) if polled_shares else None,
            "polled_share_mean": statistics.mean(polled_shares) if polled_shares else None,
            "polled_share_max": max(polled_shares) if polled_shares else None,
        })
    report = {
        "design": "Historical safety test of the proposed current-ballot Senate plurality contender screen. Counts distinct archived polls available at each cutoff; excludes AK ranked-choice and GA runoff races. Uses final-result candidate roster, so early cutoffs can leak later ballot status.",
        "cells": cells,
    }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(cells, indent=2))
    print(OUTPUT)


if __name__ == "__main__":
    main()
