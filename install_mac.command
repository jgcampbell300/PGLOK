#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -f ".venv/bin/activate" ]]; then
  # Prefer project venv when available.
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

PY_BIN="python3"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python"
fi

"$PY_BIN" -m pip install --upgrade pip
"$PY_BIN" -m pip install -r requirements.txt

echo "Dependencies installed."
