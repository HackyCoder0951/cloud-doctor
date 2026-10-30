#!/usr/bin/env bash
# Stop the sandbox. With --volumes also removes metric/log/database state (clean reset between experiment runs).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT/infra"
ARGS=()
[[ "${1:-}" == "--volumes" ]] && ARGS=(--volumes)
docker compose --env-file .env -f compose.yaml --profile logs down "${ARGS[@]}"
