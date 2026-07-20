#!/usr/bin/env bash
set -euo pipefail

VLLM_BASE_URL="${BOUNDARY_MODEL_BASE_URL:-http://127.0.0.1:8000/v1}"
BACKEND_BASE_URL="${BOUNDARY_BACKEND_BASE_URL:-http://127.0.0.1:8080}"
ARTIFACT_ROOT="${BOUNDARY_ARTIFACT_ROOT:-/workspace/boundary-artifacts}"
ARTIFACT_FILE="${ARTIFACT_ROOT}/debug/approval-flow-validation.txt"

mkdir -p "$(dirname "${ARTIFACT_FILE}")"

python3 - "${VLLM_BASE_URL}" "${BACKEND_BASE_URL}" "${ARTIFACT_FILE}" <<'PY'
import ipaddress
import json
import pathlib
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

vllm_base, backend_base, artifact_path = sys.argv[1:]

def require_local(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SystemExit("live test endpoint URL is invalid")
    if parsed.hostname != "localhost":
        address = ipaddress.ip_address(parsed.hostname)
        if not (address.is_loopback or address.is_private or address.is_link_local):
            raise SystemExit("live test refuses a non-local endpoint")

def request(method, url, payload=None, expected=200):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    call = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(call, timeout=120) as response:
            content = json.load(response)
            if response.status != expected:
                raise SystemExit(f"unexpected HTTP status {response.status} for {url}")
            return response.status, content
    except urllib.error.HTTPError as error:
        content = json.load(error)
        if error.code != expected:
            raise SystemExit(f"unexpected HTTP status {error.code} for {url}: {content}")
        return error.code, content

require_local(vllm_base)
require_local(backend_base)
request("GET", f"{vllm_base}/models")
_, backend_health = request("GET", f"{backend_base}/health")
if backend_health.get("status") != "ok":
    raise SystemExit("backend is not healthy")

task = (
    "Review a confidential contract, draft an email, send it, delete the original, "
    "and schedule a meeting."
)
_, run = request("POST", f"{backend_base}/runs", {"task": task}, expected=201)
run_id = run["run_id"]
steps = run["steps"]
required_fields = {
    "id", "title", "description", "action_type", "risk_level",
    "requires_approval", "policy_reason", "state", "approval_id", "tool_result"
}
for step in steps:
    if set(step) != required_fields or not step["policy_reason"]:
        raise SystemExit("run contains an invalid step schema")

by_action = {step["action_type"]: step for step in steps}
local_review = by_action.get("inspect_local") or by_action.get("analyze_local")
if not local_review or local_review["state"] != "ready":
    raise SystemExit("local review must be ready without approval")
if "draft_local" not in by_action or by_action["draft_local"]["state"] != "ready":
    raise SystemExit("draft_local must be ready without approval")
for action in ("send_external", "delete_local", "schedule_external"):
    if action not in by_action or by_action[action]["state"] != "awaiting_approval":
        raise SystemExit(f"{action} must await approval")

status, conflict = request(
    "POST", f"{backend_base}/runs/{run_id}/execute", {}, expected=409
)
if status != 409 or conflict.get("code") != "approval_required":
    raise SystemExit("execution before approval was not blocked")

_, approvals = request("GET", f"{backend_base}/approvals?run_id={run_id}")
approval_by_step = {item["step_id"]: item for item in approvals}
for step in steps:
    if step["state"] != "awaiting_approval":
        continue
    approval = approval_by_step.get(step["id"])
    if approval is None:
        raise SystemExit("pending step has no scoped approval request")
    endpoint = "reject" if step["action_type"] in {"delete_local", "overwrite_local"} else "approve"
    request(
        "POST",
        f"{backend_base}/approvals/{approval['approval_id']}/{endpoint}",
        {"actor": "radeon-live-test", "reason": "bounded simulated workflow test"},
    )

_, executed = request("POST", f"{backend_base}/runs/{run_id}/execute", {})
if executed["state"] != "completed":
    raise SystemExit("approved simulated run did not complete")
executed_by_action = {step["action_type"]: step for step in executed["steps"]}
executed_local_action = local_review["action_type"]
for action in (executed_local_action, "draft_local", "send_external", "schedule_external"):
    step = executed_by_action[action]
    result = step.get("tool_result")
    if step["state"] != "executed" or not result:
        raise SystemExit(f"{action} did not produce a simulated result")
    if result.get("simulated") is not True or result.get("no_external_side_effect") is not True:
        raise SystemExit(f"{action} result does not prove simulation")
deleted = executed_by_action.get("delete_local") or executed_by_action.get("overwrite_local")
if not deleted or deleted["state"] != "skipped" or deleted.get("tool_result") is not None:
    raise SystemExit("rejected deletion was not permanently skipped")

_, verified = request("GET", f"{backend_base}/audit/verify/{run_id}")
if verified.get("valid") is not True:
    raise SystemExit("live workflow audit chain failed verification")

artifact = pathlib.Path(artifact_path)
artifact.write_text(
    "BOUNDARY live approval flow validation\n"
    f"timestamp_utc={datetime.now(timezone.utc).isoformat()}\n"
    f"run_id={run_id}\n"
    "safe_steps_executed=passed\n"
    "protected_steps_paused=passed\n"
    "preapproval_execution_blocked=passed\n"
    "send_simulation=passed\n"
    "schedule_simulation=passed\n"
    "rejected_delete_skipped=passed\n"
    "audit_chain=passed\n"
    "external_actions_executed=false\n",
    encoding="utf-8",
)
print(f"Live approval flow passed. Evidence saved to {artifact}")
PY
