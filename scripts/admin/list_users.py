"""List all users with footprint counts — answers "who's on here?".

Usage:
    /app/.venv/bin/python scripts/admin/list_users.py [--limit N] [--since DAYS]

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/list_users.py"

Prints one row per user: id, email, display_name, is_admin, created_at, and
counts for docs owned (public/total), grants received, active tokens, and
last-seen (max of last_used_at across that user's tokens).

Ordered by created_at DESC so the newest accounts surface first — that's the
shape of the "did anyone I don't know sign up?" question.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from markland.config import get_config
from markland.db import init_db


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=100, help="max users to print")
    parser.add_argument(
        "--since",
        type=int,
        default=None,
        help="only show users created in the last N days",
    )
    args = parser.parse_args()

    conn = init_db(get_config().db_path)

    where = ""
    params: tuple = ()
    if args.since is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=args.since)).isoformat()
        where = "WHERE created_at >= ?"
        params = (cutoff,)

    users = conn.execute(
        f"SELECT id, email, display_name, is_admin, created_at FROM users "
        f"{where} ORDER BY created_at DESC LIMIT ?",
        (*params, args.limit),
    ).fetchall()

    if not users:
        print("no users matched")
        return 0

    header = (
        f"{'id':<22} {'email':<32} {'admin':<5} {'created_at':<28} "
        f"{'docs(pub/total)':<16} {'grants':<7} {'tokens':<7} last_used"
    )
    print(header)
    print("-" * len(header))

    for uid, email, display_name, is_admin, created in users:
        docs_total = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE owner_id=?", (uid,)
        ).fetchone()[0]
        docs_public = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE owner_id=? AND is_public=1",
            (uid,),
        ).fetchone()[0]
        grants_received = conn.execute(
            "SELECT COUNT(*) FROM grants WHERE principal_id=?", (uid,)
        ).fetchone()[0]
        tokens_active = conn.execute(
            "SELECT COUNT(*) FROM tokens "
            "WHERE principal_id=? AND principal_type='user' AND revoked_at IS NULL",
            (uid,),
        ).fetchone()[0]
        last_used = conn.execute(
            "SELECT MAX(last_used_at) FROM tokens "
            "WHERE principal_id=? AND principal_type='user'",
            (uid,),
        ).fetchone()[0] or "-"

        print(
            f"{uid:<22} {email:<32} {('y' if is_admin else 'n'):<5} "
            f"{created:<28} {f'{docs_public}/{docs_total}':<16} "
            f"{grants_received:<7} {tokens_active:<7} {last_used}"
        )

    print(f"\ntotal: {len(users)} user(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
