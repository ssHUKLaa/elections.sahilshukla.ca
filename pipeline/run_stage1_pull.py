"""Run one local Stage 1 pull and ingest it into the replay database."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> None:
    print("Running:", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-historical", action="store_true")
    parser.add_argument(
        "--database", type=Path, default=Path("data/processed/stage1.sqlite")
    )
    args = parser.parse_args()
    python = sys.executable
    run([python, "pipeline/snapshot_nyt_polls.py"])
    complete = sorted(
        path
        for path in Path("data/raw/nyt").iterdir()
        if path.is_dir() and not path.name.endswith(".incomplete")
    )
    if not complete:
        raise RuntimeError("NYT pull completed without a snapshot directory")
    run(
        [
            python,
            "pipeline/ingest_nyt_snapshot.py",
            str(complete[-1]),
            "--database",
            str(args.database),
        ]
    )
    if args.include_historical:
        run([python, "pipeline/snapshot_historical_sources.py"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
