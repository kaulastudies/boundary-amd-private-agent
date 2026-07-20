#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for script in "${SCRIPT_DIR}"/*.sh; do
  [[ "${script}" == "${BASH_SOURCE[0]}" ]] && continue
  bash -n "${script}"
done

if grep -Eiq '(pip install|apt(-get)? install|dnf install|yum install)' "${SCRIPT_DIR}/verify-rocm.sh" "${SCRIPT_DIR}/check-vllm.sh" "${SCRIPT_DIR}/test-live-plan.sh" "${SCRIPT_DIR}/test-live-permission-policy.sh"; then
  printf 'ERROR: verification scripts must not install packages.\n' >&2
  exit 1
fi
if grep -Eiq '(pip install|apt(-get)? install|dnf install|yum install|vllm serve|huggingface-cli)' "${SCRIPT_DIR}/test-live-approval-flow.sh" "${SCRIPT_DIR}/test-live-audit-chain.sh"; then
  printf 'ERROR: workflow live tests must not install packages, launch vLLM, or download models.\n' >&2
  exit 1
fi
if ! grep -q 'shutil.copy2(primary, copied)' "${SCRIPT_DIR}/test-live-audit-chain.sh"; then
  printf 'ERROR: audit tamper test must operate on an isolated database copy.\n' >&2
  exit 1
fi
if grep -Eiq '(authorization:|api[_ -]?key|vllm serve|huggingface-cli)' "${SCRIPT_DIR}/test-live-plan.sh" "${SCRIPT_DIR}/test-live-permission-policy.sh"; then
  printf 'ERROR: live plan test must not use credentials, launch vLLM, or download models.\n' >&2
  exit 1
fi
if ! grep -q 'refusing to create or modify the bundled /opt/venv' "${SCRIPT_DIR}/setup-backend.sh"; then
  printf 'ERROR: setup-backend.sh must protect /opt/venv.\n' >&2
  exit 1
fi
if grep -Eq 'pip install.*(torch|vllm|rocm)' "${SCRIPT_DIR}/setup-backend.sh"; then
  printf 'ERROR: backend setup must not install the supplied GPU stack.\n' >&2
  exit 1
fi
if ! grep -q 'BOUNDARY_MODEL_BASE_URL' "${SCRIPT_DIR}/run-backend.sh"; then
  printf 'ERROR: run-backend.sh must configure the local model endpoint.\n' >&2
  exit 1
fi
if grep -Eq '(NEXT_PUBLIC_BACKEND|https?://[^ ]*(openai|anthropic|google))' "${SCRIPT_DIR}/run-frontend.sh"; then
  printf 'ERROR: frontend launcher must use only the server-side local backend proxy.\n' >&2
  exit 1
fi
if grep -Eiq '(npm install|pnpm install|yarn install)' "${SCRIPT_DIR}/run-frontend.sh"; then
  printf 'ERROR: frontend runtime launcher must not install packages.\n' >&2
  exit 1
fi
printf 'Cloud script syntax and safety checks passed.\n'
