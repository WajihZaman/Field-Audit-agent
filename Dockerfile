# Dockerfile
# ==========
# Single-container deployment for Hugging Face Spaces (Docker SDK).
# Runs the FastAPI backend and Streamlit frontend as two processes inside
# one container -- see start.sh. HF Spaces routes external traffic to
# port 7860, which the Streamlit frontend binds to.

FROM python:3.11-slim

# curl is used by start.sh to wait for the backend's /health endpoint
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face Spaces best practice: run as a non-root user with a fixed
# UID so file permissions (e.g. the SQLite/Chroma data dir) behave
# predictably regardless of how the Space schedules the container.
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR $HOME/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user backend/ ./backend/
COPY --chown=user frontend/ ./frontend/
COPY --chown=user start.sh ./start.sh
RUN mkdir -p data && chmod +x start.sh

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=$HOME/app \
    BACKEND_PORT=8000 \
    BACKEND_INTERNAL_URL=http://127.0.0.1:8000

EXPOSE 7860

CMD ["./start.sh"]
