#!/usr/bin/env bash
# Clean up old release files, keeping only the latest versions

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🧹 Cleaning up old release files..."
echo ""

# Function to keep only latest N versions
keep_latest() {
    local pattern="$1"
    local keep_count="${2:-2}"
    
    # Get matching files sorted by modification time (newest first)
    local files=($(ls -t $pattern 2>/dev/null || true))
    
    if [[ ${#files[@]} -le $keep_count ]]; then
        return
    fi
    
    echo "📦 Keeping latest $keep_count of ${#files[@]} files matching '$pattern':"
    for ((i=0; i<$keep_count; i++)); do
        echo "   ✓ ${files[$i]}"
    done
    
    echo "   🗑️  Removing older files:"
    for ((i=$keep_count; i<${#files[@]}; i++)); do
        echo "      - ${files[$i]}"
        rm -f "${files[$i]}"
    done
    echo ""
}

# Keep only 2 latest Linux release packages
keep_latest "PGLOK-Linux-*.tar.gz" 2

# Keep only 2 latest source packages  
keep_latest "PGLOK-v*.tar.gz" 2

echo "✅ Cleanup complete!"
echo ""
echo "Remaining files:"
ls -lh *.tar.gz 2>/dev/null | awk '{print "  " $9, "(" $5 ")"}' || echo "  None"
