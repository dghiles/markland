"""User account operations."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str | None
    is_admin: bool
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_user_id() -> str:
    return f"usr_{secrets.token_hex(8)}"


def _row_to_user(row: tuple) -> User:
    return User(
        id=row[0],
        email=row[1],
        display_name=row[2],
        is_admin=bool(row[3]),
        created_at=row[4],
    )


_COLS = "id, email, display_name, is_admin, created_at"


def create_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    display_name: str | None = None,
) -> User:
    """Insert a new user. Email stored lowercased."""
    user = User(
        id=_generate_user_id(),
        email=email.strip().lower(),
        display_name=display_name,
        is_admin=False,
        created_at=_now(),
    )
    conn.execute(
        f"INSERT INTO users ({_COLS}) VALUES (?, ?, ?, ?, ?)",
        (user.id, user.email, user.display_name, 0, user.created_at),
    )
    conn.commit()
    from markland.service import metrics as _metrics
    try:
        _metrics.emit("signup", principal_id=user.id, email=user.email)
    except Exception:
        pass
    return user


def get_user(conn: sqlite3.Connection, user_id: str) -> User | None:
    row = conn.execute(
        f"SELECT {_COLS} FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> User | None:
    row = conn.execute(
        f"SELECT {_COLS} FROM users WHERE email = ?", (email.strip().lower(),)
    ).fetchone()
    return _row_to_user(row) if row else None


def upsert_user_by_email(
    conn: sqlite3.Connection,
    email: str,
    *,
    display_name: str | None = None,
) -> User:
    """Return the existing user with this email, or create one."""
    existing = get_user_by_email(conn, email)
    if existing is not None:
        return existing
    return create_user(conn, email=email, display_name=display_name)
