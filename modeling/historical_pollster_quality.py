"""As-of 538 pollster precision weights for the Stage 6 historical replay."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATINGS = ROOT / "data/reference/pollster_ratings/historical"
POLLS = ROOT / "data/raw/historical_wayback/20241129"
POLL_MANIFEST = ROOT / "data/reference/stage6_wayback_manifest.json"


def rating_weights(cycle: int) -> tuple[dict[str, float], dict]:
    manifest_path = RATINGS / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    edition = str(manifest["replay_use"][str(cycle)])
    spec = manifest["files"][edition]
    rating_path = RATINGS / spec["filename"]
    if hashlib.sha256(rating_path.read_bytes()).hexdigest() != spec["sha256"]:
        raise ValueError(f"Historical rating hash mismatch: {rating_path}")
    rows = list(csv.DictReader(rating_path.open(encoding="utf-8-sig", newline="")))
    valid = []
    banned_ids = set()
    for row in rows:
        if row.get("Banned by 538", "").strip().lower() == "yes":
            banned_ids.add(row["Pollster Rating ID"])
        try:
            expected_error = float(row["Simple Expected Error"])
            ppm = float(row["Predictive Plus-Minus"])
            count = float(row.get("Polls Analyzed") or row.get("# of Polls") or 0)
        except (ValueError, TypeError):
            continue
        if expected_error > 0 and count > 0:
            valid.append((row, expected_error, ppm, count))
    baseline = sum(error * count for _, error, _, count in valid) / sum(count for _, _, _, count in valid)
    by_id = {}
    for row, _, ppm, _ in valid:
        if row["Pollster Rating ID"] in banned_ids:
            weight = 0.0
        else:
            predicted_error = baseline + ppm
            weight = (baseline / predicted_error) ** 2 if predicted_error > 0 else 1.0
        by_id[row["Pollster Rating ID"]] = weight
    by_id.update({rating_id: 0.0 for rating_id in banned_ids})
    return by_id, {
        "rating_edition": edition, "rating_sha256": spec["sha256"],
        "rating_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "reference_expected_error_points": baseline,
        "weight_formula": "(reference_expected_error / (reference_expected_error + predictive_plus_minus))^2",
        "unrated_weight": 1.0, "banned_weight": 0.0,
    }


def load(cycle: int) -> tuple[dict[str, float], dict]:
    by_id, metadata = rating_weights(cycle)
    poll_manifest = json.loads(POLL_MANIFEST.read_text(encoding="utf-8"))
    weights = {}
    coverage = Counter()
    for filename, file_spec in poll_manifest["files"].items():
        if cycle not in file_spec["cycle_use"]:
            continue
        with (POLLS / filename).open(encoding="utf-8-sig", newline="") as stream:
            for row in csv.DictReader(stream):
                if row.get("cycle") != str(cycle):
                    continue
                key = f"wayback:{row['poll_id']}"
                weights[key] = by_id.get(row.get("pollster_rating_id", ""), 1.0)
                coverage["rated" if row.get("pollster_rating_id", "") in by_id else "unrated"] += 1
                if weights[key] == 0:
                    coverage["banned"] += 1
    return weights, {**metadata, "coverage_rows": dict(coverage)}
