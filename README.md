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

- Python 3.11+
- Node.js 20+
- npm 10+

## Start the backend

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".\backend[dev]"
python -m uvicorn boundary_backend.main:app --app-dir backend/src --reload
```

The API is available at `http://localhost:8000`; health is at
`http://localhost:8000/health`.

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

`LocalModelClient` defines the future inference contract. The included
`UnconfiguredLocalModelClient` fails explicitly if generation is attempted.
No remote provider dependency, credential, or API-key setting is included.

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
BOUNDARY_PORT=8000 BOUNDARY_LOCAL_MODEL_ENDPOINT=http://127.0.0.1:8001 \
  bash scripts/cloud/run-backend.sh
```

JupyterLab is the primary access path; SSH is optional when enabled. See
[`docs/radeon-cloud.md`](docs/radeon-cloud.md) for the complete laptop → GitHub
→ Radeon Cloud workflow, exact checks, storage layout, and security rules.
