# syntax=docker/dockerfile:1.7

# Every image below is pinned by digest so two builds of the same commit
# ship the same OS packages and binaries. python:3.12-slim@78387bc3… is the
# Debian 13 base under the last known-healthy prod image (v235). Bump digests
# deliberately (all FROM lines together), rebuild, and diff `dpkg-query -W`
# before merging.

# --- litestream: download + checksum-verify in a throwaway stage so curl and
# its apt dependencies never reach the runtime image.
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS litestream

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

ARG LITESTREAM_VERSION=0.3.13
ARG LITESTREAM_SHA256=eb75a3de5cab03875cdae9f5f539e6aedadd66607003d9b1e7a9077948818ba0
RUN curl -fsSL -o /tmp/litestream.tar.gz "https://github.com/benbjohnson/litestream/releases/download/v${LITESTREAM_VERSION}/litestream-v${LITESTREAM_VERSION}-linux-amd64.tar.gz" \
    && echo "${LITESTREAM_SHA256}  /tmp/litestream.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/litestream.tar.gz -C /usr/local/bin litestream \
    && chmod +x /usr/local/bin/litestream

# --- runtime
FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    MARKLAND_DATA_DIR=/data \
    MARKLAND_WEB_PORT=8080

# No apt in this stage: the pinned base already ships ca-certificates (used by
# litestream's Go TLS stack for R2), tzdata, and netbase; Python's outbound
# TLS (Resend, Sentry) uses certifi's bundle from the venv.
COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5.6@sha256:92aa10fc236a5cbd3624c9909f855a860bd209fef17756c831ee84c478423517 /uv /usr/local/bin/uv

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
