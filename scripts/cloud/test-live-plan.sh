#!/usr/bin/env bash
set -euo pipefail

VLLM_BASE_URL="${BOUNDARY_MODEL_BASE_URL:-http://127.0.0.1:8000/v1}"
BACKEND_BASE_URL="${BOUNDARY_BACKEND_BASE_URL:-http://127.0.0.1:8080}"
MODEL_NAME="${BOUNDARY_MODEL_NAME:-boundary-qwen3-8b}"
ARTIFACT_ROOT="${BOUNDARY_ARTIFACT_ROOT:-/workspace/boundary-artifacts}"
ARTIFACT_FILE="${ARTIFACT_ROOT}/debug/agent-plan-validation.txt"
TEMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf -- "${TEMP_DIR}"
}
trap cleanup EXIT

mkdir -p "$(dirname "${ARTIFACT_FILE}")"

curl --fail --silent --show-error \
  "${VLLM_BASE_URL}/models" > "${TEMP_DIR}/vllm-models.json"
curl --fail --silent --show-error \
  "${BACKEND_BASE_URL}/health" > "${TEMP_DIR}/backend-health.json"
curl --fail --silent --show-error \
  "${BACKEND_BASE_URL}/model/health" > "${TEMP_DIR}/model-health.json"
curl --fail --silent --show-error \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"task":"Inspect the local BOUNDARY repository and propose safe next steps."}' \
  "${BACKEND_BASE_URL}/agent/plan" > "${TEMP_DIR}/agent-plan.json"

python3 - \
  "${TEMP_DIR}/vllm-models.json" \
  "${TEMP_DIR}/backend-health.json" \
  "${TEMP_DIR}/model-health.json" \
  "${TEMP_DIR}/agent-plan.json" \
  "${ARTIFACT_FILE}" \
  "${MODEL_NAME}" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

vllm_path, backend_path, model_path, plan_path, artifact_path, expected_model = sys.argv[1:]

def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)

vllm = read_json(vllm_path)
backend = read_json(backend_path)
model = read_json(model_path)
plan = read_json(plan_path)

model_ids = {
    item.get("id") for item in vllm.get("data", []) if isinstance(item, dict)
}
if expected_model not in model_ids:
    raise SystemExit("vLLM does not advertise the configured model")
if backend.get("status") != "ok":
    raise SystemExit("backend health response is not healthy")
if model != {
    "model_name": expected_model,
    "available": True,
    "local_only": True,
}:
    raise SystemExit("backend model health response is invalid")

allowed_risks = {"safe", "review", "sensitive", "destructive", "blocked"}
protected_risks = {"sensitive", "destructive", "blocked"}
if not isinstance(plan, dict) or set(plan) != {"steps"}:
    raise SystemExit("plan must contain exactly one steps field")
if not isinstance(plan["steps"], list) or not plan["steps"]:
    raise SystemExit("plan steps must be a non-empty list")
for index, step in enumerate(plan["steps"]):
    if not isinstance(step, dict) or set(step) != {
        "id", "title", "description", "risk_level", "requires_approval"
    }:
        raise SystemExit(f"step {index} fields are invalid")
    for field in ("id", "title", "description"):
        if not isinstance(step[field], str) or not step[field].strip():
            raise SystemExit(f"step {index} {field} must be a non-empty string")
    if step["risk_level"] not in allowed_risks:
        raise SystemExit(f"step {index} risk level is invalid")
    if not isinstance(step["requires_approval"], bool):
        raise SystemExit(f"step {index} requires_approval must be boolean")
    if step["risk_level"] in protected_risks and not step["requires_approval"]:
        raise SystemExit(f"step {index} weakens the backend approval policy")

artifact = pathlib.Path(artifact_path)
artifact.write_text(
    "BOUNDARY live plan validation\n"
    f"timestamp_utc={datetime.now(timezone.utc).isoformat()}\n"
    "vllm_health=passed\n"
    "backend_health=passed\n"
    "model_health=passed\n"
    "plan_schema=passed\n"
    "approval_policy=passed\n"
    f"model_name={expected_model}\n"
    f"plan={json.dumps(plan, separators=(',', ':'))}\n",
    encoding="utf-8",
)
print(f"Live planning smoke test passed. Result saved to {artifact}")
PY
