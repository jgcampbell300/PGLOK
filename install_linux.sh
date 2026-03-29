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

# Check if we need a virtual environment (for externally managed Python)
NEED_VENV=false
if ! "$PY_BIN" -m pip install --dry-run pip 2>/dev/null; then
    echo "📝 System Python is externally managed, creating virtual environment..."
    NEED_VENV=true
fi

if [[ "$NEED_VENV" == true ]] && [[ ! -f ".venv/bin/activate" ]]; then
    echo "📦 Creating virtual environment..."
    "$PY_BIN" -m venv .venv
fi

if [[ -f ".venv/bin/activate" ]]; then
    # Use project venv
    echo "📦 Using virtual environment..."
    # shellcheck disable=SC1091
    source ".venv/bin/activate"
    PY_BIN="python"
fi

echo "📦 Installing Python dependencies..."
if [[ -f ".venv/bin/activate" ]]; then
    "$PY_BIN" -m pip install --upgrade pip
    "$PY_BIN" -m pip install -r requirements.txt
else
    # Try with --break-system-packages as fallback
    "$PY_BIN" -m pip install --upgrade pip --break-system-packages 2>/dev/null || "$PY_BIN" -m pip install --upgrade pip
    "$PY_BIN" -m pip install -r requirements.txt --break-system-packages 2>/dev/null || "$PY_BIN" -m pip install -r requirements.txt
fi

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
    
    # Check if icon exists
    ICON_PATH="$(pwd)/icon.png"
    if [[ ! -f "$ICON_PATH" ]]; then
        echo "⚠️  Icon not found at $ICON_PATH"
        ICON_PATH=""
    fi
    
    cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PGLOK
Comment=Project Gorgon Locator and Data Tools
Exec=$(pwd)/start_linux.sh
${ICON_PATH:+Icon=$ICON_PATH}
Terminal=false
Categories=Game;Utility;
StartupNotify=true
EOF
    
    echo "✅ Desktop entry created at $DESKTOP_FILE"
    echo "   You can now launch PGLOK from your application menu."
    
    # Also create desktop entry for the executable if it exists
    if [[ -f "$(pwd)/dist/PGLOK" ]]; then
        EXE_DESKTOP_FILE="$DESKTOP_DIR/pglok-exe.desktop"
        cat > "$EXE_DESKTOP_FILE" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=PGLOK (Executable)
Comment=Project Gorgon Locator and Data Tools - Standalone
Exec=$(pwd)/dist/PGLOK
${ICON_PATH:+Icon=$ICON_PATH}
Terminal=false
Categories=Game;Utility;
StartupNotify=true
EOF
        echo "✅ Executable desktop entry created at $EXE_DESKTOP_FILE"
    fi
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
