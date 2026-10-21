#!/usr/bin/env bash
# ==============================================================================
# Antigravity Swarm Coordinator Setup & Restore Script (macOS & Linux)
# ==============================================================================
# Usage:
#   chmod +x install.sh && ./install.sh --clean-skills
#   ./install.sh --target-repo ~/Projects/MyProject --clean-skills
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_PY="${SCRIPT_DIR}/install.py"

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: python3 is required to run the Antigravity Swarm Coordinator installer." >&2
    exit 1
fi

echo "=========================================================="
echo "   Antigravity Swarm Coordinator Setup (macOS / Linux)    "
echo "=========================================================="

"${PYTHON_BIN}" "${INSTALL_PY}" "$@"

echo "=========================================================="
echo " Setup complete! Swarm Coordinator + 200 skills ready.    "
echo "=========================================================="
