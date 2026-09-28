"""Build a clearly labeled retrospective daily 2026 nowcast series."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
EASTERN = ZoneInfo("America/New_York")
MODEL = ROOT / "modeling/stage5_outcome_model.py"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def source_time(stage2: Path, stage1: Path) -> datetime:
    with sqlite3.connect(stage2) as connection:
        snapshot_id = dict(connection.execute("SELECT key,value FROM build_metadata"))["source_snapshot_id"]
    with sqlite3.connect(stage1) as connection:
        row = connection.execute("SELECT retrieved_at_utc FROM source_snapshots WHERE snapshot_id=?",
                                 (snapshot_id,)).fetchone()
    if row is None:
        raise ValueError(f"Missing source snapshot {snapshot_id}")
    return datetime.strptime(row[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def cutoff_for_day(day: date, retrieved: datetime) -> datetime:
    next_midnight = datetime.combine(day + timedelta(days=1), time.min, EASTERN)
    end_of_day = (next_midnight - timedelta(seconds=1)).astimezone(timezone.utc)
    return min(end_of_day, retrieved)


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command)}\n"
                           f"{result.stdout[-4000:]}\n{result.stderr[-4000:]}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", type=date.fromisoformat, default=date(2026, 9, 16))
    parser.add_argument("--end-date", type=date.fromisoformat)
    parser.add_argument("--stage1-database", type=Path, default=ROOT / "data/processed/stage1.sqlite")
    parser.add_argument("--database", type=Path, default=ROOT / "data/processed/stage2.sqlite")
    parser.add_argument("--output-root", type=Path, default=ROOT / "artifacts/nowcast_history")
    parser.add_argument("--draws", type=int, default=75000)
    parser.add_argument("--no-index", action="store_true", help="Produce only this date range; another run will assemble the full index")
    args = parser.parse_args()
    retrieved = source_time(args.database, args.stage1_database)
    last_day = retrieved.astimezone(EASTERN).date()
    end = args.end_date or last_day
    if args.start_date > end or end > last_day:
        raise ValueError(f"Date range must end no later than saved snapshot day {last_day}")
    database_sha = sha(args.database)
    model_sha = sha(MODEL)
    entries = []
    day = args.start_date
    while day <= end:
        cutoff = cutoff_for_day(day, retrieved)
        cutoff_text = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")
        output = args.output_root / day.isoformat()
        forecast_path = output / "forecast_2026.json"
        reusable = False
        if forecast_path.exists() and (output / "senate_extremes_2026.json").exists():
            old = json.loads(forecast_path.read_text(encoding="utf-8"))
            metadata = old["metadata"]
            reusable = (metadata.get("information_cutoff_utc") == cutoff_text
                        and metadata.get("data_sha256") == database_sha
                        and metadata.get("model_code_sha256") == model_sha
                        and metadata.get("simulation_draws") == args.draws
                        and metadata.get("reconstruction", {}).get("kind") == "retrospective_poll_cutoff")
        if not reusable:
            run([sys.executable, str(MODEL), "--database", str(args.database),
                 "--stage1-database", str(args.stage1_database), "--output-dir", str(output),
                 "--draws", str(args.draws), "--information-cutoff-utc", cutoff_text])
        run([sys.executable, str(ROOT / "pipeline/validate_stage5.py"),
             "--database", str(args.database), "--stage1-database", str(args.stage1_database),
             "--artifact-dir", str(output)])
        forecast = json.loads(forecast_path.read_text(encoding="utf-8"))
        house = forecast["joint_summaries"]["house"]["control"]
        senate = forecast["joint_summaries"]["senate"]["full_chamber"]["caucus_scenarios"]
        included_race_polls = sum(race["poll_diagnostics"]["poll_count"]
                                  for race in forecast["races"])
        entries.append({
            "date": day.isoformat(), "information_cutoff_utc": cutoff_text,
            "source_snapshot_after_cutoff": cutoff < retrieved,
            "kind": "retrospective_poll_cutoff",
            "forecast_path": str(forecast_path.relative_to(ROOT)).replace("\\", "/"),
            "forecast_sha256": sha(forecast_path),
            "senate_extremes_sha256": sha(output / "senate_extremes_2026.json"),
            "stage2_database_sha256": database_sha,
            "model_code_sha256": model_sha,
            "included_race_polls": included_race_polls,
            "house_D_control_probability": house["D_control_probability"],
            "senate_D_control_probability_unaligned": senate["other_winners_unaligned"]["D_control_probability"],
            "senate_D_control_probability_all_other_to_D": senate["all_other_winners_caucus_D"]["D_control_probability"],
        })
        print(f"Completed {day} cutoff {cutoff_text}", flush=True)
        day += timedelta(days=1)
    if args.no_index:
        print(f"Completed {len(entries)} daily forecasts without replacing the history index", flush=True)
        return
    index_path = args.output_root / "index.json"
    retained = []
    if index_path.exists():
        existing = json.loads(index_path.read_text(encoding="utf-8"))
        replaced_dates = {entry["date"] for entry in entries}
        retained = [entry for entry in existing.get("entries", [])
                    if entry["date"] not in replaced_dates]
    report = {
        "description": "Retrospective 2026 poll-cutoff nowcasts, not forecasts recorded on these dates.",
        "limitation": "All dates use the saved source feed and currently reviewed candidate and map inputs; source revisions and later roster knowledge may affect earlier points.",
        "timezone_for_slider_dates": "America/New_York",
        "source_snapshot_retrieved_at_utc": retrieved.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stage2_database_sha256": database_sha,
        "model_code_sha256": model_sha,
        "draws_per_day": args.draws,
        "entries": sorted(retained + entries, key=lambda entry: entry["date"]),
    }
    args.output_root.mkdir(parents=True, exist_ok=True)
    pending = args.output_root / "index.pending.json"
    pending.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    pending.replace(index_path)
    print(f"Wrote {len(report['entries'])} days to {index_path}", flush=True)


if __name__ == "__main__":
    main()
