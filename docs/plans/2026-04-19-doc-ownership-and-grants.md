# Document Ownership and Grants — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Introduce real per-doc ownership and per-principal grants. After this plan, every document has an `owner_id`, every non-owner access is authorised by a `grants` row (or public/share-token fallback), and the MCP + HTTP surfaces enforce it uniformly through a new `service/docs.py` layer. Owners can grant `view` / `edit` access to other users by email, revoke it, and list grants — both via `markland_grant` / `markland_revoke` / `markland_list_grants` and the matching `POST/DELETE/GET /api/docs/{id}/grants` routes. The web dashboard gains a "Shared with me" section and a share dialog on the viewer. This is Plan 3 of 10 per `docs/specs/2026-04-19-multi-agent-auth-design.md` §17.

**Architecture:** A new `src/markland/service/docs.py` wraps every doc CRUD call and funnels it through `check_permission(principal, doc_id, action)` implementing §5's resolution order (owner → direct grant → agent inheritance TODO for Plan 4 → public+view → share token via `/d/{token}` → deny-as-404). A parallel `src/markland/service/grants.py` handles grant CRUD and fires a best-effort grantee email via the Plan-1 `EmailClient`. The MCP tools in `src/markland/server.py` and the FastAPI routes under `/api/docs/*` both call into these service modules — neither reaches into `db.py` directly for doc access. The `/d/{share_token}` HTML viewer and `GET /explore` stay exactly as they are — share tokens and public visibility remain separate, parallel surfaces.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, SQLite (WAL), argon2id tokens from Plan 2, Resend via Plan 1's `EmailClient`, Jinja2 templates, pytest.

**Scope excluded (this plan):**
- Agents and agent grants — Plan 4 delivers `agents` table, `agt_…` tokens, and the user-owned-agent inheritance rule (§5 step 3). `service/docs.py` leaves a clearly-marked TODO hook at that step; today it is unreachable because no agent principals exist.
- Invite links — Plan 5 delivers `invites` table, `markland_create_invite`, invite-accept flow, and grant-on-new-user fallback from spec §6.1 step 6.
- Device flow — Plan 6.
- Conflict handling (`version`, `if_version`, `ETag`, `If-Match`, `revisions`) — Plan 8. This plan preserves the existing `update_document` semantics unchanged except for the permission check.
- Presence (`active_principals` in `markland_get`) — Plan 9.
- Audit log and rate limits — Plan 10.
- Richer email templates — Plan 7 refactors the inline HTML this plan ships into proper Jinja templates.

---

## File Structure

**New files:**
- `src/markland/service/docs.py` — permission-aware CRUD wrapping `db.py`; every MCP/HTTP handler calls through here
- `src/markland/service/grants.py` — grant/revoke/list + best-effort grantee email
- `src/markland/service/permissions.py` — pure `check_permission` + `PermissionError` types (kept separate so `service/docs.py` stays thin)
- `src/markland/web/api_grants.py` — FastAPI router for `/api/docs/{id}/grants`
- `src/markland/web/dashboard.py` — `/dashboard` HTML page with "My docs" + "Shared with me"
- `src/markland/web/templates/dashboard.html` — the dashboard template
- `src/markland/web/templates/_share_dialog.html` — Jinja partial for the owner-only share dialog on the viewer
- `scripts/backfill_owners.py` — one-off script to assign `owner_id` on pre-Plan-3 docs
- `tests/test_service_permissions.py` — unit tests for `check_permission`
- `tests/test_service_docs.py` — owner-scoped CRUD + permission denials
- `tests/test_service_grants.py` — grant/revoke/list, user-only, upsert behaviour, email side-effect
- `tests/test_mcp_grants.py` — MCP tools `markland_grant` / `markland_revoke` / `markland_list_grants` + ownership-aware publish/list/get/update/delete
- `tests/test_api_grants.py` — HTTP `GET/POST/DELETE /api/docs/{id}/grants`
- `tests/test_dashboard_shared.py` — "Shared with me" section renders the right docs
- `tests/test_smoke_grants.py` — end-to-end two-user happy path

**Modified files:**
- `src/markland/db.py` — add `owner_id` column + `grants` table + `idx_grants_principal` to `init_db`; add `insert_document_with_owner`, `list_documents_for_principal`, `list_shared_with_principal`, and grants CRUD helpers
- `src/markland/models.py` — add `owner_id: str | None` to `Document`; add `Grant` dataclass
- `src/markland/tools/documents.py` — thin wrappers either removed or redirected at `service/docs.py` (only `_extract_title` stays; the other tools call into `service/docs.py`)
- `src/markland/server.py` — `build_mcp` reworked so every doc tool takes the current `Principal` from `request.state.principal` (Plan 2 puts it there) and calls `service/docs.py`; adds `markland_grant`, `markland_revoke`, `markland_list_grants`
- `src/markland/web/app.py` — register `api_grants` router, mount `/dashboard`, pass `EmailClient` through to services
- `src/markland/web/templates/document.html` — include `_share_dialog.html` when current principal is the doc owner
- `README.md` — append "Ownership & grants" section pointing to `scripts/backfill_owners.py`

**Unchanged:** `config.py`, `web/renderer.py`, `run_app.py`, `service/email.py`, `service/auth.py`, `service/sessions.py`, `service/magic_link.py`, the magic-link + `/settings/tokens` routes, `tests/test_config.py`, `tests/test_auth_middleware.py`, `tests/test_email_service.py`, `tests/test_renderer.py`, the `/d/{share_token}` public viewer route.

---

## Task 1: Schema — `owner_id` column, `grants` table, index

**Files:**
- Modify: `src/markland/db.py`
- Modify: `src/markland/models.py`
- Create: `tests/test_service_permissions.py` (schema smoke portion only; permission logic comes in Task 2)

- [ ] **Step 1: Write the failing test**

Create `tests/test_service_permissions.py` with just the schema portion:

```python
"""Schema + permission tests for Plan 3."""

from markland.db import init_db


def test_documents_has_owner_id_column(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = [row[1] for row in conn.execute("PRAGMA table_info(documents)").fetchall()]
    assert "owner_id" in cols


def test_grants_table_exists_with_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(grants)").fetchall()}
    assert set(cols) == {
        "doc_id",
        "principal_id",
        "principal_type",
        "level",
        "granted_by",
        "granted_at",
    }


def test_grants_primary_key_is_doc_and_principal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    rows = conn.execute("PRAGMA table_info(grants)").fetchall()
    pk_cols = sorted(row[1] for row in rows if row[5] > 0)
    assert pk_cols == ["doc_id", "principal_id"]


def test_idx_grants_principal_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    idx = conn.execute("PRAGMA index_list(grants)").fetchall()
    names = [row[1] for row in idx]
    assert "idx_grants_principal" in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_permissions.py -v`
Expected: FAIL — `grants` table and `owner_id` column do not exist.

- [ ] **Step 3: Extend `models.py`**

Replace `src/markland/models.py` with:

```python
"""Document + grant data models."""

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class Document:
    id: str
    title: str
    content: str
    share_token: str
    created_at: str
    updated_at: str
    is_public: bool = False
    is_featured: bool = False
    owner_id: str | None = None

    @staticmethod
    def generate_id() -> str:
        return secrets.token_hex(8)

    @staticmethod
    def generate_share_token() -> str:
        return secrets.token_urlsafe(16)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()


@dataclass
class Grant:
    doc_id: str
    principal_id: str
    principal_type: str  # 'user' | 'agent'
    level: str  # 'view' | 'edit'
    granted_by: str
    granted_at: str
```

- [ ] **Step 4: Extend `db.py` with the new schema**

Modify `src/markland/db.py` — update `init_db` and add `owner_id` to `_DOC_COLUMNS` + `_row_to_doc`:

