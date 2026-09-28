"""Snapshot selected official 2026 state candidate lists for manual extraction.

This is a growing source catalog. Downloaded documents are evidence, not automatically
accepted ballot entries. Keep raw bytes and hashes for every review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import requests


SOURCES = {
    "CA_general_certified.pdf": "https://elections.cdn.sos.ca.gov/statewide-elections/2026-general/cert-list-candidates.pdf",
    "MD_general_statewide.csv": "https://elections.maryland.gov/elections/2026/general_candidates/2026_GG_statewide_candidatelist.csv",
    "MD_general_governor.csv": "https://elections.maryland.gov/elections/2026/general_candidates/2026_GG_governorlt.governor_candidatelist.csv",
    "NC_candidate_listing.csv": "https://s3.amazonaws.com/dl.ncsbe.gov/Elections/2026/Candidate%20Filing/Candidate_Listing_2026.csv",
    "ME_general_candidates.xlsx": "https://www.maine.gov/sos/sites/maine.gov.sos/files/inline-files/2026%20General%20Candidate%20List%20-%20FINAL.xlsx",
    "TX_general_certified.pdf": "https://www.sos.state.tx.us/elections/forms/2026-ballot-cert.pdf",
    "WA_general_certified.pdf": "https://www.sos.wa.gov/sites/default/files/2026-08/2026%20Certification%20of%20Candidates%20to%20General%20Election.pdf",
    "AL_general_democratic_certified.pdf": "https://www.sos.alabama.gov/sites/default/files/election-2026/2026GeneralElectionStateCertificationofDemocraticCandidates.pdf",
    "AL_general_republican_certified.pdf": "https://www.sos.alabama.gov/sites/default/files/election-2026/2026GeneralElectionStateCertificationofRepublicanCandidates.pdf",
    "AL_general_independent_certified.pdf": "https://www.sos.alabama.gov/sites/default/files/election-2026/2026GeneralElection-StateCertificationofIndependentCandidate.pdf",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("data/raw/state_ballots"))
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    basename = started.strftime("%Y%m%dT%H%M%SZ")
    staging = args.output_root / f"{basename}.incomplete"
    destination = args.output_root / basename
    if staging.exists() or destination.exists():
        raise FileExistsError(destination)
    staging.mkdir(parents=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "us2026forecast-ballot-inventory/0.1", "Accept-Encoding": "identity"})
    manifest = {"retrieved_at_utc": started.isoformat(), "files": {}}
    for name, url in SOURCES.items():
        response = session.get(url, timeout=120)
        response.raise_for_status()
        data = response.content
        if len(data) < 100 or data.lstrip().lower().startswith(b"<html"):
            raise ValueError(f"Unexpected response for {name}")
        (staging / name).write_bytes(data)
        manifest["files"][name] = {
            "url": url,
            "final_url": response.url,
            "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
            "content_type": response.headers.get("Content-Type"),
            "last_modified": response.headers.get("Last-Modified"),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
        print(f"{name}: {len(data):,} bytes")
    (staging / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    staging.replace(destination)
    print(f"Saved {destination}")


if __name__ == "__main__":
    main()
