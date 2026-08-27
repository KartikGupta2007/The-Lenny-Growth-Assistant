#!/usr/bin/env bash
# Start the backend and frontend together. Ctrl-C stops both.
#
#   ./scripts/dev.sh
#
# Expects the one-time setup in README.md: a backend virtualenv, npm install,
# and backend/.env.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -x backend/.venv/bin/python ]; then
  echo "backend/.venv is missing — see 'Setup' in README.md" >&2
  exit 1
fi
if [ ! -f backend/.env ]; then
  echo "backend/.env is missing — cp backend/.env.example backend/.env" >&2
  exit 1
fi
if [ ! -d frontend/node_modules ]; then
  echo "frontend/node_modules is missing — cd frontend && npm install" >&2
  exit 1
fi

trap 'kill 0' EXIT INT TERM

(cd backend && .venv/bin/python -m uvicorn app.main:app --reload --port 8000) &
(cd frontend && npm run dev) &

echo
echo "  backend   http://localhost:8000  (docs at /docs)"
echo "  frontend  http://localhost:5173"
echo "  Ctrl-C stops both."
echo
wait