```python
"""SQLite database operations for document + grant storage."""

import sqlite3
from pathlib import Path

from markland.models import Document, Grant


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, col_def: str
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
        conn.commit()


def init_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            share_token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_public INTEGER NOT NULL DEFAULT 0,
            is_featured INTEGER NOT NULL DEFAULT 0,
            owner_id TEXT
        )
    """)
    _add_column_if_missing(conn, "documents", "is_public", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "is_featured", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "owner_id", "TEXT")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS grants (
            doc_id TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            level TEXT NOT NULL,
            granted_by TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            PRIMARY KEY (doc_id, principal_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_share_token ON documents(share_token)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_public ON documents(is_public)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_featured ON documents(is_featured)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_owner ON documents(owner_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_grants_principal ON grants(principal_id, doc_id)"
    )
    conn.commit()
    return conn


def _row_to_doc(row: tuple) -> Document:
    return Document(
        id=row[0],
        title=row[1],
        content=row[2],
        share_token=row[3],
        created_at=row[4],
        updated_at=row[5],
        is_public=bool(row[6]),
        is_featured=bool(row[7]),
        owner_id=row[8],
    )


_DOC_COLUMNS = (
    "id, title, content, share_token, created_at, updated_at, "
    "is_public, is_featured, owner_id"
)


def insert_document(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str,
    content: str,
    share_token: str,
    is_public: bool = False,
    owner_id: str | None = None,
) -> str:
    now = Document.now()
    conn.execute(
        f"""
        INSERT INTO documents ({_DOC_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (doc_id, title, content, share_token, now, now, 1 if is_public else 0, owner_id),
    )
    conn.commit()
    return doc_id


def get_document(conn: sqlite3.Connection, doc_id: str) -> Document | None:
    row = conn.execute(
        f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = ?",
        (doc_id,),
    ).fetchone()
    return _row_to_doc(row) if row else None


def get_document_by_token(conn: sqlite3.Connection, token: str) -> Document | None:
    row = conn.execute(
        f"SELECT {_DOC_COLUMNS} FROM documents WHERE share_token = ?",
        (token,),
    ).fetchone()
    return _row_to_doc(row) if row else None


def list_documents(conn: sqlite3.Connection) -> list[Document]:
    rows = conn.execute(
        f"SELECT {_DOC_COLUMNS} FROM documents ORDER BY updated_at DESC"
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def list_documents_for_owner(
    conn: sqlite3.Connection, owner_id: str
) -> list[Document]:
    rows = conn.execute(
        f"""
        SELECT {_DOC_COLUMNS}
        FROM documents
        WHERE owner_id = ?
        ORDER BY updated_at DESC
        """,
        (owner_id,),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def list_documents_for_principal(
    conn: sqlite3.Connection, principal_id: str
) -> list[Document]:
    """Union of owned docs and docs directly granted to this principal_id.

    Agent-inheritance (Plan 4) will expand this to also pull docs granted to
    the agent's owner; today the helper only handles direct membership.
    """
    rows = conn.execute(
        f"""
        SELECT {_DOC_COLUMNS} FROM documents WHERE owner_id = ?
        UNION
        SELECT {', '.join('d.' + c for c in _DOC_COLUMNS.split(', '))}
        FROM documents d
        JOIN grants g ON g.doc_id = d.id
        WHERE g.principal_id = ?
        ORDER BY updated_at DESC
        """,
        (principal_id, principal_id),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def list_shared_with_principal(
    conn: sqlite3.Connection, principal_id: str
) -> list[Document]:
    """Docs where this principal has a grant but is NOT the owner."""
    rows = conn.execute(
        f"""
        SELECT {', '.join('d.' + c for c in _DOC_COLUMNS.split(', '))}
        FROM documents d
        JOIN grants g ON g.doc_id = d.id
        WHERE g.principal_id = ? AND (d.owner_id IS NULL OR d.owner_id != ?)
        ORDER BY d.updated_at DESC
        """,
        (principal_id, principal_id),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def search_documents(conn: sqlite3.Connection, query: str) -> list[Document]:
    pattern = f"%{query}%"
    rows = conn.execute(
        f"""
        SELECT {_DOC_COLUMNS}
        FROM documents
        WHERE title LIKE ? OR content LIKE ?
        ORDER BY updated_at DESC
        """,
        (pattern, pattern),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def search_documents_for_principal(
    conn: sqlite3.Connection, principal_id: str, query: str
) -> list[Document]:
    pattern = f"%{query}%"
    rows = conn.execute(
        f"""
        SELECT {_DOC_COLUMNS} FROM documents
        WHERE owner_id = ? AND (title LIKE ? OR content LIKE ?)
        UNION
        SELECT {', '.join('d.' + c for c in _DOC_COLUMNS.split(', '))}
        FROM documents d JOIN grants g ON g.doc_id = d.id
        WHERE g.principal_id = ? AND (d.title LIKE ? OR d.content LIKE ?)
        ORDER BY updated_at DESC
        """,
        (principal_id, pattern, pattern, principal_id, pattern, pattern),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def list_public_documents(
    conn: sqlite3.Connection,
    query: str | None = None,
    limit: int = 50,
) -> list[Document]:
    q = (query or "").strip()
    if q:
        pattern = f"%{q[:200]}%"
        rows = conn.execute(
            f"""
            SELECT {_DOC_COLUMNS}
            FROM documents
            WHERE is_public = 1 AND (title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (pattern, pattern, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT {_DOC_COLUMNS}
            FROM documents
            WHERE is_public = 1
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_doc(row) for row in rows]


def list_featured_and_recent_public(
    conn: sqlite3.Connection, limit: int = 8
) -> list[Document]:
    rows = conn.execute(
        f"""
        SELECT {_DOC_COLUMNS}
        FROM documents
        WHERE is_public = 1
        ORDER BY is_featured DESC, updated_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def delete_document(conn: sqlite3.Connection, doc_id: str) -> bool:
    conn.execute("DELETE FROM grants WHERE doc_id = ?", (doc_id,))
    cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    return cursor.rowcount > 0


def update_document(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str | None = None,
    content: str | None = None,
) -> Document | None:
    doc = get_document(conn, doc_id)
    if doc is None:
        return None
    new_title = title if title is not None else doc.title
    new_content = content if content is not None else doc.content
    now = Document.now()
    conn.execute(
        "UPDATE documents SET title = ?, content = ?, updated_at = ? WHERE id = ?",
        (new_title, new_content, now, doc_id),
    )
    conn.commit()
    return get_document(conn, doc_id)


def set_visibility(
    conn: sqlite3.Connection, doc_id: str, is_public: bool
) -> Document | None:
    doc = get_document(conn, doc_id)
    if doc is None:
        return None
    now = Document.now()
    conn.execute(
        "UPDATE documents SET is_public = ?, updated_at = ? WHERE id = ?",
        (1 if is_public else 0, now, doc_id),
    )
    conn.commit()
    return get_document(conn, doc_id)


def set_featured(
    conn: sqlite3.Connection, doc_id: str, is_featured: bool
) -> Document | None:
    doc = get_document(conn, doc_id)
    if doc is None:
        return None
    conn.execute(
        "UPDATE documents SET is_featured = ? WHERE id = ?",
        (1 if is_featured else 0, doc_id),
    )
    conn.commit()
    return get_document(conn, doc_id)


# --- Grants CRUD --------------------------------------------------------


def _row_to_grant(row: tuple) -> Grant:
    return Grant(
        doc_id=row[0],
        principal_id=row[1],
        principal_type=row[2],
        level=row[3],
        granted_by=row[4],
        granted_at=row[5],
    )


_GRANT_COLUMNS = "doc_id, principal_id, principal_type, level, granted_by, granted_at"


def upsert_grant(
    conn: sqlite3.Connection,
    doc_id: str,
    principal_id: str,
    principal_type: str,
    level: str,
    granted_by: str,
) -> Grant:
    now = Document.now()
    conn.execute(
        f"""
        INSERT INTO grants ({_GRANT_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(doc_id, principal_id) DO UPDATE SET
            principal_type = excluded.principal_type,
            level = excluded.level,
            granted_by = excluded.granted_by,
            granted_at = excluded.granted_at
        """,
        (doc_id, principal_id, principal_type, level, granted_by, now),
    )
    conn.commit()
    row = conn.execute(
        f"SELECT {_GRANT_COLUMNS} FROM grants WHERE doc_id = ? AND principal_id = ?",
        (doc_id, principal_id),
    ).fetchone()
    return _row_to_grant(row)


def delete_grant(
    conn: sqlite3.Connection, doc_id: str, principal_id: str
) -> bool:
    cursor = conn.execute(
        "DELETE FROM grants WHERE doc_id = ? AND principal_id = ?",
        (doc_id, principal_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def get_grant(
    conn: sqlite3.Connection, doc_id: str, principal_id: str
) -> Grant | None:
    row = conn.execute(
        f"SELECT {_GRANT_COLUMNS} FROM grants WHERE doc_id = ? AND principal_id = ?",
        (doc_id, principal_id),
    ).fetchone()
    return _row_to_grant(row) if row else None


def list_grants_for_doc(
    conn: sqlite3.Connection, doc_id: str
) -> list[Grant]:
    rows = conn.execute(
        f"""
        SELECT {_GRANT_COLUMNS} FROM grants
        WHERE doc_id = ?
        ORDER BY granted_at ASC
        """,
        (doc_id,),
    ).fetchall()
    return [_row_to_grant(row) for row in rows]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_permissions.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Verify existing tests still pass**

Run: `uv run pytest tests/ -v`
Expected: PASS for the full suite. `tests/test_db.py` and `tests/test_documents.py` still work because `Document.owner_id` defaults to `None` and `insert_document` has a new defaulted kwarg.

---

## Task 2: `service/permissions.py` — pure `check_permission`

**Files:**
- Create: `src/markland/service/permissions.py`
- Modify: `tests/test_service_permissions.py`

- [ ] **Step 1: Extend the failing test**

Append to `tests/test_service_permissions.py`:

```python
import pytest

from markland.db import init_db, insert_document, upsert_grant
from markland.models import Document
from markland.service.permissions import (
    NotFound,
    PermissionDenied,
    Principal,
    check_permission,
)


def _seed_doc(conn, *, owner_id: str | None = None, is_public: bool = False) -> str:
    doc_id = Document.generate_id()
    insert_document(
        conn,
        doc_id,
        "Title",
        "body",
        Document.generate_share_token(),
        is_public=is_public,
        owner_id=owner_id,
    )
    return doc_id


def _user(uid: str) -> Principal:
    return Principal(principal_id=uid, principal_type="user", user_id=uid)


def test_owner_can_do_anything(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    p = _user("usr_alice")
    assert check_permission(conn, p, doc_id, "view") == "owner"
    assert check_permission(conn, p, doc_id, "edit") == "owner"
    assert check_permission(conn, p, doc_id, "owner") == "owner"


def test_direct_view_grant_allows_view_denies_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    upsert_grant(conn, doc_id, "usr_bob", "user", "view", "usr_alice")
    p = _user("usr_bob")
    assert check_permission(conn, p, doc_id, "view") == "view"
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "edit")
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "owner")


def test_direct_edit_grant_allows_view_and_edit_denies_manage(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    p = _user("usr_bob")
    assert check_permission(conn, p, doc_id, "view") == "edit"
    assert check_permission(conn, p, doc_id, "edit") == "edit"
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "owner")


def test_public_doc_allows_view_denies_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice", is_public=True)
    p = _user("usr_stranger")
    assert check_permission(conn, p, doc_id, "view") == "public"
    with pytest.raises(PermissionDenied):
        check_permission(conn, p, doc_id, "edit")


def test_no_grant_no_public_denies_with_not_found(tmp_path):
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    p = _user("usr_stranger")
    with pytest.raises(NotFound):
        check_permission(conn, p, doc_id, "view")


