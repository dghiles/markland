"""Agent CRUD — user-owned and service-owned agents."""

from __future__ import annotations

import sqlite3

from markland.models import Agent


def _row_to_agent(row) -> Agent:
    return Agent(
        id=row[0],
        display_name=row[1],
        owner_type=row[2],
        owner_id=row[3],
        created_at=row[4],
        revoked_at=row[5],
    )


_AGENT_COLUMNS = "id, display_name, owner_type, owner_id, created_at, revoked_at"


def get_agent(conn: sqlite3.Connection, agent_id: str) -> Agent | None:
    """Return the agent row (active or revoked), or None if missing."""
    row = conn.execute(
        f"SELECT {_AGENT_COLUMNS} FROM agents WHERE id = ?",
        (agent_id,),
    ).fetchone()
    return _row_to_agent(row) if row else None


def create_agent(
    conn: sqlite3.Connection,
    owner_user_id: str,
    display_name: str,
) -> Agent:
    """Create a user-owned agent. Raises ValueError if validation fails."""
    name = (display_name or "").strip()
    if not name:
        raise ValueError("display_name_required")

    user = conn.execute(
        "SELECT id FROM users WHERE id = ?", (owner_user_id,)
    ).fetchone()
    if user is None:
        raise ValueError("user_not_found")

    agent = Agent(
        id=Agent.generate_id(),
        display_name=name,
        owner_type="user",
        owner_id=owner_user_id,
        created_at=Agent.now(),
        revoked_at=None,
    )
    conn.execute(
        "INSERT INTO agents(id, display_name, owner_type, owner_id, created_at, revoked_at) "
        "VALUES (?, ?, 'user', ?, ?, NULL)",
        (agent.id, agent.display_name, agent.owner_id, agent.created_at),
    )
    conn.commit()
    return agent


def create_service_agent(
    conn: sqlite3.Connection,
    service_id: str,
    display_name: str,
) -> Agent:
    """Create a service-owned agent. Admin-only at the caller level; no web UI."""
    name = (display_name or "").strip()
    if not name:
        raise ValueError("display_name_required")
    if not service_id or not service_id.startswith("svc_"):
        raise ValueError("service_id_required")

    agent = Agent(
        id=Agent.generate_id(),
        display_name=name,
        owner_type="service",
        owner_id=service_id,
        created_at=Agent.now(),
        revoked_at=None,
    )
    conn.execute(
        "INSERT INTO agents(id, display_name, owner_type, owner_id, created_at, revoked_at) "
        "VALUES (?, ?, 'service', ?, ?, NULL)",
        (agent.id, agent.display_name, agent.owner_id, agent.created_at),
    )
    conn.commit()
    return agent


def list_agents(conn: sqlite3.Connection, owner_user_id: str) -> list[Agent]:
    """List active (non-revoked) user-owned agents for a given user."""
    rows = conn.execute(
        f"SELECT {_AGENT_COLUMNS} FROM agents "
        "WHERE owner_type = 'user' AND owner_id = ? AND revoked_at IS NULL "
        "ORDER BY created_at DESC",
        (owner_user_id,),
    ).fetchall()
    return [_row_to_agent(r) for r in rows]


def revoke_agent(
    conn: sqlite3.Connection,
    agent_id: str,
    owner_user_id: str,
) -> None:
    """Soft-delete an agent by setting revoked_at. Owner-only."""
    row = conn.execute(
        "SELECT owner_type, owner_id FROM agents WHERE id = ?", (agent_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"agent_not_found: {agent_id}")
    if row[0] != "user" or row[1] != owner_user_id:
        raise PermissionError("not_agent_owner")

    conn.execute(
        "UPDATE agents SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
        (Agent.now(), agent_id),
    )
    conn.commit()


__all__ = [
    "get_agent",
    "create_agent",
    "create_service_agent",
    "list_agents",
    "revoke_agent",
]
