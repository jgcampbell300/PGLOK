#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Building PGLOK Windows Executable on Linux via Wine ==="

# ---- Configuration ----
PYTHON_VERSION="3.12.9"
PYTHON_INSTALLER="python-${PYTHON_VERSION}-amd64.exe"
PYTHON_URL="https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_INSTALLER}"
WIN_PYTHON="C:\\Python312\\python.exe"
LOCAL_PYTHON_DIR="$HOME/.wine/drive_c/Python312"

# ---- 1. Install Windows Python under Wine if not present ----
if [ ! -f "$LOCAL_PYTHON_DIR/python.exe" ]; then
    echo "--> Downloading Windows Python ${PYTHON_VERSION}..."
    wget -q -O "/tmp/${PYTHON_INSTALLER}" "${PYTHON_URL}"
    
    echo "--> Installing Windows Python under Wine (silent install)..."
    wine "/tmp/${PYTHON_INSTALLER}" /quiet InstallAllUsers=0 PrependPath=1 TargetDir="C:\\Python312" \
        Include_launcher=0 Include_test=0 Include_dev=1 Include_pip=1 || true
    rm -f "/tmp/${PYTHON_INSTALLER}"
    
    sleep 2
    
    if [ ! -f "$LOCAL_PYTHON_DIR/python.exe" ]; then
        echo "ERROR: Python did not install correctly under Wine"
        echo "Trying alternative install method..."
        wine "/tmp/${PYTHON_INSTALLER}" /passive TargetDir="C:\\Python312" || true
    fi
fi

if [ ! -f "$LOCAL_PYTHON_DIR/python.exe" ]; then
    echo "ERROR: Windows Python not found at $LOCAL_PYTHON_DIR/python.exe"
    echo "Please install Windows Python under Wine manually."
    exit 1
fi

echo "--> Windows Python found at Wine C:\\Python312"

# ---- 2. Upgrade pip and install deps ----
echo "--> Upgrading pip..."
wine "${WIN_PYTHON}" -m pip install --upgrade pip

echo "--> Installing dependencies + PyInstaller..."
wine "${WIN_PYTHON}" -m pip install -r requirements.txt pyinstaller

# ---- 3. Run PyInstaller ----
echo "--> Building Windows executable..."
wine "${WIN_PYTHON}" -m PyInstaller --clean --noconfirm scripts/pyinstaller/pglok.spec

# ---- 4. Verify ----
if [ -f "dist/PGLOK.exe" ]; then
    echo ""
    echo "=== SUCCESS ==="
    echo "Windows executable created at: $(pwd)/dist/PGLOK.exe"
    ls -lh "dist/PGLOK.exe"
else
    echo ""
    echo "=== FAILED ==="
    echo "dist/PGLOK.exe was not found after build."
    echo "Check the PyInstaller output above for errors."
    exit 1
fi
