#!/bin/bash

# PGLOK v0.1.4 Release Creation Script

echo "🚀 Creating PGLOK v0.1.4 Release"
echo "=================================="

# Set variables
REPO="jgcampbell300/PGLOK"
TAG="v0.1.4"
RELEASE_NAME="PGLOK v0.1.4"
RELEASE_NOTES_FILE="RELEASE_NOTES.md"

# Check if we have the required files
echo "📋 Checking release files..."
if [ ! -f "PGLOK-Linux-20260309.tar.gz" ]; then
    echo "❌ Linux package not found. Run ./package_clean.sh first."
    exit 1
fi

if [ ! -f "PGLOK-v0.1.4-source.tar.gz" ]; then
    echo "❌ Source package not found. Run git archive command first."
    exit 1
fi

if [ ! -f "$RELEASE_NOTES_FILE" ]; then
    echo "❌ Release notes not found."
    exit 1
fi

echo "✅ All release files found!"

# Read release notes
RELEASE_NOTES=$(cat "$RELEASE_NOTES_FILE")

echo ""
echo "📝 Release Notes Preview:"
echo "========================"
echo "$RELEASE_NOTES" | head -20
echo "... (truncated)"

echo ""
echo "🌐 Manual Release Creation Steps:"
echo "================================="
echo ""
echo "1. Go to: https://github.com/jgcampbell300/PGLOK/releases/new"
echo "2. Tag: v0.1.4"
echo "3. Target: main"
echo "4. Release title: PGLOK v0.1.4"
echo "5. Description: Copy content from RELEASE_NOTES.md"
echo "6. Attach these files:"
echo "   - PGLOK-Linux-20260309.tar.gz (58MB)"
echo "   - PGLOK-v0.1.4-source.tar.gz (286KB)"
echo "7. Click 'Publish release'"
echo ""

echo "🧪 Testing Auto-Update System:"
echo "=============================="

# Test the auto-update system with the current version
cd /home/jgcampbell300/PycharmProjects/PGLOK
python3 -c "
import sys
sys.path.insert(0, 'src')
from src.updater import fetch_latest_repo_version, parse_version_key

print('Testing auto-update system...')
print('Current: v0.1.4')

# This will fail until release is created
try:
    latest, assets = fetch_latest_repo_version()
    if latest:
        print(f'Latest available: {latest}')
        current_key = parse_version_key('v0.1.4')
        latest_key = parse_version_key(latest)
        
        if latest_key > current_key:
            print('✅ Update would be triggered')
        else:
            print('✅ Up to date')
    else:
        print('❌ No release found yet')
        print('👆 Create the GitHub release first!')
except Exception as e:
    print(f'❌ Error: {e}')
    print('👆 Create the GitHub release first!')
"

echo ""
echo "📦 Release Files Ready:"
echo "======================"
echo "✅ PGLOK-Linux-20260309.tar.gz ($(du -h PGLOK-Linux-20260309.tar.gz | cut -f1))"
echo "✅ PGLOK-v0.1.4-source.tar.gz ($(du -h PGLOK-v0.1.4-source.tar.gz | cut -f1))"
echo "✅ RELEASE_NOTES.md (ready to copy)"
echo ""
echo "🎯 Next Step: Create GitHub release at:"
echo "https://github.com/jgcampbell300/PGLOK/releases/new"
