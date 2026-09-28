#!/usr/bin/env bash
set -Eeuo pipefail

# Run on the OCI Ubuntu host as the ubuntu user. Output goes to journald and
# /var/log/us2026-deploy.log when invoked with: sudo bash ops/deploy_ubuntu.sh
repo_url=https://github.com/ssHUKLaa/elections.sahilshukla.ca.git
app_dir=/opt/us2026forecast
old_db=/home/ubuntu/USA-2024-Prediction-Model/polling_data.db
nginx_site=/etc/nginx/sites-available/elections
deploy_source=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

if [[ "$(id -u)" != 0 ]]; then
  echo 'Run this script with sudo.' >&2
  exit 1
fi

exec > >(tee -a /var/log/us2026-deploy.log) 2>&1
echo "Deployment started at $(date -u +%FT%TZ)"

if ! id forecast >/dev/null 2>&1; then
  useradd --system --home-dir "$app_dir" --shell /usr/sbin/nologin forecast
fi
install -d -o forecast -g forecast -m 0755 "$app_dir"
if [[ ! -d "$app_dir/.git" ]]; then
  if [[ -n "$(ls -A "$app_dir")" ]]; then
    echo "Refusing to clone into nonempty $app_dir" >&2
    exit 1
  fi
  runuser -u forecast -- git clone "$repo_url" "$app_dir"
fi

cd "$app_dir"
if [[ -n "$(runuser -u forecast -- git status --porcelain)" ]]; then
  echo 'Refusing to update a modified server checkout.' >&2
  exit 1
fi
runuser -u forecast -- git fetch origin
runuser -u forecast -- git merge --ff-only origin/main

if [[ ! -x .venv/bin/python ]]; then
  runuser -u forecast -- python3 -m venv .venv
fi
runuser -u forecast -- env PIP_NO_CACHE_DIR=1 .venv/bin/python -m pip install -r requirements.txt -r requirements-stage4.txt

# Stage 3 reads this small Census gazetteer at model runtime. It is deliberately
# excluded from Git because it is a downloaded source, so restore it by hash.
runuser -u forecast -- .venv/bin/python - <<'PY'
import hashlib
import json
import urllib.request
from pathlib import Path

source = json.loads(Path('data/reference/races_2026.json').read_text())['sources']['census_cd120']
target = Path(source['path'])
if not str(target).startswith('data/raw/reference/'):
    raise ValueError('Unexpected Census source path')
if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != source['sha256']:
    with urllib.request.urlopen(source['url'], timeout=60) as response:
        payload = response.read()
    if hashlib.sha256(payload).hexdigest() != source['sha256']:
        raise ValueError('Census reference checksum mismatch')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
PY
runuser -u forecast -- .venv/bin/python -c 'from modeling.national_environment import verify_sources; verify_sources()'

if [[ ! -f polling_data.db ]]; then
  install -o forecast -g forecast -m 0640 "$old_db" polling_data.db
fi

install -d -o forecast -g forecast -m 0755 data/raw data/processed artifacts
install -m 0644 "$deploy_source/us2026-web.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable us2026-web.service
systemctl restart us2026-web.service

ready=0
for attempt in {1..30}; do
  if curl --fail --silent --max-time 30 http://127.0.0.1:8000/us2026 >/dev/null; then
    ready=1
    break
  fi
  sleep 2
done
if [[ "$ready" != 1 ]]; then
  systemctl status us2026-web.service --no-pager || true
  journalctl -u us2026-web.service -n 60 --no-pager || true
  echo 'Web smoke check failed; Nginx was not changed.' >&2
  exit 1
fi

if grep -Fq 'root /home/ubuntu/USA-2024-Prediction-Model;' "$nginx_site"; then
  cp -a "$nginx_site" "${nginx_site}.pre-us2026"
  python3 - "$nginx_site" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
old = 'root /home/ubuntu/USA-2024-Prediction-Model;'
assert text.count(old) == 1
path.write_text(text.replace(old, 'alias /opt/us2026forecast/static/;').replace('autoindex on;', 'autoindex off;'))
PY
  if nginx -t; then
    systemctl reload nginx
  else
    cp -a "${nginx_site}.pre-us2026" "$nginx_site"
    echo 'Nginx test failed; previous site configuration restored.' >&2
    exit 1
  fi
fi

curl --fail --silent --show-error --max-time 30 -o /dev/null https://elections.sahilshukla.ca/us2026
echo "Deployment complete at $(date -u +%FT%TZ), commit $(runuser -u forecast -- git rev-parse --short HEAD)"
