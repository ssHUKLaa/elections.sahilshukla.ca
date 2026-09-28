"""Validate and map archived 538 race polls for historical cutoff scoring."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from modeling import stage4_poll_model as stage4

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/historical_wayback/20241129"
MANIFEST = ROOT / "data/reference/stage6_wayback_manifest.json"


def load(races: list[Any]) -> tuple[list[stage4.PollQuestion], dict[str, Any]]:
    manifest_path = MANIFEST
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    races_by_id = {race.source_race_id: race for race in races}
    output = []
    counts = Counter()
    by_file = {}
    for filename, spec in manifest["files"].items():
        path = SOURCE / filename
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual_hash != spec["sha256"]:
            raise RuntimeError(f"Archived polling file hash changed: {filename}")
        office = filename.split("_polls")[0]
        grouped = defaultdict(list)
        with path.open(newline="", encoding="utf-8-sig") as stream:
            for row in csv.DictReader(stream):
                race_for_stage = races_by_id.get(row.get("race_id"))
                louisiana_open_general = (row.get("stage") == "jungle primary" and office == "house"
                                          and race_for_stage is not None and race_for_stage.state == "LA")
                if row.get("stage") != "general" and not louisiana_open_general:
                    counts["non_general"] += 1
                    continue
                try:
                    cycle = int(row["cycle"])
                except (ValueError, TypeError):
                    counts["invalid_cycle"] += 1
                    continue
                if cycle not in spec["cycle_use"]:
                    counts["outside_cycle_use"] += 1
                    continue
                grouped[(row.get("race_id"), row.get("question_id"))].append(row)
        accepted = 0
        for (race_id, question_id), rows in grouped.items():
            race = races_by_id.get(race_id)
            if race is None or race.office != office or race.cycle != int(rows[0]["cycle"]):
                counts["unmatched_race"] += 1
                continue
            if rows[0].get("hypothetical", "").lower() == "true":
                counts["hypothetical"] += 1
                continue
            if rows[0].get("ranked_choice_reallocated", "").lower() == "true":
                counts["ranked_choice_reallocated"] += 1
                continue
            try:
                election = stage4.parse_date(rows[0]["election_date"])
                ended = stage4.parse_date(rows[0]["end_date"])
                # Creation time has an unverified timezone. First full day
                # after its calendar date is a conservative availability date.
                available = stage4.parse_date(rows[0]["created_at"]) + timedelta(days=1)
            except (ValueError, TypeError):
                counts["invalid_date"] += 1
                continue
            candidates = {c.candidate_key: c for c in race.candidates}
            options = []
            ambiguous = False
            for row in rows:
                candidate_id = row.get("candidate_id") or None
                if candidate_id and candidate_id not in candidates:
                    ambiguous = True
                    break
                try:
                    pct = float(row.get("pct") or 0)
                except ValueError:
                    ambiguous = True
                    break
                options.append(stage4.PollOption(
                    candidate_key=candidate_id,
                    party_group=candidates[candidate_id].group if candidate_id else None,
                    pct=pct, response_kind="candidate" if candidate_id else "response",
                    label=row.get("candidate_name") or row.get("answer") or "",
                ))
            if ambiguous:
                counts["unmapped_candidate_or_pct"] += 1
                continue
            mapped_ids = [option.candidate_key for option in options if option.candidate_key]
            if len(mapped_ids) != len(set(mapped_ids)):
                counts["duplicate_candidate_option"] += 1
                continue
            if len({option.candidate_key for option in options if option.candidate_key and option.pct > 0}) < 2:
                counts["insufficient_contrast"] += 1
                continue
            first = rows[0]
            output.append(stage4.PollQuestion(
                question_key=f"wayback:{filename}:{question_id}",
                poll_id=f"wayback:{first['poll_id']}", race_key=race_id, office=office,
                pollster=first.get("pollster") or "unknown",
                population=first.get("population") or "unknown",
                methodology=first.get("methodology") or "unknown",
                sponsor=first.get("sponsors") or "",
                partisan=first.get("partisan") or "",
                internal=first.get("internal") or "",
                sample_size=float(first.get("sample_size") or 600),
                election_date=election, end_date=ended,
                available_date=available, options=tuple(options),
            ))
            accepted += 1
        by_file[filename] = {"general_questions_in_used_cycles": len(grouped),
                             "accepted_questions_before_deduplication": accepted,
                             "sha256": actual_hash}
    deduped = stage4.deduplicate_questions(output)
    return deduped, {
        "source_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "raw_questions_accepted": len(output), "deduplicated_questions": len(deduped),
        "files": by_file, "exclusions": dict(counts),
        "availability_rule": "created_at calendar date plus one full day",
    }
