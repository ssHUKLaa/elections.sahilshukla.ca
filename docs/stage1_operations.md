# Stage 1 data operations

## Commands

Run a NYT pull and ingest it into the replay database:

```bash
python pipeline/run_stage1_pull.py
```

Add `--include-historical` for a less frequent refresh of the historical poll and election-result catalog. Raw files go under ignored, timestamped directories in `data/raw/`. Normalized NYT versions go into the ignored `data/processed/stage1.sqlite` database.

Export the last complete source view known by a cutoff:

```bash
python pipeline/query_nyt_as_of.py \
  --as-of 2026-09-21T02:00:00Z \
  --feed senate \
  --output data/processed/senate-as-of.json
```

Run the acceptance gate:

```bash
python pipeline/validate_stage1.py
```

## Scheduling on the production Ubuntu ARM host

Production uses the systemd units in `ops/systemd/`. Install the repository at `/opt/us2026forecast`, create a dedicated `forecast` service account, and create its virtual environment at `/opt/us2026forecast/.venv`. The service and timer files do not depend on x86 binaries and use the Python environment installed on the ARM host.

Install the units as root, then enable both timers:

```bash
sudo cp ops/systemd/us2026-data-pull.service /etc/systemd/system/
sudo cp ops/systemd/us2026-data-pull.timer /etc/systemd/system/
sudo cp ops/systemd/us2026-historical-pull.service /etc/systemd/system/
sudo cp ops/systemd/us2026-historical-pull.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now us2026-data-pull.timer us2026-historical-pull.timer
systemctl list-timers 'us2026-*'
```

The live feed runs daily. The larger historical refresh runs weekly. `Persistent=true` runs a missed job after an instance reboot, while `RandomizedDelaySec` avoids requiring an exact upstream publication minute.

The task must stop on a nonzero exit code and retain the last valid database. A failed or schema-drifted download stays in a timestamped `.incomplete` directory for diagnosis and is never ingested.

## Cutoff semantics

An as-of export selects the most recent **complete snapshot retrieval time** at or before the requested cutoff. This is deliberately conservative. The NYT `created_at` field is retained as source metadata, but it is not treated as poll publication time: the upstream field describes creation in the source database and does not supply a sufficiently documented timezone/publication guarantee. A historical replay therefore never uses a row from a source snapshot first retrieved after its cutoff.

Every database question carries `availability_basis = snapshot_retrieval_time`. A future source adapter may use a verified publication timestamp, but it must be versioned and tested before replacing this rule.

## Retention and publication

Keep raw snapshots immutable and preserve their manifests. The NYT permission record is `data/reference/source_permissions_2026.json`; confirm the external correspondence before redistributing raw rows. Public model artifacts should contain derived forecasts and source attribution rather than a copy of the raw feed unless that correspondence expressly permits redistribution.
