#!/usr/bin/env sh
set -e

DB_PATH="${MARKLAND_DATA_DIR:-/data}/markland.db"

# Only attempt restore if we have replica credentials AND the DB doesn't already exist.
# Restore uses litestream's config-aware "-config" path so it inherits the same
# bucket/endpoint/region settings as replication.
if [ -n "${LITESTREAM_BUCKET}" ] && [ ! -f "${DB_PATH}" ]; then
  echo "[start] No local DB at ${DB_PATH}; attempting litestream restore…"
  litestream restore -if-replica-exists -config /etc/litestream.yml "${DB_PATH}" || {
    echo "[start] Restore failed or no replica exists; continuing with fresh DB"
  }
fi

if [ -n "${LITESTREAM_BUCKET}" ]; then
  echo "[start] Starting litestream replicate + uvicorn…"
  exec litestream replicate -config /etc/litestream.yml -exec \
    "uv run python src/markland/run_app.py"
else
  echo "[start] LITESTREAM_BUCKET not set; starting uvicorn directly (no backups)"
  exec uv run python src/markland/run_app.py
fi
