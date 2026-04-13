FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# =========================
# System dependencies
# =========================
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        cloc \
        curl \
        build-essential \
        gcc \
        g++ \
        pkg-config \
        libssl-dev \
        libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# =========================
# Install Rust properly
# =========================
RUN curl https://sh.rustup.rs -sSf | sh -s -- -y

ENV PATH="/root/.cargo/bin:/root/.cargo/env:/root/.local/bin:${PATH}"
ENV CARGO_HOME="/root/.cargo"
ENV RUSTUP_HOME="/root/.rustup"

# verify rust works (VERY IMPORTANT)
RUN rustc --version && cargo --version

# =========================
# Python tooling
# =========================
RUN pip install --no-cache-dir -U pip setuptools wheel

# =========================
# Copy dependency file first
# =========================
COPY backend/pyproject.toml /app/pyproject.toml

# =========================
# Install project deps
# FIX: disable build isolation (fixes gseapy Rust error)
# =========================
RUN pip install --no-cache-dir --no-build-isolation .

# runtime/test extras
RUN pip install --no-cache-dir pandas pytest pytest-cov

# =========================
# Copy source code
# =========================
COPY backend/src /app/src

ENV PYTHONPATH=/app/src

EXPOSE 7070

CMD ["uvicorn", "control_center.main:app", "--host", "0.0.0.0", "--port", "7070"]