# ── Stage 1: Build React frontend (dual build: admin + control) ───────────────
# Admin Console dual build architecture: produces two separate build
# outputs from the same source -- dist-admin/ (admin.omnibioai.org,
# enterprise console: Organizations/Users/Roles/Teams + ops pages) and
# dist-control/ (control.omnibioai.org, ops pages only -- Organizations/
# Users/Roles/Teams code is genuinely absent via dead-code elimination,
# not just hidden; see docs/admin-console-build.md for how this is
# verified). PR14.7B: Stage 3 below now actually serves dist-admin/
# dist-control (host-based split), not the plain `dist/` output this
# comment used to describe -- `npm run build` (dist/) is still run here,
# unchanged, purely so nothing that might still reference it breaks; it
# just isn't Stage 3's input anymore.
FROM --platform=$BUILDPLATFORM node:20-bookworm-slim AS frontend-builder
WORKDIR /frontend
COPY frontend/cc-ui/package*.json ./
RUN npm ci
COPY frontend/cc-ui/ ./
RUN npm run build && npm run build:admin && npm run build:control

# ── Stage 2: Python backend ────────────────────────────────────────────────────
FROM ghcr.io/omnibioai/omnibioai-base:latest AS backend
LABEL org.opencontainers.image.source=https://github.com/man4ish/omnibioai
WORKDIR /app

# Rust needed for gseapy compilation.
# nodejs/npm needed for _run_vuln_scan()'s npm-audit branch (the 4
# npm-manifest repos: omnibioai-studio, omnibioai-design-tokens,
# omnibioai-ui, omnibioai-launcher) -- Debian trixie's own repo ships
# nodejs 20.x, matching the frontend-builder stage's node:20 above, so no
# third-party NodeSource script is needed to pin the major version.
RUN apt-get update && apt-get install -y --no-install-recommends     build-essential gcc g++ pkg-config libssl-dev libffi-dev curl ca-certificates cloc nodejs npm     && curl https://sh.rustup.rs -sSf | sh -s -- -y     && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.cargo/bin:${PATH}"

# Copy source BEFORE pip install
COPY backend/pyproject.toml .
COPY backend/src/ ./src/

RUN pip install --no-cache-dir --no-build-isolation .

ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1
EXPOSE 7070
CMD ["uvicorn", "control_center.main:app", "--host", "0.0.0.0", "--port", "7070"]

# ── Stage 3: nginx serves both React bundles, proxies API routes → backend ────
# PR14.7B: host-based domain split -- dist-control (control.omnibioai.org)
# and dist-admin (admin.omnibioai.org) served from the same image, same
# nginx process, dispatched by Host header. See docker/nginx/*.conf for
# the actual server blocks/proxy locations (kept as real files, not an
# inline heredoc, since the API proxy location list is now large enough
# -- one entry per backend route, control_center/main.py registers none
# of them under a common prefix -- that it needs to be readable/
# reviewable on its own). Stage 1's plain `npm run build` (dist/) is
# unchanged and still runs; this stage simply never consumed it beyond
# this PR either (see docs/admin-console-build.md).
FROM nginx:alpine AS frontend
COPY --from=frontend-builder /frontend/dist-control /usr/share/nginx/html/control
COPY --from=frontend-builder /frontend/dist-admin /usr/share/nginx/html/admin
COPY docker/nginx/api-proxy.conf /etc/nginx/api-proxy.conf
COPY docker/nginx/control-center.conf /etc/nginx/conf.d/default.conf
EXPOSE 5174