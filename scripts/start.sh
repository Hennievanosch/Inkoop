#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f frontend/dist/index.html ]]; then
  echo 'De interface ontbreekt. Voer eerst bash scripts/install.sh uit.' >&2
  exit 1
fi
exec .venv/bin/python -m uvicorn backend.app:app --host "${TVE_HOST:-0.0.0.0}" --port "${TVE_PORT:-8000}"
