# BOUNDARY AMD DevMaster — Track 2

Local-first agent workspace for AMD development. The project is intentionally
scaffolded without a final model implementation, remote AI APIs, or API keys.

## Layout

- `backend/` — FastAPI service, Pydantic schemas, and a local model interface
- `frontend/` — Next.js, TypeScript, and Tailwind status UI
- `agent/` — planner, executor, retrieval, memory, permissions, audit, and tools
- `benchmarks/` — benchmark definitions and future results
- `demo-data/` — safe local sample data
- `docs/` — architecture and development notes
- `scripts/` — local startup helpers

## Prerequisites

- Python 3.10+
- Node.js 20+
- npm 10+

## Start the backend

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
python -m uvicorn boundary_backend.main:app --app-dir backend/src --reload --port 8080
```

The API is available at `http://localhost:8080`; health is at
`http://localhost:8080/health`. It connects only to a validated local vLLM
endpoint, which defaults to `http://127.0.0.1:8000/v1`.

## Start the frontend

```powershell
cd frontend
npm install
npm run build
npm run dev
```

Open `http://localhost:3000`. Set the server-only `BOUNDARY_BACKEND_URL` to
override the default `http://127.0.0.1:8080`. The browser never receives that
configuration and calls only same-origin `/api/boundary/*` routes. The Next.js
proxy validates local/private origins, allows only known workflow routes,
sanitizes errors, and applies bounded timeouts.

## Control Center

The responsive Control Center presents the complete BOUNDARY demo without curl:

1. Compose a task or load the confidential-contract demonstration.
2. Create a schema-constrained, policy-normalized workflow run.
3. Inspect safe, review, sensitive, destructive, and blocked step cards.
4. Approve or reject protected actions with an actor and optional reason.
5. Confirm simulation-only execution and review stored results.
6. Inspect the chronological audit trail and SHA-256 verification status.

The interface clearly marks `simulated=true` and
`no_external_side_effect=true`. **Reset View** clears frontend state only and
does not delete persistent runs or audit records. See
[`frontend/README.md`](frontend/README.md) for local development and the demo
script.

## Tests

```powershell
python -m pytest backend/tests
cd frontend
npm test
npm run typecheck
```

Convenience launchers are provided in `scripts/start-backend.ps1` and
`scripts/start-frontend.ps1`.

## Local-only model boundary

`LocalModelClient` defines the local inference contract and
`VLLMLocalModelClient` implements it through vLLM's local OpenAI-compatible HTTP
surface. It requires no API key and rejects public or unsupported endpoint
URLs. No remote provider dependency, credential, or fallback is included.

Configuration:

```dotenv
BOUNDARY_MODEL_BASE_URL=http://127.0.0.1:8000/v1
BOUNDARY_MODEL_NAME=boundary-qwen3-8b
BOUNDARY_MODEL_TIMEOUT_SECONDS=30
```

`GET /model/health` checks model discovery. `POST /agent/plan` uses vLLM JSON
schema constraints, returns validated plan steps, and never executes tools or
exposes hidden chain-of-thought. The backend always forces approval for
`sensitive`, `destructive`, and `blocked` steps, regardless of model output. A
semantically invalid result receives at most one repair request to the same
local endpoint.

Every plan step includes a typed `action_type` and backend-authored
`policy_reason`. The deterministic semantic policy independently checks titles
and descriptions, distinguishes drafting from sending, and only elevates risk.
External communication/calendar/sharing actions require approval; destructive
operations are destructive; and credential export is blocked. Model-provided
classifications can never weaken these rules.

## Persistent approval workflow

Milestone 3 stores plans as auditable runs in local SQLite. On Radeon Cloud the
default database is `/workspace/boundary-data/boundary.db`; override it with
`BOUNDARY_DATABASE_PATH`. The database contains `runs`, `plan_steps`,
`approval_requests`, `approval_decisions`, `audit_events`, and
`simulated_tool_results` tables initialized deterministically at startup.

Workflow endpoints:

- `POST /runs` creates and stores a policy-normalized plan without executing it.
- `GET /runs/{run_id}` returns run, step, approval, and simulated-result state.
- `GET /approvals?run_id=...` lists pending, step-scoped approvals.
- `POST /approvals/{approval_id}/approve` and `/reject` record an actor decision.
- `POST /runs/{run_id}/execute` runs only preflighted simulations.
- `GET /runs/{run_id}/audit` returns the append-only event chain.
- `GET /audit/verify/{run_id}` verifies every SHA-256 audit link.

Safe steps move from `ready` to `executed`. Protected steps move through
`awaiting_approval` and `approved` before execution; rejected steps can only be
skipped, and blocked steps cannot execute. Invalid transitions return typed HTTP
409 responses. Execution re-applies semantic policy and verifies approval scope
immediately before every simulated tool invocation.

All tool results state `simulated=true` and `no_external_side_effect=true`.
There are no real email, calendar, deletion, command, payment, upload,
publication, external API, or other side-effecting tool implementations.

## Radeon Cloud

Radeon Cloud is supported as the Ubuntu 22.04 GPU target. The expected supplied
environment provides ROCm 7.2.1 for `gfx1100`, with PyTorch and vLLM in an
existing bundled environment such as `/opt/venv`. BOUNDARY never replaces or
modifies that GPU stack.

Keep the repository and application environment on persistent `/workspace`
storage. From a JupyterLab terminal:

```bash
cd /workspace/boundary-amd-private-agent
bash scripts/cloud/verify-rocm.sh
bash scripts/cloud/check-vllm.sh
bash scripts/cloud/setup-backend.sh
BOUNDARY_PORT=8080 BOUNDARY_MODEL_BASE_URL=http://127.0.0.1:8000/v1 \
  BOUNDARY_MODEL_NAME=boundary-qwen3-8b \
  bash scripts/cloud/run-backend.sh
```

JupyterLab is the primary access path; SSH is optional when enabled. See
[`docs/radeon-cloud.md`](docs/radeon-cloud.md) for the complete laptop → GitHub
→ Radeon Cloud workflow, exact checks, storage layout, and security rules.
