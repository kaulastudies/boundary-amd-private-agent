# Radeon Cloud

BOUNDARY uses Radeon Cloud as a local-inference development target. The
expected image is Ubuntu 22.04 with ROCm 7.2.1, a `gfx1100` GPU, and bundled
PyTorch and vLLM packages—normally in `/opt/venv`. Treat the supplied GPU stack
as immutable: never install, upgrade, downgrade, or replace ROCm, PyTorch, or
vLLM from this repository.

## Workflow

1. Develop and run lightweight tests on the local laptop.
2. Commit and push source code to GitHub. Do not commit `.env`, credentials,
   personal data, model weights, or generated environment reports containing
   sensitive host details.
3. Open the Radeon Cloud JupyterLab session, which is the primary access method.
4. In a JupyterLab terminal, clone or pull the repository under `/workspace`.
   This mount is persistent; store the repository, application virtual
   environments, benchmark results, and approved model files there.
5. Verify the supplied GPU environment before setting up the BOUNDARY backend.

SSH is optional when enabled for the instance. It uses the same `/workspace`
files and does not replace JupyterLab as the documented primary path.

## Exact verification commands

Run these from the repository root:

```bash
cd /workspace/boundary-amd-private-agent
bash -n scripts/cloud/*.sh
bash scripts/cloud/test-scripts.sh
bash scripts/cloud/verify-rocm.sh
bash scripts/cloud/check-vllm.sh
```

`verify-rocm.sh` writes a timestamped report to `benchmarks/environment/` and
exits with clear diagnostics if tools, imports, `gfx1100`, or ROCm 7.2.1 cannot
be verified. The scripts report problems; they never repair the supplied GPU
environment or download a model.

## Backend environment and startup

Create a separate, persistent application environment and start FastAPI:

```bash
cd /workspace/boundary-amd-private-agent
bash scripts/cloud/setup-backend.sh
BOUNDARY_PORT=8080 \
BOUNDARY_MODEL_BASE_URL=http://127.0.0.1:8000/v1 \
BOUNDARY_MODEL_NAME=boundary-qwen3-8b \
BOUNDARY_MODEL_TIMEOUT_SECONDS=30 \
BOUNDARY_DATABASE_PATH=/workspace/boundary-data/boundary.db \
bash scripts/cloud/run-backend.sh
```

The application environment is `/workspace/venvs/boundary-backend`. It contains
only the BOUNDARY backend and its test dependencies. `/opt/venv` remains the
separate, bundled inference environment.

Test the backend without touching the inference environment:

```bash
/workspace/venvs/boundary-backend/bin/python -m pytest backend/tests
curl --fail http://127.0.0.1:8080/health
curl --fail http://127.0.0.1:8080/model/health
curl --fail --request POST http://127.0.0.1:8080/agent/plan \
  --header 'Content-Type: application/json' \
  --data '{"task":"Inspect the repository and propose safe next steps."}'
```

After both services are running, execute the bounded live smoke test:

```bash
cd /workspace/boundary-amd-private-agent
bash scripts/cloud/test-live-plan.sh
bash scripts/cloud/test-live-permission-policy.sh
cat /workspace/boundary-artifacts/debug/agent-plan-validation.txt
cat /workspace/boundary-artifacts/debug/permission-policy-validation.txt
```

The smoke test checks vLLM discovery, both backend health endpoints, and one
schema-constrained plan. It validates the plan and deterministic approval policy
locally, then writes a non-secret result to
`/workspace/boundary-artifacts/debug/agent-plan-validation.txt`. It does not
launch a model, install packages, or send credentials.

The permission-policy test submits a planning-only contract workflow containing
local review and drafting plus email sending, deletion, and meeting scheduling.
It fails if external actions are not sensitive and approval-required, deletion
is not destructive, required policy fields are missing, or any result claims an
external action occurred.

## Persistent workflow and audit validation

The backend initializes its SQLite schema at
`/workspace/boundary-data/boundary.db`. This persistent local database stores
runs, plan steps, approval requests and decisions, append-only audit events, and
simulated results. It is separate from `/opt/venv` and contains no model runtime.

With vLLM and the backend already running:

```bash
cd /workspace/boundary-amd-private-agent
bash scripts/cloud/test-live-approval-flow.sh
bash scripts/cloud/test-live-audit-chain.sh
cat /workspace/boundary-artifacts/debug/approval-flow-validation.txt
cat /workspace/boundary-artifacts/debug/audit-chain-validation.txt
```

The approval-flow test verifies that protected steps pause, early execution is
blocked, send and schedule actions require explicit approval, rejected deletion
is skipped, and every result is simulated. The audit test verifies the primary
chain, copies the database to an isolated temporary file, tampers only with that
copy, confirms detection, and removes the copy. It never alters the primary
database.

## Security boundary

- Do not place secrets, tokens, or credentials in Git, notebooks, demo data, or
  shell history.
- Do not connect core inference to remote AI APIs. Model execution must remain
  on the assigned Radeon Cloud GPU.
- `BOUNDARY_MODEL_BASE_URL` accepts only `http` or `https` endpoints on
  `localhost`, loopback, or explicit private/link-local IP addresses. It never
  falls back to a public provider.
- The expected vLLM service is `http://127.0.0.1:8000/v1`, serving
  `boundary-qwen3-8b`. BOUNDARY does not start vLLM or download a model.
- Planning returns validated steps only; it does not execute tools and must not
  request or expose hidden chain-of-thought.
- Review environment reports before sharing them outside the project.
