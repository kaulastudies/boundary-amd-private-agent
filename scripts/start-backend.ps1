$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot
python -m uvicorn boundary_backend.main:app --app-dir backend/src --reload --host 127.0.0.1 --port 8000