def test_missing_doc_raises_not_found(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = _user("usr_alice")
    with pytest.raises(NotFound):
        check_permission(conn, p, "no_such_doc", "view")


def test_agent_inheritance_hook_unreachable_today(tmp_path):
    """Plan 4 will wire owner inheritance for user-owned agents. Today the
    agent code path is unreachable because no agent Principal can be
    constructed from Plan 2's resolve_token. Smoke: supplying an agent-like
    Principal without an agents row still denies cleanly."""
    conn = init_db(tmp_path / "t.db")
    doc_id = _seed_doc(conn, owner_id="usr_alice")
    # Simulate a bare agent principal; Plan 4 will populate owner_id.
    p = Principal(principal_id="agt_future", principal_type="agent", user_id=None)
    with pytest.raises(NotFound):
        check_permission(conn, p, doc_id, "view")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_permissions.py -v`
Expected: FAIL — `markland.service.permissions` does not exist.

- [ ] **Step 3: Implement `service/permissions.py`**

Create `src/markland/service/permissions.py`:

```python
"""Permission resolution per spec §5.

Pure function over (conn, principal, doc_id, action). No mutation, no
side-effects, no I/O beyond the two SELECTs. `service/docs.py` is the
caller that combines this check with the actual CRUD.
"""

from __future__ import annotations

import sqlite3
from typing import Literal

from markland.db import get_document, get_grant
from markland.service.auth import Principal  # canonical Principal (Plan 2)


# NOTE: Principal is imported from markland.service.auth (Plan 2). Do not
# redefine it here — a duplicate class would break isinstance checks and any
# `Principal` attribute added in Plan 2 (e.g. user_id) would silently diverge.


class PermissionError(Exception):
    """Base class for permission failures."""


class NotFound(PermissionError):
    """Return this to the caller — map to 404 / MCP not_found.

    Per spec §12.5, "doesn't exist" and "you lack view access" are
    intentionally indistinguishable to prevent ID enumeration.
    """


class PermissionDenied(PermissionError):
    """Authed and visible, but the action is not allowed (e.g. view-granted
    principal attempting to edit). Map to 403 / MCP forbidden."""


_LEVEL_TO_MAX_ACTION = {
    "view": {"view"},
    "edit": {"view", "edit"},
}


def check_permission(
    conn: sqlite3.Connection,
    principal: Principal,
    doc_id: str,
    action: Literal["view", "edit", "owner"],
) -> str:
    """Resolve permission for `principal` to perform `action` on `doc_id`.

    Returns a string tag identifying *why* access was granted — useful for
    audit/logging and for tests. Tags: 'owner', 'view', 'edit', 'public'.

    Raises:
        NotFound — doc missing OR principal cannot see it (intentional).
        PermissionDenied — principal can see but not perform this action.
    """
    doc = get_document(conn, doc_id)
    if doc is None:
        raise NotFound(f"document {doc_id}")

    # (1) Owner
    if doc.owner_id is not None and principal.user_id == doc.owner_id:
        return "owner"

    # (2) Direct grant (doc, principal_id)
    grant = get_grant(conn, doc_id, principal.principal_id)
    if grant is not None:
        if action in _LEVEL_TO_MAX_ACTION[grant.level]:
            return grant.level
        raise PermissionDenied(
            f"grant level '{grant.level}' does not permit {action}"
        )

    # (3) Agent inheritance — TODO(plan-4): if principal.principal_type == 'agent'
    # and the agent is user-owned, look up a grant (doc_id, principal.user_id)
    # and inherit its level. Today this code path is unreachable because Plan 2
    # only issues user principals; agent tokens arrive in Plan 4.
    # See: docs/specs/2026-04-19-multi-agent-auth-design.md §5 rule (3).

    # (4) Public + view
    if doc.is_public and action == "view":
        return "public"

    # (5) Share-token flow is handled outside this function — `/d/{share_token}`
    # reads the doc directly via `get_document_by_token` and never goes through
    # check_permission.

    # (6) Deny — mask as NotFound to prevent ID enumeration (spec §12.5).
    raise NotFound(f"document {doc_id}")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_permissions.py -v`
Expected: PASS (11 tests total — 4 schema + 7 permission).

---

## Task 3: `service/docs.py` — owner-scoped CRUD

**Files:**
- Create: `src/markland/service/docs.py`
- Create: `tests/test_service_docs.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_docs.py`:

```python
"""Permission-aware doc CRUD."""

import pytest

from markland.db import init_db, upsert_grant
from markland.service import docs as svc
from markland.service.permissions import NotFound, PermissionDenied, Principal


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(principal_id=uid, principal_type="user", user_id=uid)


def test_publish_sets_owner_id_from_principal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    result = svc.publish(conn, BASE, alice, "# Hello\nbody", title=None, public=False)
    assert result["owner_id"] == "usr_alice"
    assert result["title"] == "Hello"


def test_list_returns_owned_and_granted_docs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    owned = svc.publish(conn, BASE, alice, "alice-doc", title="A")["id"]
    bobs = svc.publish(conn, BASE, bob, "bob-doc", title="B")["id"]
    shared = svc.publish(conn, BASE, bob, "shared-doc", title="S")["id"]
    upsert_grant(conn, shared, "usr_alice", "user", "view", "usr_bob")
    ids = {d["id"] for d in svc.list_for_principal(conn, alice)}
    assert ids == {owned, shared}
    assert bobs not in ids


def test_get_as_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    result = svc.get(conn, alice, doc_id)
    assert result["id"] == doc_id
    assert result["content"] == "body"


def test_get_as_view_grantee(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "view", "usr_alice")
    result = svc.get(conn, bob, doc_id)
    assert result["id"] == doc_id


def test_get_denies_stranger_as_not_found(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    eve = _user("usr_eve")
    doc_id = svc.publish(conn, BASE, alice, "body")["id"]
    with pytest.raises(NotFound):
        svc.get(conn, eve, doc_id)


def test_update_requires_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "view", "usr_alice")
    with pytest.raises(PermissionDenied):
        svc.update(conn, BASE, bob, doc_id, content="new")

    # Upgrade to edit
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    updated = svc.update(conn, BASE, bob, doc_id, content="new")
    assert updated["id"] == doc_id


def test_delete_requires_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    with pytest.raises(PermissionDenied):
        svc.delete(conn, bob, doc_id)
    result = svc.delete(conn, alice, doc_id)
    assert result["deleted"] is True


def test_set_visibility_requires_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = svc.publish(conn, BASE, alice, "body", title="T")["id"]
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    with pytest.raises(PermissionDenied):
        svc.set_visibility(conn, BASE, bob, doc_id, True)
    out = svc.set_visibility(conn, BASE, alice, doc_id, True)
    assert out["is_public"] is True


def test_search_scoped_to_visible_docs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    svc.publish(conn, BASE, alice, "secret alpha", title="Alpha")
    bob_doc = svc.publish(conn, BASE, bob, "secret alpha", title="Bravo")["id"]
    hits = svc.search(conn, alice, "alpha")
    ids = {h["id"] for h in hits}
    assert bob_doc not in ids
    assert len(hits) == 1


def test_shared_with_principal_excludes_own_docs(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    owned = svc.publish(conn, BASE, alice, "a", title="A")["id"]
    shared = svc.publish(conn, BASE, bob, "b", title="B")["id"]
    upsert_grant(conn, shared, "usr_alice", "user", "view", "usr_bob")
    ids = {d["id"] for d in svc.list_shared_with(conn, alice)}
    assert ids == {shared}
    assert owned not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_docs.py -v`
Expected: FAIL — `markland.service.docs` does not exist.

- [ ] **Step 3: Implement `service/docs.py`**

Create `src/markland/service/docs.py`:

```python
"""Permission-aware doc CRUD. All MCP and HTTP handlers call through here."""

from __future__ import annotations

import sqlite3

from markland import db
from markland.models import Document
from markland.service.permissions import (
    NotFound,
    PermissionDenied,
    Principal,
    check_permission,
)


def _extract_title(content: str) -> str:
    for line in content.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Untitled"


def _doc_to_summary(doc: Document) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "updated_at": doc.updated_at,
        "is_public": doc.is_public,
        "is_featured": doc.is_featured,
        "owner_id": doc.owner_id,
    }


def _doc_to_full(doc: Document, base_url: str) -> dict:
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content,
        "share_url": f"{base_url}/d/{doc.share_token}",
        "updated_at": doc.updated_at,
        "is_public": doc.is_public,
        "is_featured": doc.is_featured,
        "owner_id": doc.owner_id,
    }


def _resolve_owner_id(principal: Principal) -> str | None:
    """Return the user_id the doc should be owned by.

    For user tokens, this is principal.user_id (== principal.principal_id).
    For agent tokens (Plan 4), this is the agent's owning user_id; service-owned
    agents have no human owner so docs they publish have owner_id=None and
    only the agent itself can access them until a grant is created.
    """
    return principal.user_id


def publish(
    conn: sqlite3.Connection,
    base_url: str,
    principal: Principal,
    content: str,
    title: str | None = None,
    public: bool = False,
) -> dict:
    doc_id = Document.generate_id()
    share_token = Document.generate_share_token()
    resolved_title = title if title else _extract_title(content)
    owner_id = _resolve_owner_id(principal)
    db.insert_document(
        conn,
        doc_id,
        resolved_title,
        content,
        share_token,
        is_public=public,
        owner_id=owner_id,
    )
    return {
        "id": doc_id,
        "title": resolved_title,
        "share_url": f"{base_url}/d/{share_token}",
        "is_public": public,
        "owner_id": owner_id,
    }


def list_for_principal(
    conn: sqlite3.Connection, principal: Principal
) -> list[dict]:
    docs = db.list_documents_for_principal(conn, principal.principal_id)
    return [_doc_to_summary(d) for d in docs]


def list_shared_with(
    conn: sqlite3.Connection, principal: Principal
) -> list[dict]:
    docs = db.list_shared_with_principal(conn, principal.principal_id)
    return [_doc_to_summary(d) for d in docs]


def get(
    conn: sqlite3.Connection, principal: Principal, doc_id: str, base_url: str = ""
) -> dict:
    check_permission(conn, principal, doc_id, "view")
    doc = db.get_document(conn, doc_id)
    assert doc is not None  # check_permission guarantees existence
    return _doc_to_full(doc, base_url)


def search(
    conn: sqlite3.Connection, principal: Principal, query: str
) -> list[dict]:
    docs = db.search_documents_for_principal(conn, principal.principal_id, query)
    return [_doc_to_summary(d) for d in docs]


def share_link(
    conn: sqlite3.Connection,
    base_url: str,
    principal: Principal,
    doc_id: str,
) -> dict:
    check_permission(conn, principal, doc_id, "view")
    doc = db.get_document(conn, doc_id)
    assert doc is not None
    return {"share_url": f"{base_url}/d/{doc.share_token}", "title": doc.title}


def update(
    conn: sqlite3.Connection,
    base_url: str,
    principal: Principal,
    doc_id: str,
    content: str | None = None,
    title: str | None = None,
) -> dict:
    check_permission(conn, principal, doc_id, "edit")
    doc = db.update_document(conn, doc_id, title=title, content=content)
    assert doc is not None
    return {
        "id": doc.id,
        "title": doc.title,
        "share_url": f"{base_url}/d/{doc.share_token}",
        "updated_at": doc.updated_at,
    }


def delete(
    conn: sqlite3.Connection, principal: Principal, doc_id: str
) -> dict:
    check_permission(conn, principal, doc_id, "owner")
    deleted = db.delete_document(conn, doc_id)
    return {"deleted": deleted, "id": doc_id}


def set_visibility(
    conn: sqlite3.Connection,
    base_url: str,
    principal: Principal,
    doc_id: str,
    is_public: bool,
) -> dict:
    check_permission(conn, principal, doc_id, "owner")
    doc = db.set_visibility(conn, doc_id, is_public)
    assert doc is not None
    return {
        "id": doc.id,
        "is_public": doc.is_public,
        "share_url": f"{base_url}/d/{doc.share_token}",
    }


def feature(
    conn: sqlite3.Connection, principal: Principal, doc_id: str, is_featured: bool
) -> dict:
    # Admin-only per spec §3 — enforced at the tool layer via principal.is_admin
    # (Plan 2 carries is_admin on users). This helper trusts its caller.
    doc = db.set_featured(conn, doc_id, is_featured)
    if doc is None:
        raise NotFound(f"document {doc_id}")
    return {
        "id": doc.id,
        "is_featured": doc.is_featured,
        "is_public": doc.is_public,
    }


__all__ = [
    "publish",
    "list_for_principal",
    "list_shared_with",
    "get",
    "search",
    "share_link",
    "update",
    "delete",
    "set_visibility",
    "feature",
    # re-exports for callers
    "NotFound",
    "PermissionDenied",
]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_docs.py -v`
Expected: PASS (10 tests).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS. Existing `tests/test_documents.py` still passes because `tools/documents.py` is untouched so far.

---

## Task 4: `service/grants.py` — grant/revoke/list with email

**Files:**
- Create: `src/markland/service/grants.py`
- Create: `tests/test_service_grants.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_grants.py`:

```python
"""Grant CRUD + best-effort email notifications."""

from unittest.mock import MagicMock

import pytest

from markland.db import init_db, upsert_grant
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.permissions import PermissionDenied, Principal


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(principal_id=uid, principal_type="user", user_id=uid)


def _seed(conn, owner: Principal, *, email_by_uid: dict[str, str] | None = None):
    """Pre-populate users table (Plan 2) with the users these tests reference."""
    email_by_uid = email_by_uid or {}
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()
    return docs_svc.publish(conn, BASE, owner, "body", title="T")["id"]


