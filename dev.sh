#!/usr/bin/env bash
# Run API + UI locally (one process). From repo root:
#   ./dev.sh
# Optional:
#   DEV_PORT=8001 ./dev.sh
#   ./dev.sh --port 8001
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
else
  PY="${PYTHON:-python3}"
fi

exec "$PY" "$ROOT/scripts/dev.py" "$@"
