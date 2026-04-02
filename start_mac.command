#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -x ".venv/bin/python" ]]; then
  PY_BIN="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "build_env/bin/python" ]]; then
  PY_BIN="$SCRIPT_DIR/build_env/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY_BIN="python3"
else
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
