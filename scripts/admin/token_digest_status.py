"""Report how far the token-digest backfill has got (markland-tex).

A token gets its indexed SHA-256 lookup digest at mint, or on its first
successful resolve after the digest release. Until then, resolving it
costs one Argon2 verify, and every failed auth still Argon2-verifies the
pre-cutoff rows without one. Prints counts only, never token material.

Usage:
    /app/.venv/bin/python scripts/admin/token_digest_status.py

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/token_digest_status.py"
"""

from __future__ import annotations

from markland.config import get_config
from markland.db import init_db
from markland.service.auth import token_digest_counts


def main() -> int:
    conn = init_db(get_config().db_path)
    counts = token_digest_counts(conn)
    print(f"live tokens:                    {counts['live']}")
    print(f"  without a digest yet:         {counts['without_digest']}")
    print(f"  scanned by every failed auth: {counts['legacy_scan']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
