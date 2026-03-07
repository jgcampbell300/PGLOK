#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔧 PGLOK Installation Script for Linux"
echo "====================================="

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null && ! command -v python &> /dev/null; then
    echo "❌ Python is not installed. Please install Python 3.8 or higher."
    echo "   On Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "   On Fedora: sudo dnf install python3 python3-pip"
    echo "   On Arch: sudo pacman -S python python-pip"
    exit 1
fi

PY_BIN="python3"
if ! command -v "$PY_BIN" >/dev/null 2>&1; then
  PY_BIN="python"
fi

# Check Python version
PYTHON_VERSION=$("$PY_BIN" -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
echo "✅ Found Python $PYTHON_VERSION"

if "$PY_BIN" -c 'import sys; exit(0 if sys.version_info >= (3, 8) else 1)'; then
    echo "✅ Python version is compatible (3.8+)"
else
    echo "❌ Python 3.8 or higher is required. Current version: $PYTHON_VERSION"
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null && ! "$PY_BIN" -m pip --version &> /dev/null; then
    echo "❌ pip is not installed. Please install pip:"
    echo "   On Ubuntu/Debian: sudo apt install python3-pip"
    echo "   On Fedora: sudo dnf install python3-pip"
    echo "   On Arch: sudo pacman -S python-pip"
    exit 1
fi

echo "✅ pip is available"

if [[ -f ".venv/bin/activate" ]]; then
  # Prefer project venv when available.
  echo "📦 Using existing virtual environment..."
  # shellcheck disable=SC1091
  source ".venv/bin/activate"
fi

echo "📦 Installing Python dependencies..."
"$PY_BIN" -m pip install --upgrade pip
"$PY_BIN" -m pip install -r requirements.txt

echo "✅ Dependencies installed successfully"

# Make start script executable
chmod +x start_linux.sh
echo "✅ Made start_linux.sh executable"

# Create desktop entry (optional)
if [[ "${1:-}" == "--desktop" ]] || [[ "${1:-}" == "-d" ]]; then
    echo "🖥️  Creating desktop entry..."
    
    DESKTOP_DIR="$HOME/.local/share/applications"
    DESKTOP_FILE="$DESKTOP_DIR/pglok.desktop"
    
    mkdir -p "$DESKTOP_DIR"
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PGLOK
Comment=Project Gorgon Locator and Data Tools
Exec=$(pwd)/start_linux.sh
Icon=$(pwd)/icon.png
Terminal=false
Categories=Game;Utility;
EOF
    
    echo "✅ Desktop entry created at $DESKTOP_FILE"
    echo "   You can now launch PGLOK from your application menu."
fi

echo ""
echo "🎉 Installation completed successfully!"
echo ""
echo "To run PGLOK:"
echo "  ./start_linux.sh"
echo ""
echo "For desktop integration (optional):"
echo "  ./install_linux.sh --desktop"
echo ""
echo "For more information, see README.md"
