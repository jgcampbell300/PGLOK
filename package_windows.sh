#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY_BIN="python3"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python"
fi

VERSION="$("$PY_BIN" -c 'import src; print(src.__version__)')"

if [[ -z "$VERSION" ]]; then
  echo "❌ Could not determine PGLOK version from src.__version__"
  exit 1
fi

echo "📦 Creating PGLOK Windows distribution package for version $VERSION..."

if [[ ! -f "dist/PGLOK.exe" ]]; then
    echo "❌ Windows executable not found. Run build_windows_via_wine.sh first."
    exit 1
fi

WINDOWS_PACKAGE_NAME="PGLOK-Windows-v${VERSION}"
PACKAGE_DIR="$WINDOWS_PACKAGE_NAME"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

echo "📋 Copying files..."
cp dist/PGLOK.exe "$PACKAGE_DIR/"
cp icon.ico "$PACKAGE_DIR/"
cp icon.png "$PACKAGE_DIR/"
cp README.md "$PACKAGE_DIR/"
cp LICENSE "$PACKAGE_DIR/"
cp install_windows.bat "$PACKAGE_DIR/"

echo "🗜️  Creating ZIP package..."
mkdir -p dist
if command -v 7z &>/dev/null; then
  7z a "dist/${WINDOWS_PACKAGE_NAME}.zip" "$PACKAGE_DIR/"
elif command -v zip &>/dev/null; then
  zip -r "dist/${WINDOWS_PACKAGE_NAME}.zip" "$PACKAGE_DIR/"
else
  echo "❌ No ZIP tool found (install zip or 7z)"
  rm -rf "$PACKAGE_DIR"
  exit 1
fi

rm -rf "$PACKAGE_DIR"

echo ""
echo "✅ Package created: dist/${WINDOWS_PACKAGE_NAME}.zip"
echo "📦 Size: $(du -h "dist/${WINDOWS_PACKAGE_NAME}.zip" | cut -f1)"
