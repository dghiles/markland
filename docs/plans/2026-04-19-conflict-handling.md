# Conflict Handling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Protect concurrent edits with optimistic concurrency. Every document carries an integer `version`. Every update must assert the version the caller last saw via `if_version` (MCP) or `If-Match` (HTTP); a mismatch is rejected with a structured conflict payload including the current server state so the caller can re-merge and retry. Every successful update also snapshots the pre-update state to a `revisions` table (capped at 50 rows per doc) so a future `markland_history` tool can restore — the snapshot is written now; the restore tool is deferred.

**Architecture:** Versioning lives in the service layer (`service/docs.py`). `service.docs.update()` gains a required `if_version: int` kwarg and wraps its work in a SQLite transaction: read current row, compare `version`, insert revision, update with `version = version + 1`, prune older revisions past 50. A new `ConflictError` exception carries the server's current state. The MCP tool `markland_update` translates `ConflictError` to `MCPError(code="conflict", data={...})`; the HTTP PATCH route translates it to `409 Conflict` with a JSON body, and requires `If-Match` upfront (missing → `428 Precondition Required`). `GET /api/docs/{id}` sets a weak `ETag: W/"<version>"` header. `markland_get` returns `version` in its dict.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, SQLite (WAL, per-connection transaction via `BEGIN IMMEDIATE`), pytest, httpx (via `fastapi.testclient`), `uv run pytest`.

**Scope excluded (this plan):**
- **No three-way auto-merge.** The server never attempts to reconcile diverged content itself — it hands back `current_content` and lets the caller decide.
- **No CRDT.** Optimistic locking with a single monotonic integer is the entire concurrency model. CRDTs are explicitly deferred per spec §17.
- **No WYSIWYG diff viewer.** The web dashboard does not render a side-by-side diff on conflict. A future UI plan will add that; the MCP path is the launch-blocker.
- **No `markland_history` restore tool.** Revisions are written and pruned but not surfaced. Per spec §8.2: "No UI surface at launch. Preserved so a future `markland_history(doc_id)` tool can restore."
- **No revision viewer on `/d/<share_token>`.** Viewers see `updated_at` only, as today.

---

## File Structure

**New files:**
- `tests/test_service_docs_versioning.py` — unit tests for `service.docs.update()` with `if_version`, `ConflictError`, revision insert, and 50-row pruning.
- `tests/test_mcp_update_conflict.py` — MCP-level test: `markland_update` rejects missing `if_version`, translates `ConflictError` to MCP `conflict` error code.
- `tests/test_http_conflict.py` — HTTP-level tests for `ETag`, `If-Match`, `428`, `409`.
- `tests/test_conflict_e2e.py` — end-to-end integration: two agents racing on the same doc.

**Modified files:**
- `src/markland/db.py` — add `documents.version` column (idempotent ALTER), create `revisions` table, add helpers `insert_revision`, `prune_revisions`, `count_revisions`. `_row_to_doc` and `_DOC_COLUMNS` updated to carry `version`.
- `src/markland/models.py` — `Document.version: int = 1` field.
- `src/markland/service/docs.py` — introduce `ConflictError`; change `update()` to require `if_version`; wire the transaction. Expose `get(doc_id, principal)` as a thin passthrough that already returns `version` (Plan 3 shape, now widened).
- `src/markland/tools/documents.py` — `update_doc(...)` accepts `if_version: int` (required); `get_doc(...)` includes `version` in its dict; translates `ConflictError` into a structured error payload the server layer can lift.
- `src/markland/server.py` / `build_mcp` — `markland_update` signature gains required `if_version: int`; on `ConflictError` raises `mcp.server.fastmcp.exceptions.ToolError` with a `conflict` code and the current state in `data`. Docstring documents that callers must pass the `version` they last saw from `markland_get`.
- `src/markland/web/app.py` — `GET /api/docs/{id}` sets `ETag: W/"<version>"`; `PATCH /api/docs/{id}` requires `If-Match` header (428 if missing/malformed, 409 if mismatched). Body of 409 matches the spec §12.5 shape.

**Unchanged:** `publish_doc`, `delete_doc`, `share_doc`, `set_visibility_doc`, `feature_doc`, renderer, templates, landing/explore routes, auth middleware.

---

## Task 1: Schema migration — `version` column + `revisions` table

**Files:**
- Modify: `src/markland/db.py`
- Create: `tests/test_service_docs_versioning.py` (skeleton only in this task — filled out in Task 4)

Rationale: get the schema in place and backfill existing rows before any service-layer code depends on it. Brand-new DBs pick up the column from the `CREATE TABLE` literal; existing DBs get it via `_add_column_if_missing`. Default `1` covers the backfill.

- [x] **Step 1: Write the failing test**

Create `tests/test_service_docs_versioning.py`:

