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

# Create non-root user up front so subsequent COPYs can target a chown'd
# tree (P1-D / markland-l2p — drop the implicit root runtime).
RUN useradd -m -u 1000 -s /bin/bash app \
 && mkdir -p /data /app \
 && chown -R app:app /data /app

WORKDIR /app

# Copy dependency files first for layer caching
COPY --chown=app:app pyproject.toml uv.lock ./
COPY --chown=app:app src ./src

RUN uv sync --frozen --no-dev \
 && chown -R app:app /app

COPY --chown=app:app scripts /app/scripts
COPY --chown=app:app seed-content /app/seed-content
COPY litestream.yml /etc/litestream.yml
RUN cp /app/scripts/start.sh /app/start.sh && chmod +x /app/start.sh \
 && chown app:app /app/start.sh

# Persist SQLite on a volume — mount target is owned by `app` (chown'd above).
VOLUME ["/data"]

EXPOSE 8080

# Drop privileges before exec'ing start.sh / litestream / uvicorn.
USER app

ENTRYPOINT ["/app/start.sh"]
