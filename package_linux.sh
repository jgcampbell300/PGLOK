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

echo "📦 Creating PGLOK distribution package for version $VERSION..."

# Check if executable exists
if [[ ! -f "dist/PGLOK" ]]; then
    echo "❌ Executable not found. Please run ./build_linux.sh first."
    exit 1
fi

# Check if icon exists
if [[ ! -f "icon.png" ]]; then
    echo "❌ Icon not found. Please run python3 create_icon.py first."
    exit 1
fi

# Create package directory
LINUX_PACKAGE_NAME="PGLOK-Linux-v${VERSION}"
PACKAGE_DIR="$LINUX_PACKAGE_NAME"

rm -rf "$PACKAGE_DIR"
mkdir -p "$PACKAGE_DIR"

# Copy files
echo "📋 Copying files..."
cp dist/PGLOK "$PACKAGE_DIR/"
cp icon.png "$PACKAGE_DIR/"
cp README.md "$PACKAGE_DIR/"
cp LICENSE "$PACKAGE_DIR/"

# Create installation script
cat > "$PACKAGE_DIR/install.sh" << 'EOF'
#!/bin/bash
set -euo pipefail

echo "🔧 Installing PGLOK..."

# Install to user's local bin
INSTALL_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"

# Copy executable
cp PGLOK "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR/PGLOK"

# Copy icon
ICON_DIR="$HOME/.local/share/icons"
mkdir -p "$ICON_DIR"
cp icon.png "$ICON_DIR/pglok.png"

# Create desktop entry
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

cat > "$DESKTOP_DIR/pglok.desktop" << DESKTOP
[Desktop Entry]
Version=1.0
Type=Application
Name=PGLOK
Comment=Project Gorgon Locator and Data Tools
Exec=$INSTALL_DIR/PGLOK
Icon=$ICON_DIR/pglok.png
Terminal=false
Categories=Game;Utility;
StartupNotify=true
DESKTOP

echo "✅ Installation complete!"
echo "🚀 You can now run PGLOK from your application menu or by typing 'PGLOK' in terminal."
EOF

chmod +x "$PACKAGE_DIR/install.sh"

# Create tar.gz package
echo "🗜️  Creating package..."
mkdir -p dist
tar -czf "dist/${LINUX_PACKAGE_NAME}.tar.gz" "$PACKAGE_DIR"

# Create source package
echo "🗜️  Creating source package..."
SOURCE_ARCHIVE="dist/PGLOK-v${VERSION}-source.tar.gz"
git archive --format=tar.gz --prefix="PGLOK-v${VERSION}-source/" HEAD > "$SOURCE_ARCHIVE"

# Cleanup
rm -rf "$PACKAGE_DIR"

echo ""
echo "✅ Package created: dist/${LINUX_PACKAGE_NAME}.tar.gz"
echo "✅ Source package created: $SOURCE_ARCHIVE"
echo "📦 Size (binary package): $(du -h "dist/${LINUX_PACKAGE_NAME}.tar.gz" | cut -f1)"
echo ""
echo "To install:"
echo "  tar -xzf dist/${LINUX_PACKAGE_NAME}.tar.gz"
echo "  cd ${LINUX_PACKAGE_NAME}"
echo "  ./install.sh"
