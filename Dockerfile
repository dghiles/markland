# syntax=docker/dockerfile:1.7

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    MARKLAND_DATA_DIR=/data \
    MARKLAND_WEB_PORT=8080

# Install system deps (litestream) + uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# Install litestream (pinned version)
ARG LITESTREAM_VERSION=0.3.13
RUN curl -fsSL "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    | tar -xz -C /usr/local/bin litestream \
    && chmod +x /usr/local/bin/litestream

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.6 /uv /usr/local/bin/uv

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./
COPY src ./src

RUN uv sync --frozen --no-dev

COPY scripts /app/scripts
COPY litestream.yml /etc/litestream.yml
RUN cp /app/scripts/start.sh /app/start.sh && chmod +x /app/start.sh

# Persist SQLite on a volume
VOLUME ["/data"]

EXPOSE 8080

ENTRYPOINT ["/app/start.sh"]
