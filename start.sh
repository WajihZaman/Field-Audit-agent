#!/usr/bin/env bash
# start.sh
# ========
# Hugging Face Spaces (Docker SDK) exposes exactly one port to the outside
# world (7860 by default). This app has two processes -- a FastAPI backend
# and a Streamlit frontend -- so we run the backend on an internal-only
# port and the frontend (the only thing that needs to be externally
# reachable) on 7860, with the frontend calling the backend over localhost.
set -e

# 1. Define and EXPORT ports/URLs so both Python processes share the exact same config
BACKEND_PORT="${BACKEND_PORT:-8000}"
export BACKEND_PORT
export BACKEND_INTERNAL_URL="http://127.0.0.1:${BACKEND_PORT}"

echo "[start.sh] Launching FastAPI backend on port ${BACKEND_PORT}..."
# 2. Bind to 127.0.0.1 since it's strictly internal to this container
python -m uvicorn backend.main:app --host 127.0.0.1 --port "${BACKEND_PORT}" &
BACKEND_PID=$!

cleanup() {
  echo "[start.sh] Shutting down backend (pid ${BACKEND_PID})..."
  kill "${BACKEND_PID}" 2>/dev/null || true
  wait "${BACKEND_PID}" 2>/dev/null || true
}
trap cleanup EXIT

echo "[start.sh] Waiting for backend health check..."
# 3. Use Python for the health check to avoid missing `curl` in slim Docker images
# 4. Explicitly fail the container build/start if the backend doesn't respond
MAX_RETRIES=45
for i in $(seq 1 $MAX_RETRIES); do
  if python -c "import urllib.request; urllib.request.urlopen('${BACKEND_INTERNAL_URL}/health')" > /dev/null 2>&1; then
    echo "[start.sh] Backend is healthy."
    break
  fi
  
  if [ "$i" -eq "$MAX_RETRIES" ]; then
    echo "[start.sh] ERROR: Backend failed to start within ${MAX_RETRIES} seconds."
    exit 1
  fi
  sleep 1
done

echo "[start.sh] Launching Streamlit frontend on port 7860..."
# 5. Disable CORS and XSRF protection to prevent websocket/proxy issues in HF Spaces
streamlit run frontend/streamlit_app.py \
  --server.port=7860 \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --browser.gatherUsageStats=false \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false