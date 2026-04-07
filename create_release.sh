#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY_BIN="python3"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python"
fi

VERSION="$("$PY_BIN" - << 'EOF'
import src
print(src.__version__)
EOF
)"

if [[ -z "$VERSION" ]]; then
  echo "❌ Could not determine PGLOK version from src.__version__"
  exit 1
fi

TAG="v${VERSION}"
TITLE="PGLOK v${VERSION}"
LINUX_ASSET="PGLOK-Linux-v${VERSION}.tar.gz"
SOURCE_ASSET="PGLOK-v${VERSION}-source.tar.gz"

echo "Creating release $TITLE (tag: $TAG)"
echo "Using assets:"
echo "  dist/$LINUX_ASSET"
echo "  dist/$SOURCE_ASSET"

test -f "dist/$LINUX_ASSET"
test -f "dist/$SOURCE_ASSET"
test -f RELEASE_NOTES.md

gh release create "$TAG" \
  "dist/$LINUX_ASSET" \
  "dist/$SOURCE_ASSET" \
  --title "$TITLE" \
  --notes-file RELEASE_NOTES.md
