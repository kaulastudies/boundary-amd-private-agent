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
