"""Replace the content of an existing doc with a markdown file from disk.

Usage (run on the Fly machine):
    /app/.venv/bin/python scripts/admin/republish_doc.py \\
        --doc-id <doc_id> \\
        --owner-email <email> \\
        --content-path <path-to-md>

Bypasses MCP — calls service.docs.update directly with a synthesized Principal.
This is admin-only by virtue of running on the Fly machine via SSH.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from markland.config import get_config
from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service.auth import Principal
from markland.service.users import get_user_by_email


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--doc-id", required=True)
    p.add_argument("--owner-email", required=True)
    p.add_argument("--content-path", required=True)
    args = p.parse_args()

    cfg = get_config()
    conn = init_db(cfg.db_path)

    user = get_user_by_email(conn, args.owner_email)
    if user is None:
        print(f"error: no user with email={args.owner_email}", file=sys.stderr)
        return 1

    # Sanity check: user has at least one active token. We don't actually use
    # the token (we're going around MCP), but its presence signals the user
    # is fully wired up — catches "forgot to mint" operator mistakes early.
    row = conn.execute(
        "SELECT id FROM tokens WHERE principal_id=? AND principal_type='user' "
        "AND revoked_at IS NULL ORDER BY created_at DESC LIMIT 1",
        (user.id,),
    ).fetchone()
    if row is None:
        print(
            f"error: {args.owner_email} has no active tokens. "
            f"Mint one with mint_admin_token.py first.",
            file=sys.stderr,
        )
        return 1

    content = Path(args.content_path).read_text(encoding="utf-8")

    principal = Principal(
        principal_id=user.id,
        principal_type="user",
        display_name=user.display_name,
        is_admin=bool(user.is_admin),
        user_id=None,
    )

    # Plan 8 call form: get(conn, doc_id, principal) -> Document
    current = docs_svc.get(conn, args.doc_id, principal)
    if current is None:
        print(f"error: doc {args.doc_id} not found", file=sys.stderr)
        return 1

    updated = docs_svc.update(
        conn,
        doc_id=args.doc_id,
        principal=principal,
        content=content,
        if_version=current.version,
    )
    conn.commit()
    print(
        f"updated doc {updated.id} → version={updated.version} "
        f"title={updated.title!r}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
