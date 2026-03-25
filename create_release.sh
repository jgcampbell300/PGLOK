#!/usr/bin/env bash
set -euo pipefail

TAG="v0.1.8"
TITLE="PGLOK v0.1.8"
LINUX_ASSET="PGLOK-Linux-v0.1.8.tar.gz"
SOURCE_ASSET="PGLOK-v0.1.8-source.tar.gz"

echo "Creating $TITLE"

test -f "$LINUX_ASSET"
test -f "$SOURCE_ASSET"
test -f RELEASE_NOTES.md

gh release create "$TAG" \
  "$LINUX_ASSET" \
  "$SOURCE_ASSET" \
  --title "$TITLE" \
  --notes-file RELEASE_NOTES.md
