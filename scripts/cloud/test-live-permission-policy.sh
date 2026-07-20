#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARTIFACT_ROOT="${BOUNDARY_ARTIFACT_ROOT:-/workspace/boundary-artifacts}"
SOURCE_ARTIFACT="${ARTIFACT_ROOT}/debug/agent-plan-validation.txt"
POLICY_ARTIFACT="${ARTIFACT_ROOT}/debug/permission-policy-validation.txt"

bash "${SCRIPT_DIR}/test-live-plan.sh"

python3 - "${SOURCE_ARTIFACT}" "${POLICY_ARTIFACT}" <<'PY'
import json
import pathlib
import sys
from datetime import datetime, timezone

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
values = {}
for line in source.read_text(encoding="utf-8").splitlines():
    if "=" in line:
        key, value = line.split("=", 1)
        values[key] = value

required_passes = {
    "vllm_health": "passed",
    "backend_health": "passed",
    "model_health": "passed",
    "plan_schema": "passed",
    "approval_policy": "passed",
    "external_actions_executed": "false",
}
for key, expected in required_passes.items():
    if values.get(key) != expected:
        raise SystemExit(f"live permission policy check failed: {key}")

plan = json.loads(values["plan"])
actions = {step["action_type"] for step in plan["steps"]}
required_actions = {
    "draft_local", "send_external", "schedule_external"
}
if not required_actions.issubset(actions):
    raise SystemExit("live permission policy plan omitted required action types")
if not ({"inspect_local", "analyze_local"} & actions):
    raise SystemExit("live permission policy plan omitted local review")
if not ({"delete_local", "overwrite_local"} & actions):
    raise SystemExit("live permission policy plan omitted destructive deletion")

destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(
    "BOUNDARY live permission policy validation\n"
    f"timestamp_utc={datetime.now(timezone.utc).isoformat()}\n"
    "semantic_policy=passed\n"
    "approval_policy=passed\n"
    "planning_only=passed\n"
    "external_actions_executed=false\n",
    encoding="utf-8",
)
print(f"Live permission policy test passed. Result saved to {destination}")
PY
