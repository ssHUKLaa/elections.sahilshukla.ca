"""Write the expanding-cycle governor local-lean audit."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from modeling import governor_local_lean as governor
from modeling import stage3_results_baseline as stage3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "artifacts/calibration/governor_local_lean_audit.json")
    args = parser.parse_args()
    connection = sqlite3.connect(args.database)
    connection.row_factory = sqlite3.Row
    try:
        historical = stage3.load_historical_races(connection)
        transitions = stage3.build_transitions(historical)
        current = stage3.load_current_races(connection)
    finally:
        connection.close()
    predictions, report = governor.predict_current(current, historical, transitions)
    evaluation = report["expanding_cycle_evaluation"]
    output = {
        "design": {
            "estimand": "governor two-party margin relative to national House two-party margin",
            "evaluation": "expanding-cycle; tune through 2018; later-cycle check starts in 2020",
            "target_limitation": "Historical certified results proxy election-held-today support and include later campaign movement.",
            "feature_cutoff": "Every presidential feature uses the latest presidential result before its governor election.",
            "uncertainty": "The D/R log-ratio residual SD is floored at later-cycle out-of-fold error; cross-party-incumbent and local-signal-disagreement floors are used when at least five cases support them.",
        },
        "model_code_sha256": governor.sha256(Path(governor.__file__)),
        "database_sha256": report["source_hashes"]["stage2_database"],
        "source_hashes": {key: value for key, value in report["source_hashes"].items()
                          if key != "stage2_database"},
        "training_rows": report["training_rows"],
        "training_cycles": report["training_cycles"],
        "selected_specification": report["selected_specification"],
        "selected_ridge_alpha": report["selected_ridge_alpha"],
        "coefficients": report["coefficients"],
        "excluded_missing_major_party_rows": report["excluded_missing_major_party_rows"],
        "excluded_missing_major_party_examples": report["excluded_missing_major_party_examples"],
        "subgroup_scores": report["subgroup_scores"],
        "uncertainty_calibration": report["uncertainty_calibration"],
        "specification_scores": evaluation["scores"],
        "selected_expanding_predictions": evaluation["selected_prediction_rows"],
        "current_race_predictions": predictions,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "complete", "output": str(args.output),
                      "training_rows": report["training_rows"],
                      "selected_specification": report["selected_specification"],
                      "selected_ridge_alpha": report["selected_ridge_alpha"],
                      "current_races": len(predictions)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
