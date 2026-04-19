"""Create a service-owned agent and mint an initial agent token.

Usage:
    uv run python scripts/create_service_agent.py \\
        --service-id svc_openclaw \\
        --display-name "OpenClaw" \\
        --token-label "initial"

Prints the new agent_id and plaintext token to stdout. Plaintext is shown
ONCE; store it in the service's secret manager.

No web UI for service agents exists at launch — this script is the only path.
"""

from __future__ import annotations

import argparse
import sys

from markland.config import get_config
from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import auth as auth_svc


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a service-owned agent.")
    parser.add_argument("--service-id", required=True, help="svc_<slug>")
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--token-label", default="initial")
    args = parser.parse_args()

    cfg = get_config()
    conn = init_db(cfg.db_path)

    try:
        agent = agents_svc.create_service_agent(
            conn,
            service_id=args.service_id,
            display_name=args.display_name,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    _, plaintext = auth_svc._create_token_for_agent(
        conn, agent_id=agent.id, label=args.token_label,
    )

    print(f"agent_id:   {agent.id}")
    print(f"owner:      {agent.owner_type}:{agent.owner_id}")
    print(f"token:      {plaintext}")
    print()
    print("Store the token in the service's secret manager. It will not be shown again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
