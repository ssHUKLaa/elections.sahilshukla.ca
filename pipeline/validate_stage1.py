"""Run the Stage 1 acquisition and replay acceptance checks."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from pathlib import Path

from ingest_nyt_snapshot import ingest_snapshot
from query_nyt_as_of import export_as_of
from snapshot_nyt_polls import assert_expected_schema, load_schema_contract


def csv_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return sum(1 for _ in csv.DictReader(stream))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def snapshot_content_hash(snapshot: Path) -> str:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("content_sha256"):
        return manifest["content_sha256"]
    digest = hashlib.sha256()
    for name, record in sorted(manifest["files"].items()):
        digest.update(name.encode("utf-8"))
        digest.update(record["sha256"].encode("ascii"))
    return digest.hexdigest()


def validate_historical(root: Path) -> tuple[str, int]:
    snapshots = sorted(path for path in root.iterdir() if path.is_dir())
    if not snapshots:
        raise AssertionError("no historical source snapshot exists")
    snapshot = snapshots[-1]
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    catalog = json.loads(
        Path("data/reference/stage1_source_catalog.json").read_text(encoding="utf-8")
    )
    expected = {source["id"] for source in catalog["sources"]}
    if set(manifest["files"]) != expected:
        raise AssertionError("historical manifest does not match the source catalog")
    for source_id, record in manifest["files"].items():
        path = snapshot / record["filename"]
        if sha256(path) != record["sha256"]:
            raise AssertionError(f"historical checksum mismatch: {source_id}")
        if record["format"] == "csv" and record.get("rows", 0) < 1:
            raise AssertionError(f"historical CSV is empty: {source_id}")
        if record["format"] == "pdf" and not path.read_bytes().startswith(b"%PDF-"):
            raise AssertionError(f"historical PDF signature is invalid: {source_id}")
    required = {
        "538_archive_senate_polls",
        "538_archive_house_polls",
        "538_archive_governor_polls",
        "538_results_senate",
        "538_results_house",
        "538_results_governor",
        "fec_federal_elections_2010",
        "fec_federal_elections_2012",
        "fec_federal_elections_2014",
        "fec_federal_elections_2016",
        "fec_federal_elections_2018",
        "fec_federal_elections_2020",
        "fec_federal_elections_2022",
        "house_clerk_federal_elections_2024",
    }
    if not required <= expected:
        raise AssertionError("historical catalog lacks required polls or result cycles")
    return snapshot.name, len(expected)


def validate(snapshot_root: Path, historical_root: Path) -> dict[str, object]:
    snapshots = sorted(
        path
        for path in snapshot_root.iterdir()
        if path.is_dir() and not path.name.endswith(".incomplete")
    )
    if len(snapshots) < 2:
        raise AssertionError("Stage 1 requires at least two complete NYT snapshots")
    first = snapshots[0]
    changed = [
        candidate
        for candidate in snapshots[1:]
        if snapshot_content_hash(candidate) != snapshot_content_hash(first)
    ]
    if not changed:
        raise AssertionError("two complete pulls exist, but no changed source snapshot is available")
    second = changed[-1]

    temp_path = Path("data/processed/validation")
    temp_path.mkdir(parents=True, exist_ok=True)
    database = temp_path / "stage1-gate.sqlite"
    for old_artifact in (database, temp_path / "early.json", temp_path / "late.json"):
        old_artifact.unlink(missing_ok=True)
    try:
        first_result = ingest_snapshot(first, database)
        repeated_result = ingest_snapshot(first, database)
        second_result = ingest_snapshot(second, database)
        if first_result["status"] != "ingested":
            raise AssertionError("first snapshot did not ingest")
        if repeated_result["status"] != "already_ingested":
            raise AssertionError("replay was not idempotent")
        if second_result["status"] != "ingested":
            raise AssertionError("second snapshot did not create a new version")

        connection = sqlite3.connect(database)
        try:
            snapshot_rows = connection.execute(
                "SELECT snapshot_id, retrieved_at_utc, content_sha256 FROM source_snapshots "
                "ORDER BY retrieved_at_utc"
            ).fetchall()
            if len(snapshot_rows) != 2:
                raise AssertionError("expected exactly two source snapshots after replay")
            if snapshot_rows[0][2] == snapshot_rows[1][2]:
                raise AssertionError("test pulls did not contain a source-data change")

            for snapshot, result in ((first, first_result), (second, second_result)):
                snapshot_id = result["snapshot_id"]
                expected_race_options = sum(
                    csv_rows(snapshot / f"{feed}.csv")
                    for feed in ("senate", "house", "governor", "other")
                )
                actual_race_options = connection.execute(
                    """SELECT COUNT(*) FROM poll_options o JOIN questions q
                    ON o.snapshot_id=q.snapshot_id AND o.question_key=q.question_key
                    WHERE o.snapshot_id=? AND q.feed IN ('senate','house','governor','other')""",
                    (snapshot_id,),
                ).fetchone()[0]
                if actual_race_options != expected_race_options:
                    raise AssertionError("a race-poll answer row was lost during normalization")

            early_output = temp_path / "early.json"
            late_output = temp_path / "late.json"
            early = export_as_of(
                database, snapshot_rows[0][1], early_output, ["senate"]
            )
            late = export_as_of(
                database, snapshot_rows[1][1], late_output, ["senate"]
            )
            if early["snapshot_id"] == late["snapshot_id"]:
                raise AssertionError("as-of queries did not select distinct versions")
        finally:
            connection.close()
    finally:
        for artifact in (database, temp_path / "early.json", temp_path / "late.json"):
            artifact.unlink(missing_ok=True)

    contract = load_schema_contract(Path("data/reference/nyt_poll_schema_v1.json"))
    drift_detected = False
    try:
        assert_expected_schema("senate", contract["senate"] + ["unexpected"], contract["senate"])
    except ValueError:
        drift_detected = True
    if not drift_detected:
        raise AssertionError("schema drift did not stop validation")

    historical_snapshot, historical_source_count = validate_historical(historical_root)

    return {
        "status": "passed",
        "snapshots_tested": [first.name, second.name],
        "idempotent_replay": True,
        "source_change_created_new_snapshot": True,
        "full_question_vectors_preserved": True,
        "schema_drift_stops_pipeline": True,
        "as_of_replay_selects_correct_snapshot": True,
        "historical_snapshot": historical_snapshot,
        "historical_sources_verified": historical_source_count,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, default=Path("data/raw/nyt"))
    parser.add_argument(
        "--historical-root", type=Path, default=Path("data/raw/historical")
    )
    args = parser.parse_args()
    print(json.dumps(validate(args.snapshot_root, args.historical_root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