```python
"""Tests for optimistic concurrency in service.docs."""

import sqlite3

import pytest

from markland.db import (
    count_revisions,
    init_db,
    insert_document,
)
from markland.models import Document


@pytest.fixture
def conn(tmp_path):
    db = init_db(tmp_path / "t.db")
    yield db
    db.close()


def test_new_document_starts_at_version_1(conn):
    doc_id = Document.generate_id()
    token = Document.generate_share_token()
    insert_document(conn, doc_id, "t", "c", token)
    row = conn.execute(
        "SELECT version FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    assert row[0] == 1


def test_revisions_table_exists_and_is_empty_initially(conn):
    doc_id = Document.generate_id()
    token = Document.generate_share_token()
    insert_document(conn, doc_id, "t", "c", token)
    assert count_revisions(conn, doc_id) == 0
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_docs_versioning.py -v`
Expected: FAIL — `count_revisions` does not exist and the `version` column does not exist on a fresh DB.

- [x] **Step 3: Extend `db.py` with schema + helpers**

Replace `src/markland/db.py` with:

```python
"""SQLite database operations for document storage."""

import sqlite3
from pathlib import Path

from markland.models import Document


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
            version INTEGER NOT NULL DEFAULT 1
        )
    """)
    # Migrations for older DBs
    _add_column_if_missing(conn, "documents", "is_public", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "is_featured", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "version", "INTEGER NOT NULL DEFAULT 1")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            principal_id TEXT,
            principal_type TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_share_token ON documents(share_token)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_public ON documents(is_public)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_featured ON documents(is_featured)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_revisions_doc ON revisions(doc_id, id DESC)"
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
        version=row[8],
    )


_DOC_COLUMNS = (
    "id, title, content, share_token, created_at, updated_at, "
    "is_public, is_featured, version"
)


def insert_document(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str,
    content: str,
    share_token: str,
    is_public: bool = False,
) -> str:
    now = Document.now()
    conn.execute(
        f"""
        INSERT INTO documents ({_DOC_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1)
        """,
        (doc_id, title, content, share_token, now, now, 1 if is_public else 0),
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
    cursor = conn.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
    conn.commit()
    return cursor.rowcount > 0


def update_document(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str | None = None,
    content: str | None = None,
) -> Document | None:
    """Legacy helper — does NOT bump version or snapshot. Retained for
    migrations/tests only. New code MUST go through service.docs.update."""
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


def insert_revision(
    conn: sqlite3.Connection,
    *,
    doc_id: str,
    version: int,
    title: str,
    content: str,
    principal_id: str | None,
    principal_type: str | None,
) -> int:
    """Insert a snapshot preserving the pre-update state. `version` is the
    value the document held BEFORE the update that triggered this snapshot."""
    now = Document.now()
    cur = conn.execute(
        """
        INSERT INTO revisions
          (doc_id, version, title, content, principal_id, principal_type, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (doc_id, version, title, content, principal_id, principal_type, now),
    )
    return int(cur.lastrowid)


def count_revisions(conn: sqlite3.Connection, doc_id: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM revisions WHERE doc_id = ?", (doc_id,)
    ).fetchone()
    return int(row[0])


def prune_revisions(
    conn: sqlite3.Connection, doc_id: str, keep: int = 50
) -> int:
    """Delete all but the `keep` most-recent revisions for `doc_id`. Returns
    the number of rows deleted."""
    cur = conn.execute(
        """
        DELETE FROM revisions
        WHERE doc_id = ?
          AND id NOT IN (
            SELECT id FROM revisions
            WHERE doc_id = ?
            ORDER BY id DESC
            LIMIT ?
          )
        """,
        (doc_id, doc_id, keep),
    )
    return cur.rowcount
```

- [x] **Step 4: Update `models.py`**

Replace `src/markland/models.py` with:

```python
"""Document data model."""

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
    version: int = 1

    @staticmethod
    def generate_id() -> str:
        return secrets.token_hex(8)

    @staticmethod
    def generate_share_token() -> str:
        return secrets.token_urlsafe(16)

    @staticmethod
    def now() -> str:
        return datetime.now(timezone.utc).isoformat()
```

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_docs_versioning.py -v`
Expected: PASS (2 tests).

- [x] **Step 6: Run full suite — confirm no regressions from the migration**

Run: `uv run pytest tests/ -v`
Expected: PASS for the full suite. `test_db.py` and `test_documents.py` should keep passing because `Document.version` defaults to `1` and `_DOC_COLUMNS` selects it from the new column.

---

## Task 2: `ConflictError` in `service/docs.py`

**Files:**
- Modify: `src/markland/service/docs.py`

Background: `service/docs.py` exists from Plan 3 and currently exposes `update(doc_id, principal, *, content=None, title=None)` that calls `db.update_document`. This task introduces the exception type the new `update` signature will raise in Task 3. Keep the task small so the error class has clean tests before it's thrown from real code.

- [x] **Step 1: Write the failing test**

Append to `tests/test_service_docs_versioning.py`:

```python
from markland.service.docs import ConflictError


