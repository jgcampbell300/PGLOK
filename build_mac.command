#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PY_BIN="python3"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python"
fi

if [[ -f ".venv/bin/activate" ]]; then
  # Prefer project virtualenv if present.
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

"$PY_BIN" -m pip install --upgrade pip
"$PY_BIN" -m pip install -r requirements.txt pyinstaller
"$PY_BIN" -m PyInstaller --clean --noconfirm scripts/pyinstaller/pglok.spec

echo
echo "Build complete: dist/PGLOK"
