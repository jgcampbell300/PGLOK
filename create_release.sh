#!/usr/bin/env bash
set -euo pipefail

TAG="v0.1.9"
TITLE="PGLOK v0.1.9"
LINUX_ASSET="PGLOK-Linux-v0.1.9.tar.gz"
SOURCE_ASSET="PGLOK-v0.1.9-source.tar.gz"

echo "Creating $TITLE"

test -f "dist/$LINUX_ASSET"
test -f "dist/$SOURCE_ASSET"
test -f RELEASE_NOTES.md

gh release create "$TAG" \
  "dist/$LINUX_ASSET" \
  "dist/$SOURCE_ASSET" \
  --title "$TITLE" \
  --notes-file RELEASE_NOTES.md
