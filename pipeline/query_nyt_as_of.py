"""Export the last complete NYT poll snapshot available by an UTC cutoff."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def parse_utc(value: str) -> datetime:
    if value.endswith("Z") and "T" in value and "-" not in value[:10]:
        parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ")
        return parsed.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("as-of timestamp must include UTC or an explicit offset")
    return parsed.astimezone(timezone.utc)


def export_as_of(
    database: Path, as_of: str, output: Path, feeds: list[str] | None = None
) -> dict[str, object]:
    cutoff = parse_utc(as_of)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        snapshots = connection.execute(
            "SELECT * FROM source_snapshots ORDER BY retrieved_at_utc, snapshot_id"
        ).fetchall()
        eligible = [
            row for row in snapshots if parse_utc(row["retrieved_at_utc"]) <= cutoff
        ]
        if not eligible:
            raise ValueError(f"No complete source snapshot exists by {cutoff.isoformat()}")
        snapshot = eligible[-1]
        parameters: list[str] = [snapshot["snapshot_id"]]
        where = "snapshot_id = ?"
        if feeds:
            placeholders = ",".join("?" for _ in feeds)
            where += f" AND feed IN ({placeholders})"
            parameters.extend(feeds)

        question_rows = connection.execute(
            f"SELECT * FROM questions WHERE {where} ORDER BY feed, question_key",
            parameters,
        ).fetchall()
        questions: list[dict[str, object]] = []
        for question_row in question_rows:
            question = dict(question_row)
            question.pop("snapshot_id")
            question["raw_question"] = json.loads(question.pop("raw_question_json"))
            option_rows = connection.execute(
                """SELECT * FROM poll_options
                WHERE snapshot_id = ? AND question_key = ? ORDER BY option_index""",
                (snapshot["snapshot_id"], question["question_key"]),
            ).fetchall()
            options = []
            for option_row in option_rows:
                option = dict(option_row)
                option.pop("snapshot_id")
                option.pop("question_key")
                option["raw_option"] = json.loads(option.pop("raw_option_json"))
                options.append(option)
            question["options"] = options
            questions.append(question)

        result: dict[str, object] = {
            "as_of_utc": cutoff.isoformat().replace("+00:00", "Z"),
            "selection_rule": "latest complete source snapshot retrieved at or before as_of_utc",
            "source_snapshot": dict(snapshot),
            "question_count": len(questions),
            "option_count": sum(len(q["options"]) for q in questions),
            "questions": questions,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return {
            "output": str(output),
            "snapshot_id": snapshot["snapshot_id"],
            "question_count": result["question_count"],
            "option_count": result["option_count"],
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/processed/stage1.sqlite"))
    parser.add_argument("--as-of", required=True, help="UTC or offset ISO-8601 cutoff")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--feed", action="append", dest="feeds")
    args = parser.parse_args()
    print(json.dumps(export_as_of(args.database, args.as_of, args.output, args.feeds), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
