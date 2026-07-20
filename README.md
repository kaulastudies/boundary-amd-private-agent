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
