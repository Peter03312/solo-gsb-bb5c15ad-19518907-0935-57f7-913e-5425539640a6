# syntax=docker/dockerfile:1
# ---------------------------------------------------------------------------
# Stage 1: build the React/Vite frontend
# ---------------------------------------------------------------------------
FROM node:20-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python backend serving API + built static assets
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    STATIC_DIR=/app/frontend/dist \
    PORT=8000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend /app/backend
COPY --from=frontend /build/frontend/dist /app/frontend/dist

# local storage for uploaded sources and generated parts
RUN mkdir -p /data/sources /data/outputs
VOLUME ["/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

WORKDIR /app/backend
# init storage directories, then start the API (which also serves the SPA)
CMD ["sh", "-c", "mkdir -p \"$DATA_DIR/sources\" \"$DATA_DIR/outputs\" && uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]
