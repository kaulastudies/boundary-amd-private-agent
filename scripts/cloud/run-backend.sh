#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT=/workspace
APP_VENV=/workspace/venvs/boundary-backend
PORT="${BOUNDARY_PORT:-8080}"

if [[ ! -x "${APP_VENV}/bin/python" ]]; then
  printf 'ERROR: backend environment missing at %s. Run scripts/cloud/setup-backend.sh first.\n' "${APP_VENV}" >&2
  exit 1
fi
if [[ ! "${PORT}" =~ ^[0-9]+$ ]] || (( PORT < 1 || PORT > 65535 )); then
  printf 'ERROR: BOUNDARY_PORT must be an integer from 1 to 65535.\n' >&2
  exit 1
fi

export BOUNDARY_MODEL_BASE_URL="${BOUNDARY_MODEL_BASE_URL:-http://127.0.0.1:8000/v1}"
export BOUNDARY_MODEL_NAME="${BOUNDARY_MODEL_NAME:-boundary-qwen3-8b}"
export BOUNDARY_MODEL_TIMEOUT_SECONDS="${BOUNDARY_MODEL_TIMEOUT_SECONDS:-30}"
export BOUNDARY_DATABASE_PATH="${BOUNDARY_DATABASE_PATH:-${WORKSPACE_ROOT}/boundary-data/boundary.db}"
export BOUNDARY_EMBEDDING_MODEL="${BOUNDARY_EMBEDDING_MODEL:-sentence-transformers/all-MiniLM-L6-v2}"
export BOUNDARY_EMBEDDING_DEVICE="${BOUNDARY_EMBEDDING_DEVICE:-cpu}"
export BOUNDARY_RAG_INDEX_PATH="${BOUNDARY_RAG_INDEX_PATH:-${WORKSPACE_ROOT}/boundary-data/rag/boundary.faiss}"
export HF_HOME="${HF_HOME:-${WORKSPACE_ROOT}/cache/huggingface}"
export HUGGINGFACE_HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-${HF_HOME}/hub}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
exec "${APP_VENV}/bin/python" -m uvicorn boundary_backend.main:app \
  --app-dir "${REPO_ROOT}/backend/src" \
  --host 0.0.0.0 \
  --port "${PORT}"