def test_conflict_error_carries_current_state():
    exc = ConflictError(
        current_version=7,
        current_title="Live title",
        current_content="Live body",
    )
    assert exc.current_version == 7
    assert exc.current_title == "Live title"
    assert exc.current_content == "Live body"
    # Sensible string form for logs.
    assert "7" in str(exc)


def test_conflict_error_is_an_exception():
    with pytest.raises(ConflictError):
        raise ConflictError(current_version=1, current_title="t", current_content="c")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_docs_versioning.py::test_conflict_error_carries_current_state -v`
Expected: FAIL — `ConflictError` does not exist.

- [x] **Step 3: Add `ConflictError` to `service/docs.py`**

Edit `src/markland/service/docs.py` — add near the top of the file (after existing imports, before the `update`/`get` functions):

```python
class ConflictError(Exception):
    """Raised when an update's `if_version` does not match the stored version.

    Carries the current server state so callers can surface or merge.
    """

    def __init__(
        self,
        *,
        current_version: int,
        current_title: str,
        current_content: str,
    ) -> None:
        self.current_version = current_version
        self.current_title = current_title
        self.current_content = current_content
        super().__init__(
            f"version conflict: caller had stale version, current is {current_version}"
        )
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_docs_versioning.py -v`
Expected: all prior tests plus the two new ones pass.

---

## Task 3: `service.docs.update()` — optimistic locking + revision snapshot

**Files:**
- Modify: `src/markland/service/docs.py`

This is the core change. `update()` gains a **required** `if_version: int` kwarg and performs the full locked-update dance inside a single `BEGIN IMMEDIATE` transaction:

1. Acquire write lock via `BEGIN IMMEDIATE`.
2. SELECT current row.
3. If `doc.version != if_version` → ROLLBACK and raise `ConflictError`.
4. INSERT into `revisions` with the pre-update state (preserved_version = `doc.version`).
5. UPDATE documents with new title/content, `version = version + 1`, `updated_at = now`.
6. Prune revisions to 50 newest.
7. COMMIT.
8. Return the refreshed Document.

- [x] **Step 1: Write the failing tests**

Append to `tests/test_service_docs_versioning.py`:

```python
from markland.service.docs import get as service_get
from markland.service.docs import update as service_update
from markland.tools.documents import publish_doc


from markland.service.auth import Principal


def _Principal(pid: str, ptype: str = "agent") -> Principal:
    """Matches the Plan 2 principal dataclass for service.docs to log who wrote."""
    return Principal(
        principal_id=pid,
        principal_type=ptype,
        display_name=None,
        is_admin=False,
    )


def _make_doc(conn) -> str:
    result = publish_doc(conn, "http://x", "Original", "Body v1", public=False)
    return result["id"]


