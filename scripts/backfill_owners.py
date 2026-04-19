"""Backfill documents.owner_id for pre-Plan-3 docs.

Usage:
  MARKLAND_DATA_DIR=/data BACKFILL_OWNER_EMAIL=admin@markland.dev \
    uv run python scripts/backfill_owners.py [--dry-run]

Looks up the user by email and sets owner_id on every documents row where
owner_id IS NULL. Prints the count. Idempotent — running twice is a no-op.
"""

from __future__ import annotations

import argparse
import os
import sys

from markland.config import get_config
from markland.db import init_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    email = os.environ.get("BACKFILL_OWNER_EMAIL", "").strip()
    if not email:
        print(
            "set BACKFILL_OWNER_EMAIL to the email of the user that should own "
            "all orphaned docs",
            file=sys.stderr,
        )
        return 2

    config = get_config()
    conn = init_db(config.db_path)
    row = conn.execute(
        "SELECT id FROM users WHERE lower(email) = lower(?)", (email,)
    ).fetchone()
    if row is None:
        print(
            f"no user with email {email} — create the account first, then re-run",
            file=sys.stderr,
        )
        return 1
    owner_id = row[0]

    orphan_count = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE owner_id IS NULL"
    ).fetchone()[0]
    print(f"found {orphan_count} orphaned docs; target owner_id={owner_id}")
    if orphan_count == 0:
        return 0
    if args.dry_run:
        print("dry-run; no writes")
        return 0
    conn.execute(
        "UPDATE documents SET owner_id = ? WHERE owner_id IS NULL", (owner_id,)
    )
    conn.commit()
    print(f"assigned owner_id={owner_id} to {orphan_count} docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
