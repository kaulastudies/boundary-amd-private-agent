#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BACKEND_BASE_URL="${BOUNDARY_BACKEND_BASE_URL:-http://127.0.0.1:8080}"
PRIMARY_DATABASE="${BOUNDARY_DATABASE_PATH:-/workspace/boundary-data/boundary.db}"
APP_PYTHON="${BOUNDARY_BACKEND_PYTHON:-/workspace/venvs/boundary-backend/bin/python}"
ARTIFACT_ROOT="${BOUNDARY_ARTIFACT_ROOT:-/workspace/boundary-artifacts}"
ARTIFACT_FILE="${ARTIFACT_ROOT}/debug/audit-chain-validation.txt"

if [[ ! -x "${APP_PYTHON}" ]]; then
  printf 'ERROR: backend Python environment not found at %s.\n' "${APP_PYTHON}" >&2
  exit 1
fi
if [[ ! -f "${PRIMARY_DATABASE}" ]]; then
  printf 'ERROR: primary workflow database not found at %s.\n' "${PRIMARY_DATABASE}" >&2
  exit 1
fi
mkdir -p "$(dirname "${ARTIFACT_FILE}")"

"${APP_PYTHON}" - \
  "${BACKEND_BASE_URL}" \
  "${PRIMARY_DATABASE}" \
  "${ARTIFACT_FILE}" \
  "${REPO_ROOT}/backend/src" <<'PY'
import ipaddress
import json
import pathlib
import shutil
import sqlite3
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone

backend_base, primary_path, artifact_path, source_path = sys.argv[1:]
parsed = urllib.parse.urlparse(backend_base)
if parsed.scheme not in {"http", "https"} or not parsed.hostname:
    raise SystemExit("backend URL is invalid")
if parsed.hostname != "localhost":
    address = ipaddress.ip_address(parsed.hostname)
    if not (address.is_loopback or address.is_private or address.is_link_local):
        raise SystemExit("audit test refuses a non-local backend")

def api(method, path, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    request = urllib.request.Request(
        f"{backend_base}{path}", data=body, headers=headers, method=method
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)

run = api("POST", "/runs", {"task": "Inspect local project metadata. Plan only."})
run_id = run["run_id"]
verified = api("GET", f"/audit/verify/{run_id}")
if verified.get("valid") is not True:
    raise SystemExit("primary audit chain did not verify before isolated tamper test")

sys.path.insert(0, source_path)
from boundary_backend.workflow import WorkflowDatabase

primary = pathlib.Path(primary_path).resolve()
with tempfile.TemporaryDirectory(dir=pathlib.Path(artifact_path).parent) as temp_dir:
    copied = pathlib.Path(temp_dir) / "tamper-test.db"
    shutil.copy2(primary, copied)
    if copied.resolve() == primary:
        raise SystemExit("refusing to tamper with the primary database")
    with sqlite3.connect(copied) as connection:
        connection.execute(
            "UPDATE audit_events SET metadata_json = ? WHERE run_id = ? AND sequence = "
            "(SELECT MIN(sequence) FROM audit_events WHERE run_id = ?)",
            ('{"isolated_tamper":true}', run_id, run_id),
        )
    valid_after_tamper, invalid_event = WorkflowDatabase(str(copied)).verify_audit(run_id)
    if valid_after_tamper or not invalid_event:
        raise SystemExit("tampering in copied database was not detected")

artifact = pathlib.Path(artifact_path)
artifact.write_text(
    "BOUNDARY live audit chain validation\n"
    f"timestamp_utc={datetime.now(timezone.utc).isoformat()}\n"
    f"run_id={run_id}\n"
    "primary_chain=passed\n"
    "isolated_copy_tamper_detected=passed\n"
    "primary_database_modified=false\n",
    encoding="utf-8",
)
print(f"Live audit-chain test passed. Evidence saved to {artifact}")
PY
