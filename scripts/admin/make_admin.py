"""Flip a user's `is_admin` flag to 1.

Usage:
    /app/.venv/bin/python scripts/admin/make_admin.py <email>

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/make_admin.py you@example.com"

Prints "updated N row(s)". Idempotent — running on an already-admin account
is a no-op (rowcount returns 1 either way; SQLite UPDATE matches by WHERE).
"""

from __future__ import annotations

import sys

from markland.config import get_config
from markland.db import init_db


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: make_admin.py <email>", file=sys.stderr)
        return 2
    email = sys.argv[1]
    conn = init_db(get_config().db_path)
    n = conn.execute(
        "UPDATE users SET is_admin=1 WHERE email=?", (email,)
    ).rowcount
    conn.commit()
    print(f"updated {n} row(s) for {email}")
    if n == 0:
        print(
            f"note: no user with email={email}. "
            f"They need to sign in via magic link first.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
