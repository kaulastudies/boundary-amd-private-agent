#!/usr/bin/env bash
trap - ERR
set +e
set +E
set +u
set +o pipefail
BACKEND_URL=${BOUNDARY_BACKEND_URL:-http://127.0.0.1:8080}
OUT=/workspace/boundary-artifacts/benchmarks/private-rag-benchmark.json
TOP_K=${BOUNDARY_RAG_BENCHMARK_TOP_K:-4}
mkdir -p "$(dirname "$OUT")" || exit 1
command -v curl >/dev/null && command -v python3 >/dev/null || { echo "curl and python3 are required" >&2; exit 1; }
if ! BACKEND_URL="$BACKEND_URL" TOP_K="$TOP_K" python3 - <<'PY'
import ipaddress
import os
from urllib.parse import urlparse

url = urlparse(os.environ["BACKEND_URL"])
try:
    address_is_local = url.hostname == "localhost" or ipaddress.ip_address(url.hostname or "").is_private
    top_k_is_valid = 1 <= int(os.environ["TOP_K"]) <= 8
except (ValueError, TypeError):
    raise SystemExit(1)
valid = (
    url.scheme in {"http", "https"}
    and address_is_local
    and not url.username
    and not url.password
    and url.path in {"", "/"}
    and not url.query
    and not url.fragment
    and top_k_is_valid
)
raise SystemExit(0 if valid else 1)
PY
then
  echo "BACKEND_URL must be local/private and TOP_K must be from 1 to 8" >&2
  exit 1
fi
tmp=$(mktemp -d /workspace/boundary-artifacts/benchmarks/rag-benchmark.XXXXXX) || exit 1
cleanup() {
  case "$tmp" in
    /workspace/boundary-artifacts/benchmarks/rag-benchmark.*)
      rm -f "$tmp/bootstrap.json" "$tmp/bootstrap-times" "$tmp/health.json" \
        "$tmp/backend-health.json" "$tmp/openapi.json" "$tmp/query-times" \
        "$tmp/request.json" "$tmp/run.json" "$tmp/run-response.json" "$tmp/plan-times"
      rmdir "$tmp" 2>/dev/null
      ;;
  esac
}
trap cleanup EXIT
start=$(python3 -c 'import time; print(time.perf_counter())')
curl --fail --silent --show-error --max-time 600 -X POST "$BACKEND_URL/rag/bootstrap-demo" -H 'Content-Type: application/json' -d '{}' > "$tmp/bootstrap.json" || { echo "RAG bootstrap failed" >&2; exit 1; }
end=$(python3 -c 'import time; print(time.perf_counter())'); printf '%s %s\n' "$start" "$end" > "$tmp/bootstrap-times"
curl --fail --silent --show-error --max-time 10 "$BACKEND_URL/rag/health" > "$tmp/health.json" || { echo "RAG health check failed" >&2; exit 1; }
curl --fail --silent --show-error --max-time 10 "$BACKEND_URL/health" > "$tmp/backend-health.json" || { echo "Backend health check failed" >&2; exit 1; }
curl --fail --silent --show-error --max-time 10 "$BACKEND_URL/openapi.json" > "$tmp/openapi.json" || { echo "Backend version discovery failed" >&2; exit 1; }
: > "$tmp/query-times"
for query in 'delivery milestone penalties' 'staffing dependency schedule risks' 'email deletion meeting approval'; do
  qstart=$(python3 -c 'import time; print(time.perf_counter())')
  QUERY="$query" TOP_K="$TOP_K" python3 -c 'import json,os; print(json.dumps({"query":os.environ["QUERY"],"top_k":int(os.environ["TOP_K"])}))' > "$tmp/request.json"
  curl --fail --silent --show-error --max-time 120 -X POST "$BACKEND_URL/rag/query" -H 'Content-Type: application/json' --data-binary "@$tmp/request.json" > /dev/null || { echo "RAG query failed" >&2; exit 1; }
  qend=$(python3 -c 'import time; print(time.perf_counter())'); printf '%s %s\n' "$qstart" "$qend" >> "$tmp/query-times"
done
pstart=$(python3 -c 'import time; print(time.perf_counter())')
python3 -c 'import json; print(json.dumps({"task":"Review the synthetic contract, identify delivery risks, draft and send an email, delete the contract, and schedule a meeting. Plan only.","use_private_evidence":True,"evidence_top_k":4}))' > "$tmp/run.json"
curl --fail --silent --show-error --max-time 600 -X POST "$BACKEND_URL/runs" -H 'Content-Type: application/json' --data-binary "@$tmp/run.json" > "$tmp/run-response.json" || { echo "Evidence-grounded plan failed" >&2; exit 1; }
pend=$(python3 -c 'import time; print(time.perf_counter())'); printf '%s %s\n' "$pstart" "$pend" > "$tmp/plan-times"
TMP="$tmp" OUT="$OUT" TOP_K="$TOP_K" python3 - <<'PY'
import json, os, statistics
from pathlib import Path
t=Path(os.environ['TMP']); h=json.loads((t/'health.json').read_text()); backend=json.loads((t/'backend-health.json').read_text()); spec=json.loads((t/'openapi.json').read_text()); run=json.loads((t/'run-response.json').read_text()); bs,be=map(float,(t/'bootstrap-times').read_text().split()); ps,pe=map(float,(t/'plan-times').read_text().split())
if h.get('index_backend') != 'faiss' or not h.get('available'): raise SystemExit('Radeon benchmark requires an available FAISS index')
if backend.get('remote_apis_enabled') is not False: raise SystemExit('remote API boundary is not verified')
if not run.get('private_evidence_used') or not run.get('evidence'): raise SystemExit('plan did not use private evidence')
lat=[(float(b)-float(a))*1000 for a,b in (x.split() for x in (t/'query-times').read_text().splitlines())]; ordered=sorted(lat)
pct=lambda p: ordered[min(len(ordered)-1,round((len(ordered)-1)*p))]
r={"embedding_model":h["embedding_model"],"embedding_device":h["embedding_device"],"index_backend":h["index_backend"],"document_count":h["document_count"],"chunk_count":h["chunk_count"],"bootstrap_duration_ms":round((be-bs)*1000,3),"retrieval_latencies_ms":[round(x,3) for x in lat],"average_retrieval_latency_ms":round(statistics.mean(lat),3),"p50_retrieval_latency_ms":round(pct(.5),3),"p95_retrieval_latency_ms":round(pct(.95),3),"evidence_grounded_plan_latency_ms":round((pe-ps)*1000,3),"top_k":int(os.environ['TOP_K']),"radeon_model_name":backend["model"],"backend_version":spec["info"]["version"]}
Path(os.environ['OUT']).write_text(json.dumps(r,indent=2)+"\n")
PY
cat "$OUT"
