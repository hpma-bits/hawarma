#!/usr/bin/env bash
set -e

echo "============================================"
echo "  Hawarma - Cooking Game Automation Agent"
echo "  Setup Script"
echo "============================================"
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "[ERROR] Python not found"
        echo "Please install Python 3.10+: https://www.python.org/downloads/"
        exit 1
    fi
    PYTHON=python
else
    PYTHON=python3
fi

echo "[OK] Python found: $($PYTHON --version)"

# Create venv
echo "[1/4] Creating virtual environment..."
if [ ! -d ".venv" ]; then
    $PYTHON -m venv .venv
fi
echo "[OK] Virtual environment ready"

# Install uv
echo "[2/4] Checking uv package manager..."
if ! command -v uv &> /dev/null; then
    echo "Installing uv..."
    pip install uv 2>/dev/null || $PYTHON -m pip install uv
fi
echo "[OK] uv ready"

# Install dependencies
echo "[3/4] Installing dependencies..."
source .venv/bin/activate
uv pip install -e . 2>&1 || pip install -e .
echo "[OK] Dependencies installed"

# Check config
echo "[4/4] Checking config..."
if [ ! -f "configs/config.yaml" ]; then
    echo "[WARN] Config file not found: configs/config.yaml"
    echo "Make sure you run this script from the project root directory"
else
    echo "[OK] Config file ready"
fi

echo ""
echo "============================================"
echo "  Setup complete!"
echo ""
echo "  To start:"
echo "    ./run.sh"
echo "    or: python -m hawarma"
echo "============================================"