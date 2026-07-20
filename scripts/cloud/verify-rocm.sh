#!/usr/bin/env bash
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPORT_DIR="${BOUNDARY_ENV_REPORT_DIR:-${REPO_ROOT}/benchmarks/environment}"
REPORT_FILE="${REPORT_DIR}/radeon-cloud-$(date -u +%Y%m%dT%H%M%SZ).txt"
EXPECTED_ROCM_VERSION="${EXPECTED_ROCM_VERSION:-7.2.1}"
EXPECTED_GPU_ARCH="${EXPECTED_GPU_ARCH:-gfx1100}"
errors=0

mkdir -p "${REPORT_DIR}"
exec > >(tee "${REPORT_FILE}") 2>&1

fail() {
  printf 'ERROR: %s\n' "$*"
  errors=$((errors + 1))
}

find_python() {
  local candidate
  for candidate in \
    "${BOUNDARY_BUNDLED_PYTHON:-}" \
    /opt/venv/bin/python \
    "${VIRTUAL_ENV:-}/bin/python" \
    "$(command -v python3 2>/dev/null || true)" \
    "$(command -v python 2>/dev/null || true)"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

printf 'BOUNDARY Radeon Cloud environment verification\n'
printf 'Timestamp (UTC): %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'Host: %s\n' "$(hostname)"
printf 'Repository: %s\n' "${REPO_ROOT}"
printf 'Expected ROCm: %s\n' "${EXPECTED_ROCM_VERSION}"
printf 'Expected GPU architecture: %s\n\n' "${EXPECTED_GPU_ARCH}"

if command -v rocm-smi >/dev/null 2>&1; then
  printf '%s\n' '--- rocm-smi ---'
  printf 'Path: %s\n' "$(command -v rocm-smi)"
  rocm-smi --showproductname --showmeminfo vram --showdriverversion --showuniqueid || fail 'rocm-smi could not query the GPU.'
else
  fail 'rocm-smi was not found on PATH. Use the supplied ROCm container; do not install ROCm from this script.'
fi

if command -v rocminfo >/dev/null 2>&1; then
  printf '%s\n' '--- rocminfo ---'
  printf 'Path: %s\n' "$(command -v rocminfo)"
  rocminfo_output="$(rocminfo 2>&1)" || fail 'rocminfo failed. Confirm that the container can access the GPU device.'
  printf '%s\n' "${rocminfo_output}" | awk '/Marketing Name:|Name: *gfx|Name: *AMD|Vendor Name:|Max Waves Per CU:/{print}'
  if ! grep -q "${EXPECTED_GPU_ARCH}" <<<"${rocminfo_output}"; then
    fail "Expected GPU architecture ${EXPECTED_GPU_ARCH} was not reported by rocminfo."
  fi
else
  fail 'rocminfo was not found on PATH. Use the supplied ROCm container; do not install ROCm from this script.'
fi

printf '%s\n' '--- ROCm version files ---'
rocm_version='unknown'
for version_file in /opt/rocm/.info/version /opt/rocm/.info/version-dev /opt/rocm/.info/version-utils; do
  if [[ -r "${version_file}" ]]; then
    printf '%s: %s\n' "${version_file}" "$(<"${version_file}")"
    [[ "${rocm_version}" == 'unknown' ]] && rocm_version="$(<"${version_file}")"
  fi
done
printf 'Detected ROCm version: %s\n' "${rocm_version}"
if [[ "${rocm_version}" != 'unknown' && "${rocm_version}" != "${EXPECTED_ROCM_VERSION}"* ]]; then
  fail "ROCm ${rocm_version} does not match expected ${EXPECTED_ROCM_VERSION}. Do not replace it; select the correct supplied image."
fi

python_bin="$(find_python)" || python_bin=''
if [[ -z "${python_bin}" ]]; then
  fail 'No existing Python environment was found. Expected /opt/venv/bin/python or another existing interpreter.'
else
  printf '%s\n' '--- bundled Python environment ---'
  printf 'Python: %s\n' "${python_bin}"
  "${python_bin}" --version || fail 'The selected Python interpreter could not run.'
  "${python_bin}" - <<'PY' || fail 'PyTorch or vLLM import/inspection failed in the bundled environment. Do not install them; verify the supplied image.'
import importlib

torch = importlib.import_module("torch")
vllm = importlib.import_module("vllm")

print(f"PyTorch version: {torch.__version__}")
print(f"PyTorch HIP version: {torch.version.hip or 'not reported'}")
print(f"vLLM version: {getattr(vllm, '__version__', 'unknown')}")
print(f"CUDA/HIP device available: {torch.cuda.is_available()}")
print(f"GPU count: {torch.cuda.device_count()}")
for index in range(torch.cuda.device_count()):
    properties = torch.cuda.get_device_properties(index)
    architecture = getattr(properties, "gcnArchName", "unknown")
    total_vram_gib = properties.total_memory / (1024 ** 3)
    print(f"GPU {index} name: {properties.name}")
    print(f"GPU {index} architecture: {architecture}")
    print(f"GPU {index} VRAM: {total_vram_gib:.2f} GiB")
PY
fi

printf '\nReport saved to: %s\n' "${REPORT_FILE}"
if (( errors > 0 )); then
  printf 'Verification failed with %d diagnostic error(s). No packages were installed or changed.\n' "${errors}"
  exit 1
fi
printf 'Verification passed. No packages were installed or changed.\n'
