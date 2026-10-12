#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
CACHE_DIR="${TVE_CACHE_DIR:-$PWD/.cache}"
python3 -m venv .venv
.venv/bin/python -m pip install --cache-dir "$CACHE_DIR/pip" -r requirements.txt
npm --prefix frontend ci --cache "$CACHE_DIR/npm" --no-audit --no-fund
npm --prefix frontend run build
# Seed only a missing database; never replace existing suppliers or account settings.
.venv/bin/python -c 'from backend.app import initialize; initialize()'
