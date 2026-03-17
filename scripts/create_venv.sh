#!/usr/bin/env bash
set -euo pipefail

# Creates a reproducible venv at ./build_env and installs requirements.txt if present.
# Run: bash scripts/create_venv.sh

PROJ_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJ_ROOT"

if [ -d build_env ]; then
  echo "Removing existing build_env"
  rm -rf build_env
fi

# Try standard venv creation
if python3 -m venv build_env; then
  echo "Created venv with python3 -m venv"
else
  echo "python3 -m venv failed; attempting to use virtualenv"
  if python3 -m pip --version >/dev/null 2>&1; then
    python3 -m pip install --user virtualenv
    python3 -m virtualenv build_env
  else
    echo "pip not available to install virtualenv; aborting"
    exit 2
  fi
fi

PY="$PWD/build_env/bin/python"
PIP="$PWD/build_env/bin/pip"

if [ ! -x "$PY" ]; then
  echo "Venv python not found at $PY"
  exit 3
fi

# Ensure pip is available
if ! "$PY" -m pip --version >/dev/null 2>&1; then
  echo "Installing pip via get-pip.py"
  curl -sS https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py || wget -q -O /tmp/get-pip.py https://bootstrap.pypa.io/get-pip.py
  "$PY" /tmp/get-pip.py --disable-pip-version-check
fi

# Upgrade packaging tools
"$PIP" install --upgrade pip setuptools wheel

# Install requirements if present
if [ -f requirements.txt ]; then
  echo "Installing requirements.txt"
  "$PIP" install -r requirements.txt
else
  echo "No requirements.txt found"
fi

echo "Done. Activate with: source build_env/bin/activate"
