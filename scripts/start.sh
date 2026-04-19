#!/usr/bin/env sh
set -e

DB_PATH="${MARKLAND_DATA_DIR:-/data}/markland.db"

# Only attempt restore if we have replica credentials AND the DB doesn't already exist.
if [ -n "${LITESTREAM_REPLICA_URL}" ] && [ ! -f "${DB_PATH}" ]; then
  echo "[start] No local DB at ${DB_PATH}; attempting litestream restore…"
  litestream restore -if-replica-exists -o "${DB_PATH}" "${LITESTREAM_REPLICA_URL}" || {
    echo "[start] Restore failed or no replica exists; continuing with fresh DB"
  }
fi

if [ -n "${LITESTREAM_REPLICA_URL}" ]; then
  echo "[start] Starting litestream replicate + uvicorn…"
  exec litestream replicate -config /etc/litestream.yml -exec \
    "uv run python src/markland/run_app.py"
else
  echo "[start] LITESTREAM_REPLICA_URL not set; starting uvicorn directly (no backups)"
  exec uv run python src/markland/run_app.py
fi
