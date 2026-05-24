#!/usr/bin/env bash
set -e

if [ ! -d ".venv" ]; then
    echo "[ERROR] Virtual environment not found. Run ./setup.sh first."
    exit 1
fi

source .venv/bin/activate
python -m hawarma.tui