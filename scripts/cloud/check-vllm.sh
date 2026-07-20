#!/usr/bin/env bash
set -uo pipefail

errors=0
python_bin=''
for candidate in "${BOUNDARY_BUNDLED_PYTHON:-}" /opt/venv/bin/python "${VIRTUAL_ENV:-}/bin/python" "$(command -v python3 2>/dev/null || true)"; do
  if [[ -n "${candidate}" && -x "${candidate}" ]]; then
    python_bin="${candidate}"
    break
  fi
done

if [[ -x /opt/venv/bin/vllm ]]; then
  vllm_command=/opt/venv/bin/vllm
elif command -v vllm >/dev/null 2>&1; then
  vllm_command="$(command -v vllm)"
else
  printf 'ERROR: the vllm command was not found in /opt/venv/bin or PATH.\n' >&2
  errors=$((errors + 1))
  vllm_command=''
fi

if [[ -n "${vllm_command}" ]]; then
  printf 'vLLM command: %s\n' "${vllm_command}"
  "${vllm_command}" --version || {
    printf 'ERROR: vllm --version failed. No model was launched.\n' >&2
    errors=$((errors + 1))
  }
fi

if [[ -z "${python_bin}" ]]; then
  printf 'ERROR: no existing bundled Python interpreter was found.\n' >&2
  errors=$((errors + 1))
else
  printf 'Python: %s\n' "${python_bin}"
  "${python_bin}" -c 'import vllm; print("vLLM Python package:", getattr(vllm, "__version__", "unknown"))' || {
    printf 'ERROR: the vLLM Python package could not be imported. No installation was attempted.\n' >&2
    errors=$((errors + 1))
  }
fi

if (( errors > 0 )); then
  printf 'vLLM availability check failed with %d error(s). No model was launched or downloaded.\n' "${errors}" >&2
  exit 1
fi
printf 'vLLM command and package are available. No model was launched or downloaded.\n'
