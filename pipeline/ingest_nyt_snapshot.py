"""Ingest one immutable NYT snapshot into the Stage 1 replay database.

The database stores a complete version of every question for every source snapshot.
Reingesting the same snapshot is a no-op. Different retrievals remain distinct even
when their payloads are identical, which makes an as-of query reproducible.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from snapshot_nyt_polls import (
    DEFAULT_SCHEMA_CONTRACT,
    SOURCES,
    assert_expected_schema,
    load_schema_contract,
)


RACE_FEEDS = ("senate", "house", "governor", "other")
OPTION_COLUMNS = {
    "party",
    "pct",
    "answer",
    "candidate_name",
    "candidate_id",
    "ranked_choice_round",
    "ranked_choice_reallocated",
    "ranked_choice_final",
}


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS source_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    retrieved_at_utc TEXT NOT NULL,
    raw_path TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    schema_contract_sha256 TEXT NOT NULL,
    permission_record TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    ingested_at_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS source_snapshots_raw_path
    ON source_snapshots(raw_path);

CREATE TABLE IF NOT EXISTS polls (
    snapshot_id TEXT NOT NULL,
    feed TEXT NOT NULL,
    source_poll_id TEXT NOT NULL,
    pollster TEXT,
    pollster_id TEXT,
    sponsors TEXT,
    methodology TEXT,
    start_date TEXT,
    end_date TEXT,
    source_created_at TEXT,
    poll_url TEXT,
    raw_poll_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, feed, source_poll_id),
    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS questions (
    snapshot_id TEXT NOT NULL,
    question_key TEXT NOT NULL,
    feed TEXT NOT NULL,
    source_poll_id TEXT NOT NULL,
    source_question_id TEXT NOT NULL,
    state TEXT,
    cycle TEXT,
    office_type TEXT,
    seat_name TEXT,
    seat_number TEXT,
    election_date TEXT,
    stage TEXT,
    sample_size TEXT,
    population TEXT,
    population_full TEXT,
    hypothetical TEXT,
    source_race_id TEXT,
    source_created_at TEXT,
    availability_basis TEXT NOT NULL,
    raw_question_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, question_key),
    FOREIGN KEY (snapshot_id, feed, source_poll_id)
      REFERENCES polls(snapshot_id, feed, source_poll_id)
);

CREATE TABLE IF NOT EXISTS poll_options (
    snapshot_id TEXT NOT NULL,
    question_key TEXT NOT NULL,
    option_index INTEGER NOT NULL,
    answer TEXT,
    candidate_name TEXT,
    source_candidate_id TEXT,
    party TEXT,
    pct TEXT,
    ranked_choice_round TEXT,
    ranked_choice_reallocated TEXT,
    ranked_choice_final TEXT,
    response_kind TEXT NOT NULL,
    raw_option_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, question_key, option_index),
    FOREIGN KEY (snapshot_id, question_key)
      REFERENCES questions(snapshot_id, question_key)
);

CREATE TABLE IF NOT EXISTS approval_averages (
    snapshot_id TEXT NOT NULL,
    row_index INTEGER NOT NULL,
    topic TEXT NOT NULL,
    date TEXT NOT NULL,
    answer TEXT NOT NULL,
    pct TEXT NOT NULL,
    raw_row_json TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, row_index),
    FOREIGN KEY (snapshot_id) REFERENCES source_snapshots(snapshot_id)
);
"""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def payload_content_hash(files: dict[str, Any]) -> str:
    digest = hashlib.sha256()
    for name in sorted(files):
        digest.update(name.encode("utf-8"))
        digest.update(files[name]["sha256"].encode("ascii"))
    return digest.hexdigest()


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None:
            raise ValueError(f"Missing CSV header: {path}")
        return reader.fieldnames, list(reader)


def validate_snapshot(
    snapshot: Path, contract_path: Path = DEFAULT_SCHEMA_CONTRACT
) -> tuple[dict[str, Any], str, str]:
    """Verify manifest, payload hashes, feed set, and the exact schema contract."""
    manifest_path = snapshot / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    files = manifest.get("files", {})
    if set(files) != set(SOURCES):
        raise ValueError(f"Snapshot feed set differs from adapter: {sorted(files)}")

    expected = load_schema_contract(contract_path)
    for name in SOURCES:
        csv_path = snapshot / f"{name}.csv"
        actual_sha = file_sha256(csv_path)
        if actual_sha != files[name].get("sha256"):
            raise ValueError(f"Checksum mismatch for {csv_path}")
        header, rows = read_rows(csv_path)
        assert_expected_schema(name, header, expected[name])
        if len(rows) != files[name].get("rows"):
            raise ValueError(f"Row-count mismatch for {csv_path}")

    content_hash = payload_content_hash(files)
    recorded = manifest.get("content_sha256")
    if recorded is not None and recorded != content_hash:
        raise ValueError("Manifest content_sha256 does not match its file records")
    return manifest, hashlib.sha256(manifest_bytes).hexdigest(), content_hash


