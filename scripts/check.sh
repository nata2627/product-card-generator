#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python

"$PY" -m ruff check card_generator tests scripts
"$PY" -m ruff format --check card_generator tests scripts
"$PY" -m pytest -q
"$PY" scripts/check_private.py
echo "check: ok"
