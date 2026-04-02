#!/usr/bin/env bash
set -euo pipefail

TAG="v0.2.0"
TITLE="PGLOK v0.2.0"
LINUX_ASSET="PGLOK-Linux-v0.2.0.tar.gz"
SOURCE_ASSET="PGLOK-v0.2.0-source.tar.gz"

echo "Creating $TITLE"

test -f "dist/$LINUX_ASSET"
test -f "dist/$SOURCE_ASSET"
test -f RELEASE_NOTES.md

gh release create "$TAG" \
  "dist/$LINUX_ASSET" \
  "dist/$SOURCE_ASSET" \
  --title "$TITLE" \
  --notes-file RELEASE_NOTES.md
