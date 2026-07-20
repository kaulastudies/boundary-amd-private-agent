#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for script in "${SCRIPT_DIR}"/*.sh; do
  [[ "${script}" == "${BASH_SOURCE[0]}" ]] && continue
  bash -n "${script}"
done

if grep -Eiq '(pip install|apt(-get)? install|dnf install|yum install)' "${SCRIPT_DIR}/verify-rocm.sh" "${SCRIPT_DIR}/check-vllm.sh"; then
  printf 'ERROR: verification scripts must not install packages.\n' >&2
  exit 1
fi
if ! grep -q 'refusing to create or modify the bundled /opt/venv' "${SCRIPT_DIR}/setup-backend.sh"; then
  printf 'ERROR: setup-backend.sh must protect /opt/venv.\n' >&2
  exit 1
fi
printf 'Cloud script syntax and safety checks passed.\n'
