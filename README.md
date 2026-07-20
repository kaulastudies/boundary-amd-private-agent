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
npm run dev
```

Open `http://localhost:3000`. Set `NEXT_PUBLIC_BACKEND_URL` to override the
default backend URL.

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

`GET /model/health` checks model discovery. `POST /agent/plan` returns validated
plan steps and never executes tools or exposes hidden chain-of-thought.

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
