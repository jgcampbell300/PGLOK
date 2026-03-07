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

if ! "$PY_BIN" scripts/check_env.py; then
  echo
  read -r -p "Dependencies are missing. Install now? (Y/N): " REPLY
  case "${REPLY:-N}" in
    [Yy]*)
      ./install_mac.command
      "$PY_BIN" scripts/check_env.py
      ;;
    *)
      echo "Startup cancelled."
      exit 1
      ;;
  esac
fi

exec "$PY_BIN" -m src.pglok