def test_update_with_matching_version_bumps_version_and_writes_revision(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a")
    updated = service_update(
        conn,
        doc_id,
        principal,
        content="Body v2",
        title=None,
        if_version=1,
    )
    assert updated.version == 2
    assert updated.content == "Body v2"
    assert updated.title == "Original"
    assert count_revisions(conn, doc_id) == 1
    row = conn.execute(
        "SELECT version, title, content, principal_id, principal_type "
        "FROM revisions WHERE doc_id = ? ORDER BY id DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    # Revision preserves the PRE-update state, so version == 1 (not 2).
    assert row[0] == 1
    assert row[1] == "Original"
    assert row[2] == "Body v1"
    assert row[3] == "agent_a"
    assert row[4] == "agent"


def test_update_with_mismatched_version_raises_conflict(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a")
    # First update: 1 -> 2 (fine).
    service_update(conn, doc_id, principal, content="v2", if_version=1)
    # Second update from a caller who still thinks they're at v1 → conflict.
    with pytest.raises(ConflictError) as exc_info:
        service_update(conn, doc_id, principal, content="stale", if_version=1)
    err = exc_info.value
    assert err.current_version == 2
    assert err.current_content == "v2"
    assert err.current_title == "Original"
    # Doc itself must be unchanged after a conflict.
    after = service_get(conn, doc_id, principal)
    assert after.version == 2
    assert after.content == "v2"


def test_update_against_missing_doc_raises_valueerror(conn):
    principal = _Principal("agent_a")
    with pytest.raises(ValueError):
        service_update(conn, "doesnotexist", principal, content="x", if_version=1)


def test_revision_pruning_caps_at_50(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a")
    # 55 sequential updates; each should preserve exactly one revision row.
    for i in range(55):
        service_update(
            conn,
            doc_id,
            principal,
            content=f"body-{i}",
            if_version=i + 1,  # starts at 1, bumps to 2, etc.
        )
    assert count_revisions(conn, doc_id) == 50
    # The oldest retained revision is version=6 (pre-update state of the 6th update,
    # because versions 1..5 were pruned).
    oldest = conn.execute(
        "SELECT MIN(version) FROM revisions WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]
    assert oldest == 6


def test_get_returns_version(conn):
    doc_id = _make_doc(conn)
    principal = _Principal("agent_a")
    doc = service_get(conn, doc_id, principal)
    assert doc.version == 1
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_docs_versioning.py -v`
Expected: FAIL — the current `service.docs.update()` signature does not accept `if_version`, does not bump version, does not write revisions.

- [x] **Step 3: Implement the new `update()` and expose `get()`**

Replace the body of `src/markland/service/docs.py` (keeping imports and the `ConflictError` class from Task 2):

```python
"""Service layer for document operations with permission + versioning checks."""

from __future__ import annotations

import sqlite3

from markland.db import (
    _DOC_COLUMNS,
    _row_to_doc,
    get_document,
    insert_revision,
    prune_revisions,
)
from markland.models import Document
from markland.service.auth import Principal

MAX_REVISIONS_PER_DOC = 50


class ConflictError(Exception):
    """Raised when an update's `if_version` does not match the stored version.

    Carries the current server state so callers can surface or merge.
    """

    def __init__(
        self,
        *,
        current_version: int,
        current_title: str,
        current_content: str,
    ) -> None:
        self.current_version = current_version
        self.current_title = current_title
        self.current_content = current_content
        super().__init__(
            f"version conflict: caller had stale version, current is {current_version}"
        )


def get(
    conn: sqlite3.Connection,
    doc_id: str,
    principal: Principal,  # noqa: ARG001 — Plan 3 permissions already enforced upstream
) -> Document | None:
    """Return the full Document (including `version`) or None."""
    return get_document(conn, doc_id)


def update(
    conn: sqlite3.Connection,
    doc_id: str,
    principal: Principal,
    *,
    content: str | None = None,
    title: str | None = None,
    if_version: int,
) -> Document:
    """Update a document with optimistic concurrency control.

    `if_version` is REQUIRED and must equal the current stored version; otherwise
    `ConflictError` is raised with the current server state. On success, the
    pre-update state is snapshotted to `revisions`, the version is incremented,
    and `revisions` for this doc are pruned to `MAX_REVISIONS_PER_DOC`.
    """
    # Begin an immediate write transaction so the SELECT ... UPDATE is atomic.
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"SELECT {_DOC_COLUMNS} FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise ValueError(f"Document {doc_id} not found")
        doc = _row_to_doc(row)

        if doc.version != if_version:
            conn.execute("ROLLBACK")
            raise ConflictError(
                current_version=doc.version,
                current_title=doc.title,
                current_content=doc.content,
            )

        new_title = title if title is not None else doc.title
        new_content = content if content is not None else doc.content
        now = Document.now()

        # Snapshot PRE-update state.
        insert_revision(
            conn,
            doc_id=doc.id,
            version=doc.version,
            title=doc.title,
            content=doc.content,
            principal_id=getattr(principal, "principal_id", None),
            principal_type=getattr(principal, "principal_type", None),
        )

        new_version = doc.version + 1
        conn.execute(
            """
            UPDATE documents
            SET title = ?, content = ?, updated_at = ?, version = ?
            WHERE id = ?
            """,
            (new_title, new_content, now, new_version, doc.id),
        )

        prune_revisions(conn, doc.id, keep=MAX_REVISIONS_PER_DOC)

        conn.execute("COMMIT")
    except Exception:
        # Any unexpected error: ensure we don't leave the txn open.
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise

    refreshed = get_document(conn, doc.id)
    assert refreshed is not None
    return refreshed
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_service_docs_versioning.py -v`
Expected: PASS (all versioning tests).

- [x] **Step 5: Verify the rest of the suite**

Run: `uv run pytest tests/ -v`
Expected: PASS. `service.docs.update` is now stricter; tests depending on the old shape are fixed in Task 4 (MCP tool) and Task 5 (HTTP route).

---

## Task 4: `markland_update` MCP tool — require `if_version`, translate conflicts

**Files:**
- Modify: `src/markland/tools/documents.py`
- Modify: `src/markland/server.py`
- Create: `tests/test_mcp_update_conflict.py`

Approach: `tools.documents.update_doc` is the pure-logic seam that the MCP decorator in `server.py` calls. Push the `if_version` argument through it, catch `ConflictError` at the MCP boundary (server.py) and raise a `ToolError` with `code="conflict"` and `data={current_version, current_content, current_title}`. `get_doc` gains a `version` field.

- [x] **Step 1: Write the failing tests**

Create `tests/test_mcp_update_conflict.py`:

```python
"""MCP-level tests for conflict handling in markland_update and markland_get."""

import sqlite3

import pytest

from markland.db import init_db
from markland.service.auth import Principal
from markland.service.docs import ConflictError
from markland.tools.documents import get_doc, publish_doc, update_doc


def _P(pid: str = "agent_test", ptype: str = "agent") -> Principal:
    return Principal(
        principal_id=pid,
        principal_type=ptype,
        display_name=None,
        is_admin=False,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "mcp.db")
    yield c
    c.close()


def test_get_doc_includes_version(conn):
    doc_id = publish_doc(conn, "http://x", "T", "c", public=False)["id"]
    out = get_doc(conn, doc_id)
    assert out["version"] == 1


def test_update_doc_requires_if_version_to_match(conn):
    principal = _P()
    doc_id = publish_doc(conn, "http://x", "T", "v1", public=False)["id"]

    ok = update_doc(
        conn, "http://x", doc_id, principal,
        content="v2", title=None, if_version=1,
    )
    assert ok["version"] == 2

    # Stale caller.
    with pytest.raises(ConflictError) as ei:
        update_doc(
            conn, "http://x", doc_id, principal,
            content="stale", title=None, if_version=1,
        )
    assert ei.value.current_version == 2
    assert ei.value.current_content == "v2"


def test_update_doc_missing_doc_returns_error_dict(conn):
    principal = _P()
    out = update_doc(
        conn, "http://x", "nosuchdoc", principal,
        content="x", title=None, if_version=1,
    )
    assert "error" in out


def test_mcp_tool_translates_conflict_to_tool_error(tmp_path):
    # End-to-end through build_mcp to confirm the MCP translation layer.
    from markland.server import build_mcp

    db = init_db(tmp_path / "mcp2.db")
    doc_id = publish_doc(db, "http://x", "T", "v1", public=False)["id"]

    mcp = build_mcp(db, "http://x")

    # Pull the registered tool callable. FastMCP stores tools on `mcp._tool_manager`.
    tools = {t.name: t for t in mcp._tool_manager.list_tools()}
    update_tool = tools["markland_update"]

    # Happy path
    happy = update_tool.fn(doc_id=doc_id, content="v2", if_version=1)
    assert happy["version"] == 2

    # Conflict path — the MCP layer raises ToolError with `conflict` data.
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError) as ei:
        update_tool.fn(doc_id=doc_id, content="stale", if_version=1)
    # ToolError message includes "conflict"; data carries the snapshot.
    assert "conflict" in str(ei.value).lower()
    # The attached data (if present via attr) contains current_version.
    data = getattr(ei.value, "data", None) or {}
    assert data.get("current_version") == 2
    assert data.get("current_content") == "v2"
    assert data.get("current_title") == "T"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_update_conflict.py -v`
Expected: FAIL — `update_doc` does not accept `principal`/`if_version`; `get_doc` does not return `version`.

- [x] **Step 3: Update `tools/documents.py`**

Replace `update_doc` and `get_doc` in `src/markland/tools/documents.py`:

```python
from markland.service import docs as docs_service


def get_doc(conn: sqlite3.Connection, doc_id: str) -> dict:
    doc = get_document(conn, doc_id)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "title": doc.title,
        "content": doc.content,
        "updated_at": doc.updated_at,
        "is_public": doc.is_public,
        "is_featured": doc.is_featured,
        "version": doc.version,
    }


def update_doc(
    conn: sqlite3.Connection,
    base_url: str,
    doc_id: str,
    principal,
    *,
    content: str | None = None,
    title: str | None = None,
    if_version: int,
) -> dict:
    """Update via the service layer. Lets `ConflictError` propagate so the MCP
    boundary can translate it; returns a plain error dict for `not found`."""
    try:
        doc = docs_service.update(
            conn,
            doc_id,
            principal,
            content=content,
            title=title,
            if_version=if_version,
        )
    except ValueError:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "title": doc.title,
        "share_url": f"{base_url}/d/{doc.share_token}",
        "updated_at": doc.updated_at,
        "version": doc.version,
    }
```

- [x] **Step 4: Update `server.py` / `build_mcp`**

Modify `markland_update` inside `build_mcp`:

```python
    @mcp.tool()
    def markland_update(
        doc_id: str,
        if_version: int,
        content: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Update a document's content or title with optimistic concurrency control.

        Args:
            doc_id: The document ID to update.
            if_version: REQUIRED. The version number you last saw from
                markland_get. If it does not match the server's current
                version, the update is rejected with a `conflict` error
                whose data includes `current_version`, `current_content`,
                and `current_title`. Re-fetch, merge, and retry with the
                fresh version number.
            content: New markdown content (optional).
            title: New title (optional).
        """
        from mcp.server.fastmcp.exceptions import ToolError

        from markland.service.docs import ConflictError

        principal = _principal_from_context()  # existing Plan 3 helper
        try:
            return update_doc(
                db_conn,
                base_url,
                doc_id,
                principal,
                content=content,
                title=title,
                if_version=if_version,
            )
        except ConflictError as exc:
            err = ToolError("conflict: document was modified by another caller")
            err.data = {
                "code": "conflict",
                "current_version": exc.current_version,
                "current_content": exc.current_content,
                "current_title": exc.current_title,
            }
            raise err
```

And update `markland_get`'s docstring note that its response now contains `"version": <int>` (the body is already correct via Task 3 of `get_doc`):

```python
    @mcp.tool()
    def markland_get(doc_id: str) -> dict:
        """Get a document's full content by ID.

        Response includes `version: int` — pass this value back as
        `if_version` to markland_update so your update is rejected if
        anyone else wrote in the meantime.

        Args:
            doc_id: The document ID.
        """
        return get_doc(db_conn, doc_id)
```

Note: if Plan 3's `_principal_from_context` helper has a different name (e.g. `_current_principal()`), use whatever that plan landed on. The point is the principal must flow into the service layer.

- [x] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_mcp_update_conflict.py -v`
Expected: PASS (4 tests).

- [x] **Step 6: Run full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS. Existing `tools.documents.update_doc` call sites elsewhere (e.g. HTTP handler) are wired up in Task 5.

---

## Task 5: HTTP — `ETag` on GET, `If-Match` required on PATCH, 409 on mismatch

**Files:**
- Modify: `src/markland/web/app.py`
- Create: `tests/test_http_conflict.py`

Contract per spec §12.5:

- `GET /api/docs/{id}` → body unchanged, response header `ETag: W/"<version>"`.
- `PATCH /api/docs/{id}` MUST include `If-Match: "<version>"` (or `W/"<version>"`). Missing → `428 Precondition Required` with body `{"error":"precondition_required"}`. Mismatched → `409 Conflict` with body `{"error":"conflict","current_version":N,"current_content":"...","current_title":"..."}`.
- Other errors (missing doc, auth) unchanged.

- [x] **Step 1: Write the failing tests**

Create `tests/test_http_conflict.py`:

```python
"""HTTP ETag/If-Match contract for /api/docs/{id}."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.tools.documents import publish_doc
from markland.web.app import create_app


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_ADMIN_TOKEN", "t")
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    doc_id = publish_doc(conn, "http://x", "Hello", "Body v1", public=False)["id"]
    app = create_app(conn, admin_token="t", base_url="http://x")
    client = TestClient(app)
    # The API routes require admin auth in current design; include it.
    auth = {"Authorization": "Bearer t"}
    return client, doc_id, auth


def test_get_returns_weak_etag_header(env):
    client, doc_id, auth = env
    r = client.get(f"/api/docs/{doc_id}", headers=auth)
    assert r.status_code == 200
    etag = r.headers.get("ETag")
    assert etag is not None
    assert etag == 'W/"1"'


def test_patch_without_if_match_returns_428(env):
    client, doc_id, auth = env
    r = client.patch(
        f"/api/docs/{doc_id}",
        headers=auth,
        json={"content": "Body v2"},
    )
    assert r.status_code == 428
    assert r.json() == {"error": "precondition_required"}


def test_patch_with_stale_if_match_returns_409_and_current_state(env):
    client, doc_id, auth = env
    # First update succeeds, bumping version to 2.
    r1 = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": 'W/"1"'},
        json={"content": "Body v2"},
    )
    assert r1.status_code == 200
    # Caller still thinks version is 1 → conflict.
    r2 = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": 'W/"1"'},
        json={"content": "Stale"},
    )
    assert r2.status_code == 409
    body = r2.json()
    assert body["error"] == "conflict"
    assert body["current_version"] == 2
    assert body["current_content"] == "Body v2"
    assert body["current_title"] == "Hello"


def test_patch_with_matching_if_match_succeeds_and_bumps_etag(env):
    client, doc_id, auth = env
    r = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": 'W/"1"'},
        json={"content": "Body v2"},
    )
    assert r.status_code == 200
    # The response itself carries the new ETag so clients can chain writes.
    assert r.headers.get("ETag") == 'W/"2"'
    # And a subsequent GET reflects it.
    r2 = client.get(f"/api/docs/{doc_id}", headers=auth)
    assert r2.headers.get("ETag") == 'W/"2"'


