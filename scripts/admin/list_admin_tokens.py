"""List metadata of tokens bound to admin users.

Plaintexts are unrecoverable (Argon2id-hashed) — this only shows ids,
labels, timestamps, and revocation state. Useful for spotting forgotten
test tokens that need cleanup.

Usage:
    /app/.venv/bin/python scripts/admin/list_admin_tokens.py

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/list_admin_tokens.py"
"""

from __future__ import annotations

from markland.config import get_config
from markland.db import init_db


def main() -> int:
    conn = init_db(get_config().db_path)
    rows = conn.execute(
        "SELECT t.id, t.label, u.email, t.created_at, t.last_used_at, t.revoked_at "
        "FROM tokens t JOIN users u ON u.id=t.principal_id "
        "WHERE t.principal_type='user' AND u.is_admin=1 "
        "ORDER BY t.created_at DESC"
    ).fetchall()
    if not rows:
        print("no admin tokens")
        return 0
    print(f"{'id':<24} {'email':<30} {'label':<20} {'created_at':<28} {'last_used':<28} revoked")
    for r in rows:
        tid, label, email, created, last_used, revoked = r
        print(
            f"{tid:<24} {email:<30} {(label or ''):<20} "
            f"{created:<28} {(last_used or '-'):<28} {(revoked or '-')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
