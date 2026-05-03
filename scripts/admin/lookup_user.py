"""Find a user by email and report their footprint.

Usage:
    /app/.venv/bin/python scripts/admin/lookup_user.py <email>

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/lookup_user.py alice@example.com"

Prints: user row, doc count (owned), grant count (received), token count
(active).
"""

from __future__ import annotations

import sys

from markland.config import get_config
from markland.db import init_db


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: lookup_user.py <email>", file=sys.stderr)
        return 2
    email = sys.argv[1]
    conn = init_db(get_config().db_path)
    user = conn.execute(
        "SELECT id, email, display_name, is_admin, created_at "
        "FROM users WHERE email=?",
        (email,),
    ).fetchone()
    if user is None:
        print(f"no user with email={email}", file=sys.stderr)
        return 1
    user_id = user[0]
    docs_owned = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE owner_id=?", (user_id,)
    ).fetchone()[0]
    docs_public = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE owner_id=? AND is_public=1",
        (user_id,),
    ).fetchone()[0]
    grants_received = conn.execute(
        "SELECT COUNT(*) FROM grants WHERE principal_id=?", (user_id,)
    ).fetchone()[0]
    tokens_active = conn.execute(
        "SELECT COUNT(*) FROM tokens "
        "WHERE principal_id=? AND principal_type='user' AND revoked_at IS NULL",
        (user_id,),
    ).fetchone()[0]

    print(f"id:              {user[0]}")
    print(f"email:           {user[1]}")
    print(f"display_name:    {user[2]}")
    print(f"is_admin:        {bool(user[3])}")
    print(f"created_at:      {user[4]}")
    print(f"docs_owned:      {docs_owned} ({docs_public} public)")
    print(f"grants_received: {grants_received}")
    print(f"tokens_active:   {tokens_active}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
