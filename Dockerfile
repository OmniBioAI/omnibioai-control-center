# ── Stage 1: Build React frontend ─────────────────────────────────────────────
FROM --platform=$BUILDPLATFORM node:20-bookworm-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/cc-ui/package*.json ./
RUN npm ci
COPY frontend/cc-ui/ ./
RUN npm run build

# ── Stage 2: Python backend ────────────────────────────────────────────────────
FROM ghcr.io/omnibioai/omnibioai-base:latest AS backend
LABEL org.opencontainers.image.source=https://github.com/man4ish/omnibioai
WORKDIR /app

# Rust needed for gseapy compilation
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential gcc g++ pkg-config libssl-dev libffi-dev curl ca-certificates cloc     && curl https://sh.rustup.rs -sSf | sh -s -- -y     && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

# Copy source BEFORE pip install
COPY backend/pyproject.toml .
COPY backend/src/ ./src/

RUN pip install --no-cache-dir --no-build-isolation .

ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
EXPOSE 7070
CMD ["uvicorn", "control_center.main:app", "--host", "0.0.0.0", "--port", "7070"]

# ── Stage 3: nginx serves React, proxies API routes → backend ─────────────────
FROM nginx:alpine AS frontend
COPY --from=frontend-builder /frontend/dist /usr/share/nginx/html
COPY <<'EOF' /etc/nginx/conf.d/default.conf
server {
    listen 5174;
    root /usr/share/nginx/html;
    index index.html;
    location / { try_files $uri $uri/ /index.html; }
    location /summary  { proxy_pass http://control-center:7070; proxy_set_header Host $host; }
    location /health   { proxy_pass http://control-center:7070; }
    location /services { proxy_pass http://control-center:7070; proxy_set_header Host $host; }
    location /report   { proxy_pass http://control-center:7070; proxy_set_header Host $host; }
    location /config   { proxy_pass http://control-center:7070; proxy_set_header Host $host; }
    location /docker   { proxy_pass http://control-center:7070; proxy_set_header Host $host; }
}
EOF
EXPOSE 5174