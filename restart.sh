#!/usr/bin/env bash
# Fresh restart: stop whatever is on DEV_PORT, clear stale env, start API + UI.
# From repo root:
#   ./restart.sh
# Optional:
#   DEV_PORT=8001 ./restart.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

exec "$PY" "$ROOT/scripts/dev.py" restart "$@"
