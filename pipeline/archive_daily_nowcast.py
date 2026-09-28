"""Archive a validated live nowcast once per Eastern calendar day."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
FILES = ("forecast_2026.json", "model_parameters.json", "fundamentals_impact_2026.json",
         "senate_extremes_2026.json")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--forecast-dir", type=Path, default=ROOT / "artifacts/nowcast")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts/nowcast_history")
    args = parser.parse_args()
    args.output_root = args.output_root.resolve()
    forecast = json.loads((args.forecast_dir / FILES[0]).read_text(encoding="utf-8"))
    metadata = forecast["metadata"]
    if metadata.get("reconstruction"):
        raise ValueError("A retrospective reconstruction cannot be archived as a recorded forecast")
    recorded_at = datetime.now(timezone.utc)
    day = recorded_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    output = args.output_root / day
    output.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        source = args.forecast_dir / name
        pending = output / (name + ".pending")
        shutil.copyfile(source, pending)
        os.replace(pending, output / name)
    archived_forecast = output / FILES[0]
    house = forecast["joint_summaries"]["house"]["control"]
    senate = forecast["joint_summaries"]["senate"]["full_chamber"]["caucus_scenarios"]
    entry = {
        "date": day,
        "recorded_at_utc": recorded_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "information_cutoff_utc": metadata["information_cutoff_utc"],
        "source_snapshot_after_cutoff": False,
        "kind": "recorded_live",
        "forecast_path": str(archived_forecast.relative_to(ROOT)).replace("\\", "/"),
        "forecast_sha256": sha(archived_forecast),
        "senate_extremes_sha256": sha(output / "senate_extremes_2026.json"),
        "stage2_database_sha256": metadata["data_sha256"],
        "model_code_sha256": metadata["model_code_sha256"],
        "included_race_polls": sum(race["poll_diagnostics"]["poll_count"] for race in forecast["races"]),
        "house_D_control_probability": house["D_control_probability"],
        "senate_D_control_probability_unaligned": senate["other_winners_unaligned"]["D_control_probability"],
        "senate_D_control_probability_all_other_to_D": senate["all_other_winners_caucus_D"]["D_control_probability"],
    }
    index_path = args.output_root / "index.json"
    if index_path.exists():
        report = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        report = {
            "description": "Daily 2026 nowcast history. Entry kind identifies reconstructions and recorded live forecasts.",
            "limitation": "Retrospective entries use a later saved feed and currently reviewed candidate and map inputs.",
            "timezone_for_slider_dates": "America/New_York",
            "entries": [],
        }
    report["entries"] = sorted(
        [old for old in report["entries"] if old["date"] != day] + [entry],
        key=lambda item: item["date"],
    )
    pending_index = args.output_root / "index.pending.json"
    pending_index.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    os.replace(pending_index, index_path)
    print(f"Archived {day} nowcast in {output} and updated {index_path}", flush=True)


if __name__ == "__main__":
    main()