def test_grant_by_email_creates_row(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    email_client = MagicMock()
    result = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="b@x",
        level="view",
        email_client=email_client,
    )
    assert result["principal_id"] == "usr_bob"
    assert result["principal_type"] == "user"
    assert result["level"] == "view"
    email_client.send.assert_called_once()
    kwargs = email_client.send.call_args.kwargs
    assert kwargs["to"] == "b@x"
    assert "view" in kwargs["subject"].lower() or "view" in kwargs["html"].lower()


def test_grant_rejects_unknown_email(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x"})
    with pytest.raises(grants_svc.GrantTargetNotFound):
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=alice,
            doc_id=doc_id,
            target="nobody@x",
            level="view",
            email_client=MagicMock(),
        )


def test_grant_rejects_agent_id_with_clear_error(tmp_path):
    """Plan 4 will allow `agt_…` targets. Today we refuse with a named error."""
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(conn, alice, email_by_uid={"usr_alice": "a@x"})
    with pytest.raises(grants_svc.AgentGrantsNotSupported):
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=alice,
            doc_id=doc_id,
            target="agt_abc",
            level="edit",
            email_client=MagicMock(),
        )


def test_grant_requires_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    upsert_grant(conn, doc_id, "usr_bob", "user", "edit", "usr_alice")
    with pytest.raises(PermissionDenied):
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=bob,
            doc_id=doc_id,
            target="b@x",
            level="edit",
            email_client=MagicMock(),
        )


def test_grant_upserts_on_reapply(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    mc = MagicMock()
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="view", email_client=mc)
    out = grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                           target="b@x", level="edit", email_client=mc)
    assert out["level"] == "edit"
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1
    assert rows[0]["level"] == "edit"


def test_revoke_removes_row(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="view", email_client=MagicMock())
    result = grants_svc.revoke(
        conn, principal=alice, doc_id=doc_id, principal_id="usr_bob"
    )
    assert result["revoked"] is True
    assert grants_svc.list_grants(conn, principal=alice, doc_id=doc_id) == []


def test_revoke_requires_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="edit", email_client=MagicMock())
    with pytest.raises(PermissionDenied):
        grants_svc.revoke(
            conn, principal=bob, doc_id=doc_id, principal_id="usr_bob"
        )


def test_list_grants_allows_owner_and_edit(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    eve = _user("usr_eve")
    doc_id = _seed(
        conn, alice,
        email_by_uid={
            "usr_alice": "a@x", "usr_bob": "b@x", "usr_eve": "e@x",
        },
    )
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="b@x", level="edit", email_client=MagicMock())
    grants_svc.grant(conn, base_url=BASE, principal=alice, doc_id=doc_id,
                    target="e@x", level="view", email_client=MagicMock())

    assert len(grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)) == 2
    assert len(grants_svc.list_grants(conn, principal=bob, doc_id=doc_id)) == 2
    with pytest.raises(PermissionDenied):
        grants_svc.list_grants(conn, principal=eve, doc_id=doc_id)


def test_email_failure_does_not_fail_grant(tmp_path, caplog):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    mc = MagicMock()
    mc.send.side_effect = RuntimeError("resend exploded")
    out = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="b@x",
        level="view",
        email_client=mc,
    )
    assert out["principal_id"] == "usr_bob"
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1
    assert any("grant email failed" in r.message.lower() for r in caplog.records)


def test_grant_by_principal_id_writes_row_without_permission_check(tmp_path):
    """Internal helper: no owner check, no email — just the upsert.

    Plan 5 (invite-accept) and Plan 4 (agent-id grants) call this directly
    after authorizing the caller by their own means.
    """
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id, _ = _seed(conn, alice, email_by_uid={"usr_bob": "b@x"})
    # Call with a principal who is NOT the doc owner — must still succeed.
    grants_svc.grant_by_principal_id(
        conn,
        doc_id=doc_id,
        principal_id="usr_bob",
        principal_type="user",
        level="view",
        granted_by="system",
    )
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1
    assert rows[0]["principal_id"] == "usr_bob"
    assert rows[0]["level"] == "view"
    assert rows[0]["granted_by"] == "system"


def test_grant_by_principal_id_is_idempotent_and_upserts_level(tmp_path):
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id, _ = _seed(conn, alice, email_by_uid={"usr_bob": "b@x"})
    for level in ("view", "view", "edit"):
        grants_svc.grant_by_principal_id(
            conn,
            doc_id=doc_id,
            principal_id="usr_bob",
            principal_type="user",
            level=level,
            granted_by="usr_alice",
        )
    rows = grants_svc.list_grants(conn, principal=alice, doc_id=doc_id)
    assert len(rows) == 1  # still a single row — idempotent upsert
    assert rows[0]["level"] == "edit"  # last write wins
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_grants.py -v`
Expected: FAIL — `markland.service.grants` does not exist.

- [ ] **Step 3: Implement `service/grants.py`**

Create `src/markland/service/grants.py`:

```python
"""Grants CRUD — owner-only mutations, owner-or-edit list, best-effort email.

Accepts only email targets at this plan. Agent IDs (`agt_…`) raise a named
error; Plan 4 widens the parser.
"""

from __future__ import annotations

import logging
import sqlite3

from markland import db
from markland.service.email import EmailClient
from markland.service.permissions import (
    PermissionDenied,
    Principal,
    check_permission,
)

logger = logging.getLogger("markland.grants")


class GrantTargetNotFound(Exception):
    """Target email has no matching user row."""


class AgentGrantsNotSupported(Exception):
    """`agt_…` target supplied — Plan 4 enables this."""


class InvalidGrantLevel(Exception):
    """Level not in {'view', 'edit'}."""


_VALID_LEVELS = frozenset({"view", "edit"})


def _lookup_user_by_email(conn: sqlite3.Connection, email: str) -> tuple[str, str] | None:
    row = conn.execute(
        "SELECT id, email FROM users WHERE lower(email) = lower(?)",
        (email.strip(),),
    ).fetchone()
    return (row[0], row[1]) if row else None


def _resolve_target(
    conn: sqlite3.Connection, target: str
) -> tuple[str, str, str]:
    """Return (principal_id, principal_type, email)."""
    t = target.strip()
    if t.startswith("agt_"):
        raise AgentGrantsNotSupported(
            "Agent grants arrive in Plan 4. This plan only accepts email addresses."
        )
    if "@" not in t:
        raise GrantTargetNotFound(
            "Grant target must be an email address at this plan."
        )
    match = _lookup_user_by_email(conn, t)
    if match is None:
        # Spec §6.1 step 6 says "fall back to the invite-link flow"; Plan 5
        # wires that. Until then, surface a clean error.
        raise GrantTargetNotFound(
            f"No Markland user with email {t}. Invite links land in Plan 5."
        )
    user_id, email = match
    return user_id, "user", email


def _grant_email_html(*, granter_name: str, title: str, level: str, link: str) -> str:
    return (
        f"<p>{granter_name} shared <strong>{title}</strong> with you "
        f"— <em>{level}</em> access.</p>"
        f"<p><a href=\"{link}\">Open the document</a></p>"
    )


def _granter_display(conn: sqlite3.Connection, principal: Principal) -> str:
    row = conn.execute(
        "SELECT display_name, email FROM users WHERE id = ?",
        (principal.principal_id,),
    ).fetchone()
    if row is None:
        return "Someone"
    display, email = row
    return display or email or "Someone"


def grant_by_principal_id(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    principal_id: str,
    principal_type: str,  # Literal['user','agent']
    level: str,  # Literal['view','edit']
    granted_by: str,
) -> None:
    """Internal helper: idempotent upsert of a grant row.

    No permission check — caller has already authorized (e.g. Plan 5
    invite-accept flow, Plan 4 agent-id grants). No email — caller decides
    whether to notify. Public callers should use `grant(...)` instead.
    """
    if level not in _VALID_LEVELS:
        raise InvalidGrantLevel(f"level must be one of {_VALID_LEVELS}; got {level!r}")
    db.upsert_grant(
        conn,
        doc_id=doc_id,
        principal_id=principal_id,
        principal_type=principal_type,
        level=level,
        granted_by=granted_by,
    )


def grant(
    conn: sqlite3.Connection,
    *,
    base_url: str,
    principal: Principal,
    doc_id: str,
    target: str,
    level: str,
    email_client: EmailClient | None = None,
) -> dict:
    """Owner only. Upserts a grant row and sends a best-effort email.

    `target` is an email address (→ user grant). `agt_…` IDs are rejected at
    this plan and wired in Plan 4 via `grant_by_principal_id`. If
    `email_client` is None, the email step is skipped silently.
    """
    if level not in _VALID_LEVELS:
        raise InvalidGrantLevel(f"level must be one of {_VALID_LEVELS}; got {level!r}")

    check_permission(conn, principal, doc_id, "owner")

    principal_id, principal_type, target_email = _resolve_target(conn, target)

    # Delegate the actual write to the internal helper for a single source
    # of truth on the upsert shape. Re-read the row below for timestamps.
    grant_by_principal_id(
        conn,
        doc_id=doc_id,
        principal_id=principal_id,
        principal_type=principal_type,
        level=level,
        granted_by=principal.principal_id,
    )
    row = db.get_grant(conn, doc_id, principal_id)
    assert row is not None

    doc = db.get_document(conn, doc_id)
    assert doc is not None
    link = f"{base_url}/d/{doc.share_token}"
    granter = _granter_display(conn, principal)
    subject = f"{granter} shared \"{doc.title}\" with you"
    html = _grant_email_html(
        granter_name=granter, title=doc.title, level=level, link=link
    )
    if email_client is not None:
        try:
            email_client.send(to=target_email, subject=subject, html=html)
        except Exception as exc:
            logger.warning(
                "grant email failed for doc=%s target=%s: %s", doc_id, target_email, exc
            )

    return {
        "doc_id": row.doc_id,
        "principal_id": row.principal_id,
        "principal_type": row.principal_type,
        "level": row.level,
        "granted_by": row.granted_by,
        "granted_at": row.granted_at,
    }


def revoke(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
    principal_id: str,
) -> dict:
    check_permission(conn, principal, doc_id, "owner")
    deleted = db.delete_grant(conn, doc_id, principal_id)
    return {"revoked": deleted, "doc_id": doc_id, "principal_id": principal_id}


def list_grants(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
) -> list[dict]:
    """Visible to owner or any principal with edit access on the doc."""
    check_permission(conn, principal, doc_id, "edit")
    rows = db.list_grants_for_doc(conn, doc_id)
    return [
        {
            "doc_id": r.doc_id,
            "principal_id": r.principal_id,
            "principal_type": r.principal_type,
            "level": r.level,
            "granted_by": r.granted_by,
            "granted_at": r.granted_at,
        }
        for r in rows
    ]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_grants.py -v`
Expected: PASS (11 tests — 9 public `grant`/`revoke`/`list_grants` + 2 for `grant_by_principal_id`).

---

## Task 5: Wire doc MCP tools through `service/docs.py`

**Files:**
- Modify: `src/markland/server.py`
- Modify: `src/markland/tools/documents.py` (reduced to `_extract_title` only — moved helpers into `service/docs.py`)
- Create: `tests/test_mcp_grants.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_grants.py`:

```python
"""MCP tools are ownership-aware and surface grant operations."""