def test_patch_accepts_strong_form_of_if_match(env):
    # Spec permits the quoted-only form too; both must be accepted.
    client, doc_id, auth = env
    r = client.patch(
        f"/api/docs/{doc_id}",
        headers={**auth, "If-Match": '"1"'},
        json={"content": "ok"},
    )
    assert r.status_code == 200
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_http_conflict.py -v`
Expected: FAIL — no ETag header, PATCH does not enforce `If-Match`.

- [x] **Step 3: Implement in `web/app.py`**

Modify the `GET /api/docs/{id}` and `PATCH /api/docs/{id}` handlers inside `create_app`. (If they do not yet exist, Plan 3 / Plan 7 defined them; this task adds the headers and conflict branching.)

```python
import re

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse

from markland.db import get_document
from markland.service.docs import ConflictError
from markland.service import docs as docs_service

_IF_MATCH_RE = re.compile(r'^(?:W/)?"(\d+)"$')


def _parse_if_match(value: str | None) -> int | None:
    if not value:
        return None
    m = _IF_MATCH_RE.match(value.strip())
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


# Inside create_app(...):

    @app.get("/api/docs/{doc_id}")
    def api_get_doc(doc_id: str, request: Request):
        principal = _principal_from_request(request)  # existing Plan 3 helper
        doc = docs_service.get(db_conn, doc_id, principal)
        if doc is None:
            raise HTTPException(status_code=404, detail="not_found")
        body = {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
            "updated_at": doc.updated_at,
            "version": doc.version,
            "is_public": doc.is_public,
            "is_featured": doc.is_featured,
        }
        return JSONResponse(body, headers={"ETag": f'W/"{doc.version}"'})

    @app.patch("/api/docs/{doc_id}")
    async def api_patch_doc(
        doc_id: str,
        request: Request,
        if_match: str | None = Header(default=None, alias="If-Match"),
    ):
        principal = _principal_from_request(request)
        parsed = _parse_if_match(if_match)
        if parsed is None:
            return JSONResponse(
                {"error": "precondition_required"}, status_code=428
            )
        payload = await request.json()
        content = payload.get("content")
        title = payload.get("title")
        try:
            doc = docs_service.update(
                db_conn,
                doc_id,
                principal,
                content=content,
                title=title,
                if_version=parsed,
            )
        except ValueError:
            raise HTTPException(status_code=404, detail="not_found")
        except ConflictError as exc:
            return JSONResponse(
                {
                    "error": "conflict",
                    "current_version": exc.current_version,
                    "current_content": exc.current_content,
                    "current_title": exc.current_title,
                },
                status_code=409,
            )
        return JSONResponse(
            {
                "id": doc.id,
                "title": doc.title,
                "content": doc.content,
                "updated_at": doc.updated_at,
                "version": doc.version,
            },
            headers={"ETag": f'W/"{doc.version}"'},
        )
