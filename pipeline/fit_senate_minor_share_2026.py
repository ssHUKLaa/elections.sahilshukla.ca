"""Fit the 2026 Senate minor-candidate share prior from archived elections."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import senate_minor_share
from modeling import stage3_results_baseline as stage3
from modeling.stage5_outcome_model import senate_contender_screen
from pipeline import load_stage6_wayback_polls

DB = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "data/reference/senate_minor_share_fit_2026.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, default=DB)
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        races = stage3.load_historical_races(connection)
    questions, _ = load_stage6_wayback_polls.load(races)
    fitted = senate_minor_share.fit(races, questions, 2024, senate_contender_screen)
    fitted["source_database_sha256"] = sha(args.database)
    fitted["source_poll_manifest_sha256"] = sha(ROOT / "data/reference/stage6_wayback_manifest.json")
    fitted["model_code_sha256"] = sha(ROOT / "modeling/senate_minor_share.py")
    OUTPUT.write_text(json.dumps(fitted, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: fitted[key] for key in (
        "training_cycles", "n_candidate_observations", "alpha", "beta"
    )}, indent=2))
    print(OUTPUT)


if __name__ == "__main__":
    main()
