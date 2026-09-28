"""Silver Bulletin 2026 pollster precision with 538 fallback by stable ID."""

from __future__ import annotations

import csv
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path


def load_weights(
    stage1_path: Path, ratings_path: Path,
    silver_path: Path = Path("data/reference/pollster_ratings/silver_2026.csv"),
    snapshot_id: str | None = None,
) -> tuple[dict[str, float], dict]:
    with ratings_path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    grades = {}
    for row in rows:
        try:
            grade = float(row["numeric_grade"])
        except (ValueError, TypeError):
            continue
        if 0.5 <= grade <= 3.0:
            grades[str(row["pollster_rating_id"])] = grade
    with silver_path.open(encoding="utf-8-sig", newline="") as stream:
        silver_rows = list(csv.DictReader(stream))
    silver = {}
    expected_error_total = 0.0
    expected_error_polls = 0
    for row in silver_rows:
        pollster_id = str(row["pollster_rating_id"])
        if pollster_id in silver:
            raise ValueError(f"Duplicate Silver Bulletin pollster ID {pollster_id}")
        silver[pollster_id] = row
        if row["simple_expected_error"] and row["poll_count"]:
            polls = int(row["poll_count"])
            expected_error_total += float(row["simple_expected_error"]) * polls
            expected_error_polls += polls
    if len(silver) < 500 or expected_error_polls <= 0:
        raise ValueError("Unexpected Silver Bulletin ratings coverage")
    baseline_error = expected_error_total / expected_error_polls
    connection = sqlite3.connect(stage1_path)
    try:
        if snapshot_id is None:
            latest = connection.execute(
                "SELECT snapshot_id FROM source_snapshots ORDER BY retrieved_at_utc DESC LIMIT 1"
            ).fetchone()
            if latest is None:
                raise ValueError("No NYT source snapshot in Stage 1 database")
            snapshot_id = latest[0]
        polls = connection.execute(
            "SELECT feed,source_poll_id,raw_poll_json FROM polls WHERE snapshot_id=?",
            (snapshot_id,),
        ).fetchall()
    finally:
        connection.close()
    coverage = Counter()
    weights = {}
    for feed, poll_id, raw_text in polls:
        raw = json.loads(raw_text)
        pollster_id = str(raw.get("pollster_rating_id", ""))
        silver_row = silver.get(pollster_id)
        grade = grades.get(pollster_id)
        coverage[f"{feed}_total"] += 1
        if silver_row is not None and silver_row["banned"] == "True":
            weights[poll_id] = 0.0
            coverage[f"{feed}_silver_banned"] += 1
        elif silver_row is not None:
            ppm = float(silver_row["predictive_plus_minus"])
            predicted_error = baseline_error + ppm
            if predicted_error <= 0:
                raise ValueError(f"Nonpositive predicted error for {pollster_id}")
            weights[poll_id] = (baseline_error / predicted_error) ** 2
            coverage[f"{feed}_silver"] += 1
            coverage[f"{feed}_rated"] += 1
        elif grade is not None:
            coverage[f"{feed}_538_fallback"] += 1
            coverage[f"{feed}_rated"] += 1
        else:
            coverage[f"{feed}_unrated"] += 1
    # Use the original live-poll reference to retain the 538 fallback's scale.
    all_538_grades = []
    for _, _, raw_text in polls:
        grade = grades.get(str(json.loads(raw_text).get("pollster_rating_id", "")))
        if grade is not None:
            all_538_grades.append(grade)
    reference = sum(all_538_grades) / len(all_538_grades)
    for _, poll_id, raw_text in polls:
        if poll_id in weights:
            continue
        grade = grades.get(str(json.loads(raw_text).get("pollster_rating_id", "")))
        if grade is not None:
            weights[poll_id] = math.sqrt(grade / reference)
    return weights, {
        "silver_rows": len(silver_rows), "538_rows": len(rows),
        "silver_reference_expected_error_margin_points": baseline_error,
        "538_reference_grade": reference, "feed_coverage": dict(coverage),
        "unrated_weight": 1.0,
        "silver_weight_formula": "(reference_expected_error / (reference_expected_error + predictive_plus_minus))^2",
        "538_fallback_weight_formula": "sqrt(numeric_grade / mean_grade_of_matched_live_polls)",
        "silver_banned_weight": 0.0,
        "silver_path": str(silver_path), "538_path": str(ratings_path),
        "live_snapshot_id": snapshot_id,
    }
