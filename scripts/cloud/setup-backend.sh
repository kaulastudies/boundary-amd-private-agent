#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORKSPACE_ROOT="${BOUNDARY_WORKSPACE_ROOT:-/workspace}"
APP_VENV="${BOUNDARY_BACKEND_VENV:-${WORKSPACE_ROOT}/venvs/boundary-backend}"
PYTHON_BOOTSTRAP="${BOUNDARY_SYSTEM_PYTHON:-$(command -v python3 || true)}"

if [[ "${APP_VENV}" == /opt/venv || "${APP_VENV}" == /opt/venv/* ]]; then
  printf 'ERROR: refusing to create or modify the bundled /opt/venv environment.\n' >&2
  exit 1
fi
if [[ -z "${PYTHON_BOOTSTRAP}" || ! -x "${PYTHON_BOOTSTRAP}" ]]; then
  printf 'ERROR: python3 is required to create the application environment. Nothing was installed.\n' >&2
  exit 1
fi
if [[ ! -f "${REPO_ROOT}/backend/pyproject.toml" ]]; then
  printf 'ERROR: backend/pyproject.toml was not found under %s.\n' "${REPO_ROOT}" >&2
  exit 1
fi

mkdir -p "$(dirname "${APP_VENV}")"
if [[ ! -x "${APP_VENV}/bin/python" ]]; then
  "${PYTHON_BOOTSTRAP}" -m venv "${APP_VENV}"
fi

"${APP_VENV}/bin/python" -m pip install --disable-pip-version-check -e "${REPO_ROOT}/backend[dev]"
printf 'BOUNDARY backend environment ready: %s\n' "${APP_VENV}"
printf 'Bundled inference environment left unchanged: /opt/venv\n'