```

Note: `_principal_from_request` is the Plan 3 helper that resolves the admin bearer token (or a user session) into a principal. Reuse whatever that plan shipped. If no principal is available in the current code (e.g. admin-only path today), pass a stand-in `Principal` (from `markland.service.auth`) constructed with `principal_id="admin"`, `principal_type="user"`, `display_name=None`, `is_admin=True` so revision rows carry something meaningful.

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_http_conflict.py -v`
Expected: PASS (5 tests).

- [x] **Step 5: Run full suite**

Run: `uv run pytest tests/ -v`
Expected: PASS.

---

## Task 6: End-to-end conflict scenario (two agents racing)

**Files:**
- Create: `tests/test_conflict_e2e.py`

Per the task brief: agent A reads version 3 → agent B updates to 4 → agent A updates with `if_version=3` → receives conflict with `current_version=4` → agent A re-reads, merges, retries with `if_version=4` → success. This test exercises the exact workflow documented to MCP callers.

- [x] **Step 1: Write the test**

Create `tests/test_conflict_e2e.py`:

```python
"""End-to-end: two MCP 'agents' racing on the same document."""

import pytest

from markland.db import init_db
from markland.service.auth import Principal
from markland.service.docs import ConflictError, get, update
from markland.tools.documents import publish_doc


def _P(pid: str) -> Principal:
    return Principal(
        principal_id=pid,
        principal_type="agent",
        display_name=None,
        is_admin=False,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "e2e.db")
    yield c
    c.close()


def test_two_agents_race_then_reconcile(conn):
    a = _P("agent_a")
    b = _P("agent_b")

    # Seed the doc and do two warm-up updates so version == 3 when A first reads.
    doc_id = publish_doc(conn, "http://x", "T", "v1", public=False)["id"]
    update(conn, doc_id, a, content="v2", if_version=1)
    update(conn, doc_id, a, content="v3", if_version=2)

    # A reads at version 3.
    a_snapshot = get(conn, doc_id, a)
    assert a_snapshot.version == 3
    a_saw_content = a_snapshot.content  # "v3"

    # B reads, writes, bumps to version 4.
    b_snapshot = get(conn, doc_id, b)
    assert b_snapshot.version == 3
    update(conn, doc_id, b, content="v4-from-b", if_version=3)

    # A tries to write with its stale if_version=3 → conflict.
    with pytest.raises(ConflictError) as ei:
        update(conn, doc_id, a, content="v4-from-a", if_version=3)
    err = ei.value
    assert err.current_version == 4
    assert err.current_content == "v4-from-b"

    # A merges (here: appends its intent to the current content) and retries.
    a_merged = err.current_content + "\n\n[from A on top of " + a_saw_content + "]"
    final = update(conn, doc_id, a, content=a_merged, if_version=err.current_version)
    assert final.version == 5
    assert "v4-from-b" in final.content
    assert "[from A on top of v3]" in final.content


def test_fifty_five_writes_prune_revisions_to_fifty(conn):
    from markland.db import count_revisions

    a = _P("agent_a")
    doc_id = publish_doc(conn, "http://x", "T", "v1", public=False)["id"]
    for i in range(55):
        update(conn, doc_id, a, content=f"body-{i}", if_version=i + 1)
    assert count_revisions(conn, doc_id) == 50
    # Document itself ended at version 56 (started at 1, +55 updates).
    final = get(conn, doc_id, a)
    assert final.version == 56
    assert final.content == "body-54"
```

