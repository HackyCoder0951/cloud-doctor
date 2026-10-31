#!/usr/bin/env bash
# Bring the sandbox up. Idempotent. Usage: infra/scripts/up.sh [--no-logs]
# Generates infra/.env (random database password, never printed, git-ignored) and the Prometheus config.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/infra"

if [[ ! -f .env ]]; then
  python3 - <<'EOF'
import secrets, os
fd = os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as fh:
    fh.write("APP_DB_PASSWORD=" + secrets.token_urlsafe(24) + "\n")
EOF
  echo "created infra/.env (mode 600)"
fi

python3 tools/gen_prometheus.py

PROFILES=(--profile logs)
[[ "${1:-}" == "--no-logs" ]] && PROFILES=()

docker compose --env-file .env -f compose.yaml "${PROFILES[@]}" up -d --build
echo "up. Prometheus: http://127.0.0.1:9090  api: http://127.0.0.1:18000/healthz"
