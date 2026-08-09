#!/usr/bin/env bash
# start.sh
# ========
# Hugging Face Spaces (Docker SDK) exposes exactly one port to the outside
# world (7860 by default). This app has two processes -- a FastAPI backend
# and a Streamlit frontend -- so we run the backend on an internal-only
# port and the frontend (the only thing that needs to be externally
# reachable) on 7860, with the frontend calling the backend over localhost.
set -e

BACKEND_PORT="${BACKEND_PORT:-8000}"

echo "[start.sh] Launching FastAPI backend on port ${BACKEND_PORT}..."
python -m uvicorn backend.main:app --host 0.0.0.0 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

cleanup() {
  echo "[start.sh] Shutting down backend (pid ${BACKEND_PID})..."
  kill "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo "[start.sh] Waiting for backend health check..."
for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; then
    echo "[start.sh] Backend is healthy."
    break
  fi
  sleep 1
done

echo "[start.sh] Launching Streamlit frontend on port 7860..."
streamlit run frontend/streamlit_app.py \
  --server.port=7860 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false
