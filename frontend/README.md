# BOUNDARY Control Center

The Control Center is a Next.js interface for the local BOUNDARY workflow. The
browser calls only same-origin `/api/boundary/*` routes. Next.js validates the
server-only `BOUNDARY_BACKEND_URL` and proxies an explicit route allowlist to
FastAPI; backend configuration is never exposed through `NEXT_PUBLIC_*` values.

## Local development

```powershell
cd frontend
npm install
$env:BOUNDARY_BACKEND_URL = "http://127.0.0.1:8080"
npm run dev
```

Open `http://127.0.0.1:3000`. The local FastAPI backend and vLLM service must
already be running for the complete workflow.

## Demo flow

1. Select **Use demo task**, then **Create Safe Plan**.
2. Review the ordered semantic-policy cards.
3. Enter an actor in the Approval Inbox and approve or reject protected steps.
4. Select **Execute simulations** and confirm the simulation-only warning.
5. Inspect stored results, the event timeline, and audit-chain verification.
6. Use **Reset View** to clear the browser view without deleting backend data.

No Control Center operation can perform a real email, calendar modification,
deletion, payment, upload, publication, share, command, or other external side
effect. The backend exposes simulated tools only.
