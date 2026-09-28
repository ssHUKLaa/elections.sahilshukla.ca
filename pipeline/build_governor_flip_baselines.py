"""Export prior governor winners for 2026 map flip indicators."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GROUP = {'D': 'D', 'DEM': 'D', 'R': 'R', 'REP': 'R'}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=ROOT / 'data/processed/stage2.sqlite')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/reference/governor_seat_baselines_2026.json')
    args = parser.parse_args()
    with sqlite3.connect(args.database) as connection:
        rows = connection.execute(
            """SELECT r.race_id, r.state, f.prior_winner_party, f.baseline_cycle
               FROM races AS r JOIN race_fundamentals AS f USING (race_id)
               WHERE r.office = 'governor' ORDER BY r.state"""
        ).fetchall()
    if len(rows) != 36 or len({row[1] for row in rows}) != 36:
        raise ValueError('Expected 36 unique governor races')
    if any(row[2] not in GROUP for row in rows):
        raise ValueError('Unreviewed prior governor party')
    report = {
        'meaning': 'Party that won the previous comparable governor election; a flip changes from this group.',
        'stage2_database_sha256': hashlib.sha256(args.database.read_bytes()).hexdigest(),
        'seats': {race_id: {'state': state, 'prior_winner_party': party,
                            'prior_winner_group': GROUP[party], 'baseline_cycle': cycle}
                  for race_id, state, party, cycle in rows},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(f'Wrote {len(rows)} governor baselines to {args.output}')


if __name__ == '__main__':
    main()