from unittest.mock import MagicMock

import pytest

from markland.db import init_db
from markland.server import build_mcp
from markland.service.permissions import Principal


BASE = "https://markland.test"


def _user(uid: str, email: str = "") -> Principal:
    return Principal(principal_id=uid, principal_type="user", user_id=uid)


def _seed_users(conn, **email_by_uid: str) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            display_name TEXT, is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


class _Ctx:
    """Stand-in for FastMCP's Context carrying a Principal.

    The real Plan 2 wiring uses PrincipalMiddleware to set
    request.state.principal. In these unit tests we invoke handler
    functions directly via the harness `build_mcp` returns.
    """

    def __init__(self, principal: Principal):
        self.principal = principal


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    email_client = MagicMock()
    handlers = build_mcp(
        conn, base_url=BASE, email_client=email_client
    ).markland_handlers  # see implementation note in Task 5 Step 3
    return conn, handlers, email_client


def test_publish_sets_owner_from_principal(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    r = h["markland_publish"](_Ctx(alice), content="# t", title=None, public=False)
    assert r["owner_id"] == "usr_alice"


def test_list_returns_only_visible(harness):
    conn, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="a", title="A", public=False)
    h["markland_publish"](_Ctx(bob), content="b", title="B", public=False)
    out = h["markland_list"](_Ctx(alice))
    assert {d["id"] for d in out} == {a["id"]}


def test_get_denies_stranger_as_not_found(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="secret", title="A")
    out = h["markland_get"](_Ctx(bob), doc_id=a["id"])
    assert out == {"error": "not_found"}


def test_update_requires_edit(harness):
    conn, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    out = h["markland_update"](_Ctx(bob), doc_id=a["id"], content="new")
    assert out == {"error": "not_found"}


def test_delete_requires_owner(harness):
    conn, h, ec = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    h["markland_grant"](_Ctx(alice), doc_id=a["id"], principal="b@x", level="edit")
    out = h["markland_delete"](_Ctx(bob), doc_id=a["id"])
    assert out == {"error": "forbidden"}
    out = h["markland_delete"](_Ctx(alice), doc_id=a["id"])
    assert out["deleted"] is True


def test_grant_revoke_list_happy_path(harness):
    _, h, ec = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    grant_out = h["markland_grant"](
        _Ctx(alice), doc_id=a["id"], principal="b@x", level="view"
    )
    assert grant_out["level"] == "view"
    ec.send.assert_called_once()

    listed = h["markland_list_grants"](_Ctx(alice), doc_id=a["id"])
    assert len(listed) == 1 and listed[0]["principal_id"] == "usr_bob"

    revoke_out = h["markland_revoke"](
        _Ctx(alice), doc_id=a["id"], principal="usr_bob"
    )
    assert revoke_out["revoked"] is True
    assert h["markland_list_grants"](_Ctx(alice), doc_id=a["id"]) == []


