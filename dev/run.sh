#!/usr/bin/env bash
# Runs decider (8080), stylist (8081) and front door + web (9000) as local processes.
#   dev/run.sh                    mock decider and stylist
#   DECIDER_MOCK=0 dev/run.sh     real Decider E2B on CPU
#   STYLIST_MOCK=0 GOOGLE_API_KEY=... dev/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}

pids=()
trap 'kill "${pids[@]}" 2>/dev/null || true' EXIT

DECIDER_MOCK=${DECIDER_MOCK:-1} \
  "$PY" -m uvicorn decider.app:app --host 127.0.0.1 --port 8080 &
pids+=($!)

STYLIST_MOCK=${STYLIST_MOCK:-1} GOOGLE_GENAI_USE_ENTERPRISE=0 \
  ALLOWED_ORIGINS=http://localhost:9000,http://127.0.0.1:9000 \
  "$PY" -m uvicorn stylist.app:app --host 127.0.0.1 --port 8081 &
pids+=($!)

DEMO_KEY=dev BACKEND=http DECIDER_URL=http://127.0.0.1:8080 PORT=9000 \
  "$PY" -m frontdoor.local &
pids+=($!)

echo "open http://localhost:9000"
wait
