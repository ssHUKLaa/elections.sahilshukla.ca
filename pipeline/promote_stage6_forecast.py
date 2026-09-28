"""Mark a validated forecast public under the approved Stage 6 model version."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "artifacts/calibration/stage6_public_gate.json"
PUBLIC_STATUS = "public_nowcast_approved_with_limitations"
INTERNAL_STATUS = "internal_provisional_nowcast_not_for_publication"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-dir", type=Path, default=ROOT / "artifacts/nowcast")
    parser.add_argument("--gate", type=Path, default=GATE)
    args = parser.parse_args()
    forecast_path = args.forecast_dir / "forecast_2026.json"
    gate = json.loads(args.gate.read_text(encoding="utf-8"))
    forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
    metadata = forecast["metadata"]
    if gate["status"] != "passed" or gate["owner_model_decision"] != "accepted_with_documented_governor_limitations":
        raise ValueError("Version 0.20 has no passing owner-accepted public gate")
    if metadata["model_version"] != gate["live_model_version"]:
        raise ValueError("Forecast model version differs from public gate")
    for key, approved in gate["approved_model_code_sha256"].items():
        if metadata[key] != approved:
            raise ValueError(f"Forecast {key} differs from approved model")
    if metadata.get("reconstruction"):
        raise ValueError("Retrospective reconstructions are not recorded live forecasts")
    if (metadata["information_cutoff_utc"] == gate["frozen_live_cutoff"]
            and forecast["publication_status"] == INTERNAL_STATUS
            and sha(forecast_path) != gate["hashes"]["frozen_source_forecast"]):
        raise ValueError("Frozen live forecast differs from the reviewed candidate")
    if forecast["publication_status"] == PUBLIC_STATUS:
        print(json.dumps({"status": "already_public", "version": metadata["model_version"]}))
        return
    if forecast["publication_status"] != INTERNAL_STATUS:
        raise ValueError("Unexpected source forecast publication status")
    subprocess.run([sys.executable, str(ROOT / "pipeline/validate_stage5.py"),
                    "--artifact-dir", str(args.forecast_dir)], cwd=ROOT, check=True,
                   stdout=subprocess.DEVNULL)
    forecast["publication_status"] = PUBLIC_STATUS
    pending = forecast_path.with_name("forecast_2026.publication.pending.json")
    pending.write_text(json.dumps(forecast, indent=2) + "\n", encoding="utf-8")
    os.replace(pending, forecast_path)
    print(json.dumps({"status": "public", "version": metadata["model_version"],
                      "forecast_sha256": sha(forecast_path)}))


if __name__ == "__main__":
    main()
