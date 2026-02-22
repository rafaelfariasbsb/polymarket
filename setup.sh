#!/usr/bin/env bash
# Polymarket Scalp Radar v2 - Setup Script

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Polymarket Scalp Radar v2 - Setup ==="
echo ""

# Check Python version
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PY_VERSION)"
    exit 1
fi
echo "[OK] Python $PY_VERSION"

# Create virtual environment
if [ ! -d "venv" ]; then
    echo ""
    echo "Creating virtual environment..."
    python3 -m venv venv
    echo "[OK] Virtual environment created"
else
    echo "[OK] Virtual environment exists"
fi

# Activate and install dependencies
echo ""
echo "Installing dependencies..."
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "[OK] Dependencies installed"

# Setup .env
if [ ! -f ".env" ]; then
    echo ""
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo "[!!] Created .env from .env.example"
        echo "     Edit .env and add your POLYMARKET_API_KEY before running."
    else
        echo "[!!] No .env file found. Create one with your POLYMARKET_API_KEY."
    fi
else
    echo "[OK] .env exists"
fi

# Verify imports
echo ""
echo "Verifying imports..."
if source venv/bin/activate && python3 -c "
from dotenv import load_dotenv
from py_clob_client.client import ClobClient
from web3 import Web3
from eth_account import Account
import requests
" 2>/dev/null; then
    echo "[OK] All imports working"
else
    echo "[!!] Some imports failed. Try: source venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Usage:"
echo "  source venv/bin/activate"
echo "  python radar_scalp.py          # default \$4 trades"
echo "  python radar_scalp.py 10       # \$10 trades"
echo ""
