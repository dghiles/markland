"""Mint a fresh user-token bound to the first admin user.

Existing token plaintexts are unrecoverable (Argon2id-hashed in `tokens`).
Use this to get a working bearer for `curl`-ing /admin/* endpoints.

Usage:
    /app/.venv/bin/python scripts/admin/mint_admin_token.py [LABEL]

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/mint_admin_token.py runbook-test"

Prints the plaintext token ONCE. Save it as $ADMIN_TOKEN, then revoke in
/settings/tokens (or via direct DELETE) when you're done — bearers in
shell history are a security smell.
"""

from __future__ import annotations

import sys

from markland.config import get_config
from markland.db import init_db
from markland.service.auth import create_user_token


def main() -> int:
    label = sys.argv[1] if len(sys.argv) > 1 else "admin-test"
    conn = init_db(get_config().db_path)
    row = conn.execute(
        "SELECT id, email FROM users WHERE is_admin=1 LIMIT 1"
    ).fetchone()
    if row is None:
        print(
            "error: no admin user. Run scripts/admin/make_admin.py first.",
            file=sys.stderr,
        )
        return 1
    admin_id, admin_email = row
    _, plaintext = create_user_token(conn, user_id=admin_id, label=label)
    print(f"admin:  {admin_email}")
    print(f"label:  {label}")
    print(f"token:  {plaintext}")
    print()
    print("Use as: Authorization: Bearer <token>")
    print("Revoke when done via /settings/tokens.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