def poll_projection(row: dict[str, str]) -> dict[str, str]:
    keys = (
        "poll_id",
        "pollster_id",
        "pollster",
        "sponsor_ids",
        "sponsors",
        "display_name",
        "pollster_rating_id",
        "pollster_rating_name",
        "numeric_grade",
        "pollscore",
        "methodology",
        "transparency_score",
        "start_date",
        "end_date",
        "tracking",
        "created_at",
        "url",
        "url_article",
        "url_topline",
        "url_crosstab",
        "source",
        "internal",
    )
    return {key: row.get(key, "") for key in keys}


def question_projection(row: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in row.items() if key not in OPTION_COLUMNS}


def distinct_projection(
    rows: Iterable[dict[str, str]], projector: Any, description: str
) -> dict[str, str]:
    values = {canonical_json(projector(row)): projector(row) for row in rows}
    if len(values) != 1:
        raise ValueError(f"Conflicting metadata within {description}")
    return next(iter(values.values()))


def response_kind(row: dict[str, str]) -> str:
    # NYT gives stable IDs and candidate_name values to response buckets such as
    # "Don't know" and "Someone else".  Party=NONE is the reliable discriminator;
    # checking candidate_id first incorrectly turns those buckets into candidates.
    if row.get("party") == "NONE":
        return "noncandidate_response"
    if row.get("candidate_id") or row.get("candidate_name"):
        return "candidate"
    if row.get("party") and row.get("party") != "NONE":
        return "party_or_unresolved_candidate"
    return "noncandidate_response"


def insert_poll(
    connection: sqlite3.Connection,
    snapshot_id: str,
    feed: str,
    poll_id: str,
    metadata: dict[str, str],
) -> None:
    connection.execute(
        """INSERT INTO polls VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            feed,
            poll_id,
            metadata.get("pollster"),
            metadata.get("pollster_id"),
            metadata.get("sponsors"),
            metadata.get("methodology"),
            metadata.get("start_date"),
            metadata.get("end_date"),
            metadata.get("created_at"),
            metadata.get("url"),
            canonical_json(metadata),
        ),
    )


def insert_question(
    connection: sqlite3.Connection,
    snapshot_id: str,
    feed: str,
    row: dict[str, str],
    raw_question: dict[str, str],
) -> str:
    question_key = f"{feed}:{row['question_id']}"
    connection.execute(
        """INSERT INTO questions VALUES (
        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            snapshot_id,
            question_key,
            feed,
            row["poll_id"],
            row["question_id"],
            row.get("state"),
            row.get("cycle"),
            row.get("office_type"),
            row.get("seat_name"),
            row.get("seat_number"),
            row.get("election_date"),
            row.get("stage"),
            row.get("sample_size"),
            row.get("population"),
            row.get("population_full"),
            row.get("hypothetical"),
            row.get("race_id"),
            row.get("created_at"),
            "snapshot_retrieval_time",
            canonical_json(raw_question),
        ),
    )
    return question_key