- [x] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_conflict_e2e.py -v`
Expected: PASS (2 tests). No new implementation is required — this task is a dedicated integration check that the primitives from Tasks 1–5 compose correctly.

- [x] **Step 3: Final full-suite run**

Run: `uv run pytest tests/ -v`
Expected: PASS for the full suite (prior tests + 4 new test files).

---

## Task 7: Document the protocol for MCP agents

**Files:**
- Modify: `README.md`

Short, boring operator-facing note: any caller of `markland_update` must thread the `version` from `markland_get` through `if_version`, and must be prepared for the `conflict` error code with a structured `data` payload.

- [x] **Step 1: Append a "Concurrent edits" section to `README.md`**

Append:

```markdown

## Concurrent edits

Markland uses optimistic concurrency: every document carries an integer
`version`, and every update must assert the version the caller last saw.

### MCP

```
# 1. Read — response includes "version": <int>
markland_get(doc_id="abc123")

# 2. Update — pass that number back as if_version
markland_update(
    doc_id="abc123",
    if_version=3,
    content="my new content",
)
```

If another caller wrote in between, `markland_update` raises a tool error
with `code="conflict"` and `data={current_version, current_content,
current_title}`. Re-fetch (or use the `current_*` snapshot inline), merge,
and retry with the fresh `if_version`.

