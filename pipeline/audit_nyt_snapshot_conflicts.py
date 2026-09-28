"""Report NYT poll-level fields that vary between questions in one poll."""

from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path

from ingest_nyt_snapshot import poll_projection


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot", type=Path)
    args = parser.parse_args()
    for feed in ("senate", "house", "governor", "other"):
        with (args.snapshot / f"{feed}.csv").open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        by_poll = defaultdict(list)
        for row in rows:
            by_poll[row["poll_id"]].append(poll_projection(row))
        changed = Counter()
        examples = []
        for poll_id, records in by_poll.items():
            differing = [key for key in records[0] if len({record[key] for record in records}) > 1]
            if differing:
                changed.update(differing)
                examples.append((poll_id, differing))
        print(feed, "conflicting polls", len(examples), "fields", dict(changed),
              "examples", examples[:8])


if __name__ == "__main__":
    main()
