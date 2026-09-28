"""Preserve a forecast before later election results become available."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FORECAST_DIR = ROOT / "artifacts/nowcast"
DATABASE = ROOT / "data/processed/stage2.sqlite"
OUTPUT = ROOT / "artifacts/calibration/frozen_2026-09-23"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--forecast-dir", type=Path, default=FORECAST_DIR)
    parser.add_argument("--database", type=Path, default=DATABASE)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    forecast_path = args.forecast_dir / "forecast_2026.json"
    parameters_path = args.forecast_dir / "model_parameters.json"
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    if forecast["metadata"]["data_sha256"] != sha(args.database):
        raise ValueError("Forecast and Stage 2 database differ")
    code = {str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
            for folder in (ROOT / "modeling", ROOT / "pipeline")
            for path in sorted(folder.glob("*.py"))}
    sources = {
        str(path.relative_to(ROOT)).replace("\\", "/"): sha(path)
        for path in (
            args.database,
            ROOT / "data/processed/stage1.sqlite",
            ROOT / "data/reference/races_2026.json",
            ROOT / "data/reference/ballot_registry_2026.json",
            ROOT / "data/reference/stage6_historical_house_map_shifts.json",
            ROOT / "data/reference/pollster_ratings/silver_2026.csv",
        )
    }
    hashes = {"forecast_2026.json": sha(forecast_path),
              "model_parameters.json": sha(parameters_path)}
    manifest_path = args.output_dir / "manifest.json"
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old["frozen_artifact_sha256"] != hashes:
            raise ValueError("Frozen forecast already exists with different content")
        print(json.dumps({"status": "already_frozen", "output": str(args.output_dir)}))
        return
    args.output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(forecast_path, args.output_dir / forecast_path.name)
    shutil.copy2(parameters_path, args.output_dir / parameters_path.name)
    manifest = {
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "information_cutoff_utc": forecast["metadata"]["information_cutoff_utc"],
        "model_version": forecast["metadata"]["model_version"],
        "purpose": "Prospective long-lead terminal-result diagnostic; November outcomes are not direct held-today labels.",
        "frozen_artifact_sha256": hashes,
        "input_sha256": sources,
        "code_sha256": code,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "frozen", "output": str(args.output_dir),
                      "forecast_sha256": hashes["forecast_2026.json"]}))


if __name__ == "__main__":
    main()
