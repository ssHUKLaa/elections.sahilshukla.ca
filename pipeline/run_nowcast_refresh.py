"""Refresh NYT polls, rebuild the nowcast, validate, and publish local artifacts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(*args: str) -> None:
    command = [sys.executable, *args]
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-pull", action="store_true", help="Use the existing Stage 1 snapshot")
    parser.add_argument("--draws", type=int, default=75000)
    args = parser.parse_args()
    stage1 = Path("data/processed/stage1.sqlite")
    pending_stage2 = Path("data/processed/stage2.pending.sqlite")
    current_stage2 = Path("data/processed/stage2.sqlite")
    pending_dir = Path("artifacts/.nowcast_pending")
    current_dir = Path("artifacts/nowcast")
    if not args.skip_pull:
        run("pipeline/run_stage1_pull.py")
    run("pipeline/validate_stage1.py")
    run("pipeline/build_stage2.py", "--stage1-database", str(stage1),
        "--output", str(pending_stage2))
    run("pipeline/validate_stage2.py", "--database", str(pending_stage2),
        "--stage1-database", str(stage1))
    run("modeling/stage5_outcome_model.py", "--database", str(pending_stage2),
        "--stage1-database", str(stage1), "--output-dir", str(pending_dir),
        "--draws", str(args.draws))
    run("pipeline/validate_stage5.py", "--database", str(pending_stage2),
        "--stage1-database", str(stage1), "--artifact-dir", str(pending_dir))
    current_dir.mkdir(parents=True, exist_ok=True)
    os.replace(pending_stage2, current_stage2)
    for name in ("model_parameters.json", "forecast_2026.json", "fundamentals_impact_2026.json",
                 "senate_extremes_2026.json"):
        os.replace(pending_dir / name, current_dir / name)
    gate_path = Path("artifacts/calibration/stage6_public_gate.json")
    if gate_path.is_file():
        gate = json.loads(gate_path.read_text(encoding="utf-8"))
        forecast = json.loads((current_dir / "forecast_2026.json").read_text(encoding="utf-8"))
        approved_code = gate.get("approved_model_code_sha256", {})
        if (gate.get("status") == "passed" and
                gate.get("live_model_version") == forecast["metadata"]["model_version"] and
                approved_code and all(forecast["metadata"].get(key) == value
                                      for key, value in approved_code.items())):
            run("pipeline/promote_stage6_forecast.py", "--forecast-dir", str(current_dir))
    run("pipeline/render_fundamentals_impact.py", "--artifact-dir", str(current_dir))
    run("pipeline/archive_daily_nowcast.py", "--forecast-dir", str(current_dir))
    print("Validated nowcast published to", current_dir, flush=True)


if __name__ == "__main__":
    main()