### HTTP

- `GET /api/docs/{id}` returns `ETag: W/"<version>"`.
- `PATCH /api/docs/{id}` requires `If-Match: "<version>"` (weak or strong
  form accepted). Missing → `428 Precondition Required`. Mismatched → `409
  Conflict` with body `{error, current_version, current_content,
  current_title}`.

Every successful update snapshots the pre-update state to an internal
`revisions` table (capped at 50 per doc). No user-facing history tool ships
at launch; the snapshots are preserved so a future `markland_history` tool
can restore.
```

- [x] **Step 2: Verification — read it back**

Read the README section and confirm it is accurate against the code you just wrote. No test command.

---

## Completion criteria

- `uv run pytest tests/ -v` passes the full suite, including the four new files:
  `test_service_docs_versioning.py`, `test_mcp_update_conflict.py`,
  `test_http_conflict.py`, `test_conflict_e2e.py`.
- `documents.version` column exists in fresh and migrated DBs, with `1` as the backfilled default for pre-Plan-8 rows.
- `revisions` table exists with the schema: `(id PK AUTOINCREMENT, doc_id FK, version, title, content, principal_id, principal_type, created_at)`, and per-doc pruning keeps only the 50 most recent rows.
- `service.docs.update()` requires `if_version`, raises `ConflictError(current_version, current_title, current_content)` on mismatch, increments `version` on success, and writes exactly one revision row per successful update.
- `markland_update` MCP tool has `if_version: int` as a required parameter and raises a `ToolError` with `code="conflict"` plus `data={current_version, current_content, current_title}` on mismatch.
- `markland_get` includes `"version"` in its response dict.
- `GET /api/docs/{id}` sets `ETag: W/"<version>"`; `PATCH /api/docs/{id}` returns `428` without `If-Match`, `409` on mismatch (with the full conflict body), `200` on success (with updated ETag).
- README documents the contract for both MCP and HTTP.

## What this plan does NOT deliver

Per spec §17 and §8.2, the following are explicitly deferred to later plans:

- **`markland_history(doc_id)` restore tool.** Revision rows are written and pruned but no MCP tool or HTTP endpoint surfaces them yet. The table is designed so that tool can be added with no further schema change.
- **Side-by-side diff viewer in the web dashboard.** When a signed-in user's PATCH returns `409`, the launch UI simply surfaces the error body. A richer conflict-resolution UI (diff, merge, "keep theirs / keep mine") will land in a later UI plan — the launch UI is minimal because MCP agents are the primary editor.
- **Three-way auto-merge** and any server-side content reconciliation.
- **CRDT-based concurrent editing.** Out of scope for v1 per spec §17.
- **Per-principal revision browsing**, audit logs, or retention beyond 50 rows per doc.
