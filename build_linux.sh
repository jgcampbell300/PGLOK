#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

echo "🔧 Building PGLOK executable for Linux..."

# Install dependencies with user flag to avoid system package conflicts
"$PY_BIN" -m pip install --break-system-packages --upgrade pip
"$PY_BIN" -m pip install --break-system-packages pyinstaller

# Build the executable
"$PY_BIN" -m PyInstaller --clean --noconfirm scripts/pyinstaller/pglok.spec

echo
echo "✅ Build complete: dist/PGLOK"
echo "📦 Executable created at: $(pwd)/dist/PGLOK"
echo ""
echo "To run the executable:"
echo "  ./dist/PGLOK"
echo ""
echo "To install system-wide (optional):"
echo "  sudo cp dist/PGLOK /usr/local/bin/"