def test_non_owner_cannot_grant(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    h["markland_grant"](_Ctx(alice), doc_id=a["id"], principal="b@x", level="edit")
    out = h["markland_grant"](
        _Ctx(bob), doc_id=a["id"], principal="b@x", level="edit"
    )
    assert out == {"error": "forbidden"}


def test_grant_with_unknown_email_returns_invalid_argument(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    out = h["markland_grant"](
        _Ctx(alice), doc_id=a["id"], principal="nobody@x", level="view"
    )
    assert out == {"error": "invalid_argument", "reason": "target_not_found"}


def test_grant_with_agent_id_returns_invalid_argument(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    out = h["markland_grant"](
        _Ctx(alice), doc_id=a["id"], principal="agt_future", level="view"
    )
    assert out == {"error": "invalid_argument", "reason": "agent_grants_not_supported"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_grants.py -v`
Expected: FAIL — `build_mcp` doesn't accept `email_client`, doesn't expose `markland_handlers`, and `markland_grant`/`_revoke`/`_list_grants` don't exist.

- [ ] **Step 3: Replace `src/markland/server.py`**

Replace the full file with:

```python
"""Markland MCP Server — publish and share markdown documents.

Every tool resolves the current principal from request state (set by Plan 2's
PrincipalMiddleware) and calls into `service/docs.py` / `service/grants.py`.
Errors are mapped to MCP-friendly dicts: {"error": "not_found" | "forbidden" |
"invalid_argument", "reason": ...}.

`build_mcp` also exposes `.markland_handlers` — a dict of handler callables —
so unit tests can exercise tool logic without standing up an MCP session.
"""

from __future__ import annotations

import logging

from mcp.server.fastmcp import FastMCP

from markland.config import get_config
from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.email import EmailClient
from markland.service.permissions import (
    NotFound,
    PermissionDenied,
    Principal,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("markland")


def _principal_from_ctx(ctx) -> Principal:
    """Ctx surfaces the Principal under .principal (Plan 2 wiring).

    Tests pass a stand-in Context; in production the MCP request path sets
    ctx.request_context.request.state.principal. We accept both shapes for
    test ergonomics.
    """
    if hasattr(ctx, "principal"):
        return ctx.principal
    req = getattr(getattr(ctx, "request_context", None), "request", None)
    if req is not None and hasattr(req.state, "principal"):
        return req.state.principal
    raise RuntimeError("no principal on context — PrincipalMiddleware missing?")


def build_mcp(
    db_conn,
    *,
    base_url: str,
    email_client: EmailClient | None = None,
) -> FastMCP:
    """Build a FastMCP with all Markland tools. Same factory serves stdio + HTTP.

    `email_client` is optional — when None, `markland_grant` skips the
    best-effort email send silently. Later-plan harnesses (Plans 8/9/10)
    can build an MCP without wiring a dispatcher.
    """
    mcp = FastMCP("markland")
    handlers: dict = {}

    def _publish(ctx, content: str, title: str | None = None, public: bool = False):
        p = _principal_from_ctx(ctx)
        return docs_svc.publish(db_conn, base_url, p, content, title=title, public=public)

    def _list(ctx):
        p = _principal_from_ctx(ctx)
        return docs_svc.list_for_principal(db_conn, p)

    def _get(ctx, doc_id: str):
        p = _principal_from_ctx(ctx)
        try:
            return docs_svc.get(db_conn, p, doc_id, base_url=base_url)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _search(ctx, query: str):
        p = _principal_from_ctx(ctx)
        return docs_svc.search(db_conn, p, query)

    def _share(ctx, doc_id: str):
        p = _principal_from_ctx(ctx)
        try:
            return docs_svc.share_link(db_conn, base_url, p, doc_id)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _update(ctx, doc_id: str, content: str | None = None, title: str | None = None):
        p = _principal_from_ctx(ctx)
        try:
            return docs_svc.update(
                db_conn, base_url, p, doc_id, content=content, title=title
            )
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _delete(ctx, doc_id: str):
        p = _principal_from_ctx(ctx)
        try:
            return docs_svc.delete(db_conn, p, doc_id)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _set_visibility(ctx, doc_id: str, public: bool):
        p = _principal_from_ctx(ctx)
        try:
            return docs_svc.set_visibility(db_conn, base_url, p, doc_id, public)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _feature(ctx, doc_id: str, featured: bool = True):
        p = _principal_from_ctx(ctx)
        # Admin-only at launch (spec §3). Plan 2 exposes is_admin on users —
        # we query it via the user's principal_id. Non-admins get forbidden.
        row = db_conn.execute(
            "SELECT is_admin FROM users WHERE id = ?", (p.principal_id,)
        ).fetchone()
        if not row or not row[0]:
            return {"error": "forbidden"}
        try:
            return docs_svc.feature(db_conn, p, doc_id, featured)
        except NotFound:
            return {"error": "not_found"}

    def _grant(ctx, doc_id: str, principal: str, level: str):
        p = _principal_from_ctx(ctx)
        try:
            return grants_svc.grant(
                db_conn,
                base_url=base_url,
                principal=p,
                doc_id=doc_id,
                target=principal,
                level=level,
                email_client=email_client,
            )
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}
        except grants_svc.GrantTargetNotFound:
            return {"error": "invalid_argument", "reason": "target_not_found"}
        except grants_svc.AgentGrantsNotSupported:
            return {"error": "invalid_argument", "reason": "agent_grants_not_supported"}
        except grants_svc.InvalidGrantLevel:
            return {"error": "invalid_argument", "reason": "invalid_level"}

    def _revoke(ctx, doc_id: str, principal: str):
        p = _principal_from_ctx(ctx)
        # Accept either an email or a principal_id. Emails are resolved here
        # for UX symmetry with markland_grant.
        pid = principal.strip()
        if "@" in pid:
            row = db_conn.execute(
                "SELECT id FROM users WHERE lower(email) = lower(?)", (pid,)
            ).fetchone()
            if row is None:
                return {"error": "invalid_argument", "reason": "target_not_found"}
            pid = row[0]
        try:
            return grants_svc.revoke(
                db_conn, principal=p, doc_id=doc_id, principal_id=pid
            )
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    def _list_grants(ctx, doc_id: str):
        p = _principal_from_ctx(ctx)
        try:
            return grants_svc.list_grants(db_conn, principal=p, doc_id=doc_id)
        except NotFound:
            return {"error": "not_found"}
        except PermissionDenied:
            return {"error": "forbidden"}

    @mcp.tool()
    def markland_publish(ctx, content: str, title: str | None = None, public: bool = False) -> dict:
        """Publish a markdown document owned by the current principal."""
        return _publish(ctx, content, title=title, public=public)

    @mcp.tool()
    def markland_list(ctx) -> list[dict]:
        """List docs where the current principal is owner or has a grant."""
        return _list(ctx)

    @mcp.tool()
    def markland_get(ctx, doc_id: str) -> dict:
        """Get a document. Requires view access."""
        return _get(ctx, doc_id)

    @mcp.tool()
    def markland_search(ctx, query: str) -> list[dict]:
        """Search docs the current principal can view."""
        return _search(ctx, query)

    @mcp.tool()
    def markland_share(ctx, doc_id: str) -> dict:
        """Get the shareable link for a document. Requires view access."""
        return _share(ctx, doc_id)

    @mcp.tool()
    def markland_update(
        ctx, doc_id: str, content: str | None = None, title: str | None = None
    ) -> dict:
        """Update a document's content or title. Requires edit access."""
        return _update(ctx, doc_id, content=content, title=title)

    @mcp.tool()
    def markland_delete(ctx, doc_id: str) -> dict:
        """Delete a document. Owner only."""
        return _delete(ctx, doc_id)

    @mcp.tool()
    def markland_set_visibility(ctx, doc_id: str, public: bool) -> dict:
        """Promote to /explore (public) or demote to unlisted. Owner only."""
        return _set_visibility(ctx, doc_id, public)

    @mcp.tool()
    def markland_feature(ctx, doc_id: str, featured: bool = True) -> dict:
        """Pin or unpin a doc on the landing page hero. Admin only."""
        return _feature(ctx, doc_id, featured)

    @mcp.tool()
    def markland_grant(ctx, doc_id: str, principal: str, level: str) -> dict:
        """Grant view or edit access. Owner only. `principal` is an email."""
        return _grant(ctx, doc_id, principal, level)

    @mcp.tool()
    def markland_revoke(ctx, doc_id: str, principal: str) -> dict:
        """Revoke a grant. Owner only. `principal` may be an email or usr_ id."""
        return _revoke(ctx, doc_id, principal)

    @mcp.tool()
    def markland_list_grants(ctx, doc_id: str) -> list[dict]:
        """List grants on a document. Requires edit or owner."""
        return _list_grants(ctx, doc_id)

    handlers.update(
        markland_publish=_publish,
        markland_list=_list,
        markland_get=_get,
        markland_search=_search,
        markland_share=_share,
        markland_update=_update,
        markland_delete=_delete,
        markland_set_visibility=_set_visibility,
        markland_feature=_feature,
        markland_grant=_grant,
        markland_revoke=_revoke,
        markland_list_grants=_list_grants,
    )
    mcp.markland_handlers = handlers  # type: ignore[attr-defined]
    return mcp


if __name__ == "__main__":
    config = get_config()
    db_conn = init_db(config.db_path)
    email_client = EmailClient(
        api_key=config.resend_api_key, from_email=config.resend_from_email
    )
    logger.info("Starting Markland MCP server (stdio, db: %s)", config.db_path)
    mcp_instance = build_mcp(
        db_conn, base_url=config.base_url, email_client=email_client
    )
    mcp_instance.run()
```

- [ ] **Step 4: Reduce `tools/documents.py`**

Replace `src/markland/tools/documents.py` with a shim that re-exports `service/docs.py` (keeps any legacy callers working until they migrate; remove the file entirely in Plan 10):

```python
"""DEPRECATED in Plan 3 — use `markland.service.docs` directly.

This module now re-exports the service-layer functions under their old names
so older imports (if any) keep working. New code must call
`markland.service.docs` and supply a Principal.
"""

from markland.service.docs import (  # noqa: F401
    _extract_title,
    delete as _delete,
    feature as _feature,
    get as _get,
    list_for_principal as _list,
    publish as _publish,
    search as _search,
    set_visibility as _set_visibility,
    share_link as _share,
    update as _update,
)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_mcp_grants.py -v`
Expected: PASS (9 tests).

- [ ] **Step 6: Update legacy test file if needed**

Run: `uv run pytest tests/test_documents.py -v`

If it fails because the old `tools/documents.py` signatures changed, rewrite affected tests to construct a `Principal` and call `markland.service.docs` directly. The existing test coverage is duplicated by `tests/test_service_docs.py`; acceptable resolution is to delete `tests/test_documents.py` entirely (its assertions about ownerless docs no longer match Plan 3 semantics). Record the deletion in the commit-equivalent verification below.

- [ ] **Step 7: Full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS.

---

## Task 6: HTTP grant routes

**Files:**
- Create: `src/markland/web/api_grants.py`
- Modify: `src/markland/web/app.py`
- Create: `tests/test_api_grants.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_api_grants.py`:

```python
"""HTTP endpoints for grant CRUD."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.permissions import Principal
from markland.web.app import create_app


BASE = "https://markland.test"


class _PrincipalInjector:
    """Test middleware: set request.state.principal from a header."""

    def __init__(self, app, *, by_token: dict[str, Principal]):
        self.app = app
        self.by_token = by_token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode()
            if auth.startswith("Bearer "):
                tok = auth[7:]
                if tok in self.by_token:
                    scope.setdefault("state", {})["principal"] = self.by_token[tok]
        await self.app(scope, receive, send)


def _seed_users(conn, **email_by_uid: str) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            display_name TEXT, is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    alice = Principal("usr_alice", "user", "usr_alice")
    bob = Principal("usr_bob", "user", "usr_bob")
    email_client = MagicMock()
    app = create_app(
        conn,
        mount_mcp=False,
        admin_token="",
        base_url=BASE,
        email_client=email_client,
        test_principal_by_token={"alice": alice, "bob": bob},
    )
    return TestClient(app), conn, email_client


def _publish(client_, token: str, *, title="T", content="body") -> str:
    r = client_.post(
        "/api/docs",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": title, "content": content},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_post_grants_creates_row_and_emails(client):
    c, _, ec = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "view"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["principal_id"] == "usr_bob"
    assert body["level"] == "view"
    ec.send.assert_called_once()


def test_get_grants_requires_edit_or_owner(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    r = c.get(
        f"/api/docs/{doc_id}/grants", headers={"Authorization": "Bearer bob"}
    )
    assert r.status_code == 404

    c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "edit"},
    )
    r = c.get(
        f"/api/docs/{doc_id}/grants", headers={"Authorization": "Bearer bob"}
    )
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_delete_grant_requires_owner(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "b@x", "level": "view"},
    )
    r = c.delete(
        f"/api/docs/{doc_id}/grants/usr_bob",
        headers={"Authorization": "Bearer bob"},
    )
    # Bob is not the owner — 404 (spec §12.5 masks forbidden as not_found
    # for doc-level auth failures). A grant can still have its own row-level
    # forbidden, but the owner-only mutation API treats it uniformly.
    assert r.status_code in (403, 404)
    r = c.delete(
        f"/api/docs/{doc_id}/grants/usr_bob",
        headers={"Authorization": "Bearer alice"},
    )
    assert r.status_code == 200
    assert r.json() == {"revoked": True, "doc_id": doc_id, "principal_id": "usr_bob"}


def test_post_grant_unknown_email_returns_400(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer alice"},
        json={"principal": "nobody@x", "level": "view"},
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_argument"


def test_post_grant_on_foreign_doc_returns_404(client):
    c, conn, _ = client
    doc_id = _publish(c, "alice")
    r = c.post(
        f"/api/docs/{doc_id}/grants",
        headers={"Authorization": "Bearer bob"},
        json={"principal": "b@x", "level": "view"},
    )
    assert r.status_code == 404


def test_unauthenticated_returns_401(client):
    c, _, _ = client
    doc_id = _publish(c, "alice")
    r = c.get(f"/api/docs/{doc_id}/grants")
    assert r.status_code == 401
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_grants.py -v`
Expected: FAIL — `/api/docs/*` grant routes don't exist and `create_app` doesn't accept `test_principal_by_token` / `email_client`.

- [ ] **Step 3: Write the router**

Create `src/markland/web/api_grants.py`:

```python
"""FastAPI routes for per-doc grants.

Mounted by `create_app`. Depends on a Principal being attached to
request.state.principal (Plan 2's PrincipalMiddleware). Falls through to 401
if absent.
"""

from __future__ import annotations

import sqlite3
from typing import Callable

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import JSONResponse

from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.email import EmailClient
from markland.service.permissions import NotFound, PermissionDenied, Principal


def _principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise HTTPException(status_code=401, detail={"error": "unauthenticated"})
    return principal


def build_router(
    *,
    conn: sqlite3.Connection,
    base_url: str,
    email_client: EmailClient,
) -> APIRouter:
    r = APIRouter(prefix="/api")

    @r.post("/docs")
    def publish(request: Request, body: dict = Body(...)):
        p = _principal(request)
        content = body.get("content", "")
        title = body.get("title")
        public = bool(body.get("public", False))
        return docs_svc.publish(conn, base_url, p, content, title=title, public=public)

    @r.get("/docs/{doc_id}/grants")
    def list_grants(doc_id: str, request: Request):
        p = _principal(request)
        try:
            return grants_svc.list_grants(conn, principal=p, doc_id=doc_id)
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            # Docs are visible but grants are view-level restricted — treat as 404
            # for consistency with the "mask forbidden as not-found" principle.
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    @r.post("/docs/{doc_id}/grants")
    def create_grant(doc_id: str, request: Request, body: dict = Body(...)):
        p = _principal(request)
        target = body.get("principal", "")
        level = body.get("level", "")
        try:
            return grants_svc.grant(
                conn,
                base_url=base_url,
                principal=p,
                doc_id=doc_id,
                target=target,
                level=level,
                email_client=email_client,
            )
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except (
            grants_svc.GrantTargetNotFound,
            grants_svc.AgentGrantsNotSupported,
            grants_svc.InvalidGrantLevel,
        ) as exc:
            return JSONResponse(
                {"error": "invalid_argument", "reason": exc.__class__.__name__},
                status_code=400,
            )

    @r.delete("/docs/{doc_id}/grants/{principal_id}")
    def delete_grant(doc_id: str, principal_id: str, request: Request):
        p = _principal(request)
        try:
            return grants_svc.revoke(
                conn, principal=p, doc_id=doc_id, principal_id=principal_id
            )
        except NotFound:
            raise HTTPException(status_code=404, detail={"error": "not_found"})
        except PermissionDenied:
            raise HTTPException(status_code=404, detail={"error": "not_found"})

    return r


__all__ = ["build_router"]
```

- [ ] **Step 4: Extend `create_app`**

Modify `src/markland/web/app.py` — the signature becomes:

```python
def create_app(
    db_conn: sqlite3.Connection,
    *,
    mount_mcp: bool = False,
    admin_token: str = "",
    base_url: str = "",
    email_client: "EmailClient | None" = None,
    test_principal_by_token: dict | None = None,
) -> FastAPI:
```

Inside the body, after the existing viewer routes are registered:

```python
    from markland.service.email import EmailClient
    from markland.web.api_grants import build_router as build_grants_router

    if email_client is None:
        email_client = EmailClient(api_key="", from_email="noreply@markland.dev")

    # Test-only principal injection: Plan 2 supplies the real
    # PrincipalMiddleware; here we accept a header→Principal map.
    if test_principal_by_token:
        @app.middleware("http")
        async def _inject_principal(request, call_next):
            auth = request.headers.get("authorization", "")
            if auth.startswith("Bearer "):
                tok = auth[7:]
                if tok in test_principal_by_token:
                    request.state.principal = test_principal_by_token[tok]
            return await call_next(request)

    app.include_router(build_grants_router(
        conn=db_conn, base_url=base_url, email_client=email_client,
    ))
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_api_grants.py -v`
Expected: PASS (6 tests).

---

## Task 7: "Shared with me" dashboard section

**Files:**
- Create: `src/markland/web/dashboard.py`
- Create: `src/markland/web/templates/dashboard.html`
- Modify: `src/markland/web/app.py` (mount `/dashboard`)
- Create: `tests/test_dashboard_shared.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dashboard_shared.py`:

```python
"""Dashboard lists My docs and Shared-with-me."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, upsert_grant
from markland.service import docs as docs_svc
from markland.service.permissions import Principal
from markland.web.app import create_app


BASE = "https://markland.test"


def _seed_users(conn, **email_by_uid: str) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            display_name TEXT, is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name, created_at) "
            "VALUES (?, ?, ?, '2026-01-01')",
            (uid, email, email.split("@")[0]),
        )
    conn.commit()


@pytest.fixture
def client(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    alice = Principal("usr_alice", "user", "usr_alice")
    bob = Principal("usr_bob", "user", "usr_bob")
    app = create_app(
        conn, mount_mcp=False, admin_token="", base_url=BASE,
        email_client=MagicMock(),
        test_principal_by_token={"alice": alice, "bob": bob},
    )
    return TestClient(app), conn, alice, bob


def test_dashboard_unauthed_redirects_or_401(client):
    c, *_ = client
    r = c.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 401)


def test_dashboard_shows_owned_and_shared(client):
    c, conn, alice, bob = client
    owned = docs_svc.publish(conn, BASE, alice, "x", title="OwnedByAlice")["id"]
    shared = docs_svc.publish(conn, BASE, bob, "y", title="OwnedByBob")["id"]
    upsert_grant(conn, shared, "usr_alice", "user", "view", "usr_bob")
    bob_private = docs_svc.publish(conn, BASE, bob, "z", title="NotShared")["id"]

    r = c.get("/dashboard", headers={"Authorization": "Bearer alice"})
    assert r.status_code == 200
    body = r.text
    assert "OwnedByAlice" in body
    assert "OwnedByBob" in body
    assert "NotShared" not in body
    # Sections
    assert "Shared with me" in body or "shared-with-me" in body.lower()


def test_dashboard_empty_sections_render(client):
    c, _, alice, _ = client
    r = c.get("/dashboard", headers={"Authorization": "Bearer alice"})
    assert r.status_code == 200
    assert "no documents yet" in r.text.lower() or "nothing here yet" in r.text.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_dashboard_shared.py -v`
Expected: FAIL — `/dashboard` route doesn't exist.

- [ ] **Step 3: Write the template**

Create `src/markland/web/templates/dashboard.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>Markland — Dashboard</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 48rem; margin: 2rem auto; padding: 0 1rem; }
      h1 { font-size: 1.6rem; }
      h2 { font-size: 1.2rem; margin-top: 2.5rem; border-bottom: 1px solid #ddd; padding-bottom: .25rem; }
      ul { list-style: none; padding: 0; }
      li { padding: .5rem 0; border-bottom: 1px solid #eee; }
      .empty { color: #888; font-style: italic; }
      .meta { color: #666; font-size: .85rem; }
    </style>
  </head>
  <body>
    <h1>Your documents</h1>

    <h2>My documents</h2>
    {% if owned %}
      <ul id="my-docs">
        {% for d in owned %}
          <li>
            <a href="/d/{{ d.share_token }}">{{ d.title }}</a>
            <span class="meta">· updated {{ d.updated_at }}</span>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="empty">No documents yet. Publish one via MCP or the API.</p>
    {% endif %}

    <h2 id="shared-with-me">Shared with me</h2>
    {% if shared %}
      <ul>
        {% for d in shared %}
          <li>
            <a href="/d/{{ d.share_token }}">{{ d.title }}</a>
            <span class="meta">· from {{ d.owner_display }} · updated {{ d.updated_at }}</span>
          </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class="empty">Nothing here yet. Ask a collaborator to share a doc with you.</p>
    {% endif %}
  </body>
</html>
```

- [ ] **Step 4: Write the route module**

Create `src/markland/web/dashboard.py`:

```python
"""Authenticated /dashboard page — My docs + Shared with me."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.db import (
    get_document_by_token,  # noqa: F401 (kept for future)
    list_documents_for_owner,
    list_shared_with_principal,
)
from markland.service.permissions import Principal


def build_router(*, conn: sqlite3.Connection) -> APIRouter:
    r = APIRouter()
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("dashboard.html")

    def _owner_display(owner_id: str | None) -> str:
        if not owner_id:
            return "unknown"
        row = conn.execute(
            "SELECT display_name, email FROM users WHERE id = ?", (owner_id,)
        ).fetchone()
        if row is None:
            return owner_id
        return row[0] or row[1] or owner_id

    @r.get("/dashboard", response_class=HTMLResponse)
    def dashboard(request: Request):
        principal: Principal | None = getattr(request.state, "principal", None)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        owned_docs = list_documents_for_owner(conn, principal.principal_id)
        shared_docs = list_shared_with_principal(conn, principal.principal_id)

        owned = [
            {
                "title": d.title,
                "share_token": d.share_token,
                "updated_at": d.updated_at,
            }
            for d in owned_docs
        ]
        shared = [
            {
                "title": d.title,
                "share_token": d.share_token,
                "updated_at": d.updated_at,
                "owner_display": _owner_display(d.owner_id),
            }
            for d in shared_docs
        ]
        return HTMLResponse(tpl.render(owned=owned, shared=shared))

    return r


__all__ = ["build_router"]
```

- [ ] **Step 5: Mount in `create_app`**

In `src/markland/web/app.py`, after `app.include_router(build_grants_router(...))`:

```python
    from markland.web.dashboard import build_router as build_dashboard_router
    app.include_router(build_dashboard_router(conn=db_conn))
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_dashboard_shared.py -v`
Expected: PASS (3 tests).

---

## Task 8: Share dialog on the viewer for owners

**Files:**
- Create: `src/markland/web/templates/_share_dialog.html`
- Modify: `src/markland/web/templates/document.html`
- Modify: `src/markland/web/app.py` — viewer passes `owner_view=True|False` and existing grants to the template
- Modify: `tests/test_web.py` (append new assertions)

- [ ] **Step 1: Extend the failing test**

Append to `tests/test_web.py` (create the file if it was removed; this assumes the existing test file pattern). Append:

```python
def test_share_dialog_shown_for_owner_only(tmp_path):
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from markland.db import init_db
    from markland.service import docs as docs_svc
    from markland.service.permissions import Principal
    from markland.web.app import create_app

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, "
        "display_name TEXT, is_admin INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES ('usr_alice', 'a@x', '2026-01-01')"
    )
    conn.commit()
    alice = Principal("usr_alice", "user", "usr_alice")
    stranger = Principal("usr_eve", "user", "usr_eve")

    app = create_app(
        conn, mount_mcp=False, admin_token="",
        base_url="https://markland.test",
        email_client=MagicMock(),
        test_principal_by_token={"alice": alice, "eve": stranger},
    )
    c = TestClient(app)

    pub = docs_svc.publish(conn, "https://markland.test", alice, "body", title="T", public=True)
    share_token = pub["share_url"].rsplit("/", 1)[-1]

    # Owner sees the share dialog
    r_owner = c.get(f"/d/{share_token}", headers={"Authorization": "Bearer alice"})
    assert r_owner.status_code == 200
    assert 'id="share-dialog"' in r_owner.text

    # Stranger (public doc) can view but dialog is hidden
    r_eve = c.get(f"/d/{share_token}", headers={"Authorization": "Bearer eve"})
    assert r_eve.status_code == 200
    assert 'id="share-dialog"' not in r_eve.text

    # Anonymous (public doc) also no dialog
    r_anon = c.get(f"/d/{share_token}")
    assert r_anon.status_code == 200
    assert 'id="share-dialog"' not in r_anon.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v`
Expected: FAIL — the template has no `#share-dialog` element.

- [ ] **Step 3: Write the share-dialog partial**

Create `src/markland/web/templates/_share_dialog.html`:

```html
<section id="share-dialog" style="border:1px solid #ccc;padding:1rem;margin:1rem 0;">
  <h3 style="margin-top:0;">Share</h3>
  <form id="share-form">
    <label>
      Email
      <input type="email" name="principal" placeholder="alice@example.com" required />
    </label>
    <label>
      Level
      <select name="level">
        <option value="view">view</option>
        <option value="edit">edit</option>
      </select>
    </label>
    <button type="submit">Grant</button>
  </form>
  <ul id="grants-list">
    {% for g in grants %}
      <li data-principal="{{ g.principal_id }}">
        {{ g.principal_id }} · {{ g.level }}
        <button class="revoke" data-principal="{{ g.principal_id }}">revoke</button>
      </li>
    {% endfor %}
  </ul>
  <script>
    (function () {
      const docId = {{ doc_id|tojson }};
      const form = document.getElementById("share-form");
      const list = document.getElementById("grants-list");
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const fd = new FormData(form);
        const body = { principal: fd.get("principal"), level: fd.get("level") };
        const r = await fetch(`/api/docs/${docId}/grants`, {
          method: "POST",
          headers: { "content-type": "application/json" },
          credentials: "include",
          body: JSON.stringify(body),
        });
        if (r.ok) { location.reload(); }
        else { alert(`Grant failed: ${r.status}`); }
      });
      list.addEventListener("click", async (ev) => {
        const btn = ev.target.closest(".revoke");
        if (!btn) return;
        const pid = btn.getAttribute("data-principal");
        const r = await fetch(`/api/docs/${docId}/grants/${pid}`, {
          method: "DELETE", credentials: "include",
        });
        if (r.ok) { location.reload(); }
      });
    })();
  </script>
</section>
```

- [ ] **Step 4: Modify `document.html`**

Open `src/markland/web/templates/document.html` and insert the following near the top of the rendered body content (adjust placement to match the existing template — the exact line-location is template-specific; the semantics are "render the partial only when the context flag is on"):

```html
{% if is_owner %}
  {% include "_share_dialog.html" %}
{% endif %}
```

- [ ] **Step 5: Pass owner context from the viewer**

Modify the `view_document` handler in `src/markland/web/app.py`. Replace its body with:

```python
    @app.get("/d/{share_token}", response_class=HTMLResponse)
    def view_document(share_token: str, request: Request):
        doc = get_document_by_token(db_conn, share_token)
        if doc is None:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Document not found</h1></body></html>",
                status_code=404,
            )
        principal = getattr(request.state, "principal", None)
        is_owner = bool(
            principal and doc.owner_id and principal.user_id == doc.owner_id
        )
        grants_for_template: list = []
        if is_owner:
            from markland.db import list_grants_for_doc
            grants_for_template = [
                {"principal_id": g.principal_id, "level": g.level}
                for g in list_grants_for_doc(db_conn, doc.id)
            ]
        content_html = render_markdown(doc.content)
        html = document_tpl.render(
            title=doc.title,
            content_html=content_html,
            created_at=doc.created_at,
            is_owner=is_owner,
            grants=grants_for_template,
            doc_id=doc.id,
        )
        return HTMLResponse(html)
```

Also add `from fastapi import Request` to the top of `app.py` if it is not already imported.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_web.py -v`
Expected: PASS including the new share-dialog test.

---

## Task 9: Backfill script for pre-Plan-3 docs

**Files:**
- Create: `scripts/backfill_owners.py`
- Modify: `README.md`

Rationale: Plans 1 & 2 stored docs with no `owner_id`. On first Plan 3 deploy those docs are orphaned — nobody owns them, and the permission resolver falls through to 404 for every principal. Per the spec §10.3 ("no automated migration, hosted starts fresh") this is expected: the hosted DB should be fresh. If a Plan-1/2 deploy already accumulated real data, this script reassigns those docs to the configured admin user.

- [ ] **Step 1: Write the script**

Create `scripts/backfill_owners.py`:

```python
"""Backfill documents.owner_id for pre-Plan-3 docs.

Usage:
  MARKLAND_DATA_DIR=/data BACKFILL_OWNER_EMAIL=admin@markland.dev \
    uv run python scripts/backfill_owners.py [--dry-run]

Looks up the user by email and sets owner_id on every documents row where
owner_id IS NULL. Prints the count. Idempotent — running twice is a no-op.
"""

from __future__ import annotations

import argparse
import os
import sys

from markland.config import get_config
from markland.db import init_db


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    email = os.environ.get("BACKFILL_OWNER_EMAIL", "").strip()
    if not email:
        print(
            "set BACKFILL_OWNER_EMAIL to the email of the user that should own "
            "all orphaned docs",
            file=sys.stderr,
        )
        return 2

    config = get_config()
    conn = init_db(config.db_path)
    row = conn.execute(
        "SELECT id FROM users WHERE lower(email) = lower(?)", (email,)
    ).fetchone()
    if row is None:
        print(
            f"no user with email {email} — create the account first, then re-run",
            file=sys.stderr,
        )
        return 1
    owner_id = row[0]

    orphan_count = conn.execute(
        "SELECT COUNT(*) FROM documents WHERE owner_id IS NULL"
    ).fetchone()[0]
    print(f"found {orphan_count} orphaned docs; target owner_id={owner_id}")
    if orphan_count == 0:
        return 0
    if args.dry_run:
        print("dry-run; no writes")
        return 0
    conn.execute(
        "UPDATE documents SET owner_id = ? WHERE owner_id IS NULL", (owner_id,)
    )
    conn.commit()
    print(f"assigned owner_id={owner_id} to {orphan_count} docs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Append a README note**

Append to `README.md`:

```markdown

## Ownership & grants (Plan 3)

Every document has an `owner_id` and per-principal grants in the `grants`
table. New docs get `owner_id` set from the authenticated principal
automatically. If you are upgrading a host from Plans 1/2 and have live
documents in the DB, run the backfill:

```bash
BACKFILL_OWNER_EMAIL=admin@markland.dev \
  uv run python scripts/backfill_owners.py
```

The hosted deploy assumes a fresh DB per the launch spec §10.3; this script
exists only for pre-existing installs.
```

- [ ] **Step 3: Verification — dry-run smoke**

Run locally:
```bash
MARKLAND_DATA_DIR=/tmp/markland-test BACKFILL_OWNER_EMAIL=nobody@test \
  uv run python scripts/backfill_owners.py --dry-run
```
Expected output: either "no user with email nobody@test" (exit 1 — the account must exist), or "found 0 orphaned docs" (exit 0). Both are acceptable end-states.

---

## Task 10: Grant email — end-to-end best-effort test

**Files:**
- Modify: `tests/test_service_grants.py` (already covers best-effort; this task adds a real-template assertion)

- [ ] **Step 1: Append an assertion to `tests/test_service_grants.py`**

```python
def test_grant_email_body_contains_required_fields(tmp_path):
    from unittest.mock import MagicMock
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    doc_id = _seed(
        conn, alice, email_by_uid={"usr_alice": "a@x", "usr_bob": "b@x"}
    )
    conn.execute(
        "UPDATE users SET display_name = 'Alice' WHERE id = 'usr_alice'"
    )
    conn.commit()
    mc = MagicMock()
    grants_svc.grant(
        conn, base_url=BASE, principal=alice, doc_id=doc_id,
        target="b@x", level="edit", email_client=mc,
    )
    kwargs = mc.send.call_args.kwargs
    assert kwargs["to"] == "b@x"
    assert "Alice" in kwargs["subject"]
    assert "edit" in kwargs["html"]
    assert f"{BASE}/d/" in kwargs["html"]
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_service_grants.py -v`
Expected: PASS (10 tests).

---

## Task 11: End-to-end smoke test

**Files:**
- Create: `tests/test_smoke_grants.py`

- [ ] **Step 1: Write the smoke test**

Create `tests/test_smoke_grants.py`:

```python
"""End-to-end: two users, publish → grant view → grant edit → update."""

from unittest.mock import MagicMock

from markland.db import init_db
from markland.server import build_mcp


BASE = "https://markland.test"


class _Ctx:
    def __init__(self, principal):
        self.principal = principal


def _seed_users(conn, **email_by_uid: str) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL,
            display_name TEXT, is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


def test_two_user_share_flow(tmp_path):
    from markland.service.permissions import Principal

    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    alice = Principal("usr_alice", "user", "usr_alice")
    bob = Principal("usr_bob", "user", "usr_bob")

    email = MagicMock()
    h = build_mcp(conn, base_url=BASE, email_client=email).markland_handlers

    # 1. Alice publishes
    doc = h["markland_publish"](_Ctx(alice), content="# Draft\nv1")
    assert doc["owner_id"] == "usr_alice"
    doc_id = doc["id"]

    # 2. Bob cannot see or modify
    assert h["markland_get"](_Ctx(bob), doc_id=doc_id) == {"error": "not_found"}
    assert h["markland_update"](
        _Ctx(bob), doc_id=doc_id, content="hacked"
    ) == {"error": "not_found"}

    # 3. Alice grants view
    grant_out = h["markland_grant"](
        _Ctx(alice), doc_id=doc_id, principal="b@x", level="view"
    )
    assert grant_out["level"] == "view"
    email.send.assert_called_once()

    # 4. Bob can now read but not write
    view = h["markland_get"](_Ctx(bob), doc_id=doc_id)
    assert view["content"] == "# Draft\nv1"
    assert h["markland_update"](
        _Ctx(bob), doc_id=doc_id, content="hacked"
    ) == {"error": "forbidden"}

    # 5. Alice upgrades Bob to edit
    h["markland_grant"](
        _Ctx(alice), doc_id=doc_id, principal="b@x", level="edit"
    )
    updated = h["markland_update"](
        _Ctx(bob), doc_id=doc_id, content="# Draft\nv2"
    )
    assert updated["id"] == doc_id

    # 6. Alice confirms the new content
    final = h["markland_get"](_Ctx(alice), doc_id=doc_id)
    assert final["content"] == "# Draft\nv2"

    # 7. Alice revokes — Bob is locked out
    h["markland_revoke"](_Ctx(alice), doc_id=doc_id, principal="usr_bob")
    assert h["markland_get"](_Ctx(bob), doc_id=doc_id) == {"error": "not_found"}
```

- [ ] **Step 2: Run the smoke test**

Run: `uv run pytest tests/test_smoke_grants.py -v`
Expected: PASS (1 test).

- [ ] **Step 3: Full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS across every test file touched by this plan:

- `test_service_permissions.py` (11)
- `test_service_docs.py` (10)
- `test_service_grants.py` (10)
- `test_mcp_grants.py` (9)
- `test_api_grants.py` (6)
- `test_dashboard_shared.py` (3)
- `test_web.py` (existing + 1 new)
- `test_smoke_grants.py` (1)

Plus every test that Plans 1 and 2 shipped (`test_config.py`, `test_auth_middleware.py`, `test_email_service.py`, `test_http_mcp.py`, `test_sentry_init.py`, `test_db.py`, `test_renderer.py`, Plan-2's user/token/whoami tests).

---

## Task 12: Manual sanity check against local server

- [ ] **Step 1: Start the app**

In one terminal:

```bash
MARKLAND_ADMIN_TOKEN=local_test uv run python src/markland/run_app.py
```

- [ ] **Step 2: Create two users via Plan 2's magic-link flow**

Using a browser:
1. `http://127.0.0.1:8950/login` → enter `alice@local.test` → click magic link.
2. Create a user token at `/settings/tokens`, copy it as `$ALICE_TOK`.
3. Log out. Repeat for `bob@local.test` → `$BOB_TOK`.

- [ ] **Step 3: Walk the grant flow via curl**

```bash
# Alice publishes
DOC=$(curl -sX POST http://127.0.0.1:8950/api/docs \
  -H "Authorization: Bearer $ALICE_TOK" \
  -H "Content-Type: application/json" \
  -d '{"title":"smoke","content":"hello"}' | jq -r .id)

# Bob cannot read
curl -sSo /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer $BOB_TOK" \
  "http://127.0.0.1:8950/api/docs/$DOC"   # expect 404

# Alice grants view to Bob
curl -sX POST "http://127.0.0.1:8950/api/docs/$DOC/grants" \
  -H "Authorization: Bearer $ALICE_TOK" \
  -H "Content-Type: application/json" \
  -d '{"principal":"bob@local.test","level":"view"}'

# Bob can now see it on the dashboard
curl -s -H "Authorization: Bearer $BOB_TOK" http://127.0.0.1:8950/dashboard \
  | grep -q "smoke" && echo "shared-with-me OK"
```

Expected: each step matches its comment.

- [ ] **Step 4: Stop the server (Ctrl-C)**

No file changes.

---

## Completion criteria

- `uv run pytest tests/ -v` passes, including all new files in this plan plus the ones delivered by Plans 1 and 2.
- A user's tokens from Plan 2 continue to work unchanged; ownership is scoped correctly through `service/docs.py`.
- `markland_grant`, `markland_revoke`, and `markland_list_grants` are reachable via MCP; a non-owner calling any of the first two gets `{"error": "forbidden"}` (or `not_found` for docs they cannot see).
- `GET /api/docs/{id}/grants`, `POST /api/docs/{id}/grants`, `DELETE /api/docs/{id}/grants/{principal_id}` return the correct status codes for owner, grantee, stranger, and anonymous callers.
- The dashboard at `/dashboard` shows "My documents" and "Shared with me" sections; neither surfaces a doc the principal cannot view.
- The `/d/{share_token}` viewer renders the share dialog for the owner and nobody else. The dialog's `POST` and `DELETE` both round-trip to live grants.
- `scripts/backfill_owners.py` runs cleanly on a fresh DB (zero orphans) and correctly reassigns orphaned docs when supplied an existing user email.
- `service/permissions.py::check_permission` raises `NotFound` for strangers (not `PermissionDenied`) on invisible docs, preserving spec §12.5 ID-enumeration resistance.

## What this plan does NOT deliver

Per the spec §17, this plan intentionally stops short of:

- **Agents (Plan 4):** No `agt_…` identifiers, no `agents` table, no inheritance wiring. `service/permissions.py` has a clearly-marked TODO at rule (3) referencing Plan 4.
- **Invite links (Plan 5):** `service/grants.py::_resolve_target` raises `GrantTargetNotFound` when the email isn't a known user; spec §6.1 step 6 will later fall back to an invite-link create.
- **Device flow (Plan 6):** No `/api/auth/device-*` routes, no `/setup` runbook endpoint.
- **Richer email templates (Plan 7):** The grant email is inline HTML. Plan 7 refactors to a Jinja template directory and adds retry-with-backoff.
- **Conflict handling (Plan 8):** `documents.version`, `if_version`, `ETag`, `If-Match`, and the `revisions` table all arrive in Plan 8. `markland_update` in this plan preserves the existing last-write-wins semantics.
- **Presence (Plan 9):** `markland_get` does not include `active_principals`; no `markland_set_status` or `markland_clear_status`.
- **Launch polish (Plan 10):** No rate-limiting on grant endpoints, no `audit_log` rows for grant/revoke, no Sentry dashboard, no onboarding quickstart page.