def ingest_race_feed(
    connection: sqlite3.Connection, snapshot_id: str, feed: str, rows: list[dict[str, str]]
) -> None:
    by_poll: dict[str, list[dict[str, str]]] = defaultdict(list)
    by_question: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_poll[row["poll_id"]].append(row)
        by_question[(row["poll_id"], row["question_id"])].append(row)

    for poll_id, poll_rows in by_poll.items():
        metadata = distinct_projection(
            poll_rows, poll_projection, f"{feed} poll {poll_id}"
        )
        insert_poll(connection, snapshot_id, feed, poll_id, metadata)

    for (poll_id, question_id), question_rows in by_question.items():
        raw_question = distinct_projection(
            question_rows,
            question_projection,
            f"{feed} question {poll_id}/{question_id}",
        )
        question_key = insert_question(
            connection, snapshot_id, feed, question_rows[0], raw_question
        )
        for index, row in enumerate(question_rows):
            raw_option = {key: row.get(key, "") for key in OPTION_COLUMNS}
            connection.execute(
                """INSERT INTO poll_options VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    question_key,
                    index,
                    row.get("answer"),
                    row.get("candidate_name"),
                    row.get("candidate_id"),
                    row.get("party"),
                    row.get("pct"),
                    row.get("ranked_choice_round"),
                    row.get("ranked_choice_reallocated"),
                    row.get("ranked_choice_final"),
                    response_kind(row),
                    canonical_json(raw_option),
                ),
            )


def ingest_approval_polls(
    connection: sqlite3.Connection, snapshot_id: str, rows: list[dict[str, str]]
) -> None:
    feed = "president_approval_polls"
    by_poll: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_poll[row["poll_id"]].append(row)
    for poll_id, poll_rows in by_poll.items():
        metadata = distinct_projection(
            poll_rows, poll_projection, f"approval poll {poll_id}"
        )
        insert_poll(connection, snapshot_id, feed, poll_id, metadata)

    for row in rows:
        raw_question = dict(row)
        question_key = insert_question(connection, snapshot_id, feed, row, raw_question)
        options = [("yes", row.get("yes", "")), ("no", row.get("no", ""))]
        if row.get("alternate_answers", "") != "":
            options.append(("alternate_answers", row["alternate_answers"]))
        for index, (answer, pct) in enumerate(options):
            raw_option = {"answer": answer, "pct": pct}
            connection.execute(
                """INSERT INTO poll_options VALUES (
                ?, ?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL, NULL, ?, ?)""",
                (
                    snapshot_id,
                    question_key,
                    index,
                    answer,
                    pct,
                    "approval_response",
                    canonical_json(raw_option),
                ),
            )


def ingest_snapshot(
    snapshot: Path,
    database: Path,
    contract_path: Path = DEFAULT_SCHEMA_CONTRACT,
) -> dict[str, Any]:
    manifest, manifest_hash, content_hash = validate_snapshot(snapshot, contract_path)
    retrieved = manifest["retrieved_at_utc"]
    snapshot_id = f"nyt:{retrieved}:{manifest_hash[:16]}"
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database)
    try:
        connection.executescript(SCHEMA_SQL)
        existing = connection.execute(
            "SELECT snapshot_id FROM source_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        if existing:
            return {"status": "already_ingested", "snapshot_id": snapshot_id}

        with connection:
            connection.execute(
                """INSERT INTO source_snapshots (
                snapshot_id, source, retrieved_at_utc, raw_path, content_sha256,
                manifest_sha256, schema_contract_sha256, permission_record,
                adapter_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    manifest.get("source", "New York Times polling downloads"),
                    retrieved,
                    str(snapshot.resolve()),
                    content_hash,
                    manifest_hash,
                    hashlib.sha256(contract_path.read_bytes()).hexdigest(),
                    manifest.get(
                        "permission_record", "data/reference/source_permissions_2026.json"
                    ),
                    manifest.get("adapter_version", "legacy-stage0"),
                ),
            )
            for feed in RACE_FEEDS:
                _, rows = read_rows(snapshot / f"{feed}.csv")
                ingest_race_feed(connection, snapshot_id, feed, rows)
            _, approval_rows = read_rows(snapshot / "president_approval_polls.csv")
            ingest_approval_polls(connection, snapshot_id, approval_rows)
            _, average_rows = read_rows(snapshot / "president_approval_averages.csv")
            for index, row in enumerate(average_rows):
                connection.execute(
                    "INSERT INTO approval_averages VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        snapshot_id,
                        index,
                        row["topic"],
                        row["date"],
                        row["answer"],
                        row["pct"],
                        canonical_json(row),
                    ),
                )

        counts = {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE snapshot_id = ?", (snapshot_id,)
            ).fetchone()[0]
            for table in ("polls", "questions", "poll_options", "approval_averages")
        }
        return {"status": "ingested", "snapshot_id": snapshot_id, "counts": counts}
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument(
        "--database", type=Path, default=Path("data/processed/stage1.sqlite")
    )
    parser.add_argument(
        "--schema-contract", type=Path, default=DEFAULT_SCHEMA_CONTRACT
    )
    args = parser.parse_args()
    result = ingest_snapshot(args.snapshot, args.database, args.schema_contract)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
