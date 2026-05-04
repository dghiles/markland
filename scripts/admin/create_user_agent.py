"""Create a user-owned agent and mint an initial agent token.

Use this for "I want an agent that publishes under its own name, owned by my
user account." Different from create_service_agent.py — service agents
cannot publish (see service/docs.py:94-97); user-owned agents can.

Usage:
    /app/.venv/bin/python scripts/admin/create_user_agent.py \\
        --owner-email you@example.com \\
        --display-name "Markland Bot"

Run via:
    flyctl ssh console -a markland -C \\
        "/app/.venv/bin/python scripts/admin/create_user_agent.py \\
         --owner-email you@example.com --display-name 'Markland Bot'"

Prints agent_id + plaintext token. Plaintext is shown ONCE; store it in
.env.local or your secret manager.
"""

from __future__ import annotations

import argparse
import sys

from markland.config import get_config
from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import auth as auth_svc


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a user-owned agent.")
    parser.add_argument("--owner-email", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--token-label", default="initial")
    args = parser.parse_args()

    conn = init_db(get_config().db_path)

    user_row = conn.execute(
        "SELECT id FROM users WHERE email=?", (args.owner_email,)
    ).fetchone()
    if user_row is None:
        print(
            f"error: no user with email={args.owner_email}. "
            "They must sign in via magic link first.",
            file=sys.stderr,
        )
        return 1
    owner_user_id = user_row[0]

    try:
        agent = agents_svc.create_agent(
            conn,
            owner_user_id=owner_user_id,
            display_name=args.display_name,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _, plaintext = auth_svc.create_agent_token(
        conn,
        agent_id=agent.id,
        owner_user_id=owner_user_id,
        label=args.token_label,
    )

    print(f"agent_id:     {agent.id}")
    print(f"display_name: {agent.display_name}")
    print(f"owner:        user:{owner_user_id} ({args.owner_email})")
    print(f"token:        {plaintext}")
    print()
    print("Store the token securely. It will not be shown again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
