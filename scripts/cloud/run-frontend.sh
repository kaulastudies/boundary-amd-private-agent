#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND_PORT="${BOUNDARY_FRONTEND_PORT:-3000}"

if [[ ! "${FRONTEND_PORT}" =~ ^[0-9]+$ ]] || (( FRONTEND_PORT < 1 || FRONTEND_PORT > 65535 )); then
  printf 'ERROR: BOUNDARY_FRONTEND_PORT must be an integer from 1 to 65535.\n' >&2
  exit 1
fi
if [[ ! -d "${REPO_ROOT}/frontend/.next" ]]; then
  printf 'ERROR: frontend production build is missing. Prepare dependencies and run the frontend build first.\n' >&2
  exit 1
fi

export BOUNDARY_BACKEND_URL="${BOUNDARY_BACKEND_URL:-http://127.0.0.1:8080}"
export BOUNDARY_BACKEND_TIMEOUT_MS="${BOUNDARY_BACKEND_TIMEOUT_MS:-60000}"
cd "${REPO_ROOT}/frontend"
exec npm run start -- --hostname 0.0.0.0 --port "${FRONTEND_PORT}"
