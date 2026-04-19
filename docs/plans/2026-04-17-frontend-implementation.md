# Markland Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note (2026-04-18, three theming passes the same day):** This plan reflects the initial implementation pass. The templates created in Tasks 5-7 (and the `document.html` from the earlier plan) were subsequently restyled three times on the same day:
> - **AM — Neubrutalism** (`docs/plans/2026-04-18-neubrutalism-theming.md`) — superseded
> - **Mid-day — IO24 / gradient** (`docs/plans/2026-04-18-io24-theming.md`) — superseded after design review
> - **PM — Dark + Outlined + Primary** (`docs/plans/2026-04-18-dark-outlined-primary.md`) — **current authority**
>
> The route handlers, data model, MCP tools, and excerpt logic in this plan are still accurate; only the CSS in Tasks 5, 6, 7 is stale (and landing.html now has an additional "Get started" nav-card section that wasn't in the original plan). For the current aesthetic see `docs/specs/2026-04-17-frontend-design.md` → "Visual Direction".

**Goal:** Add a marketing landing page (`/`) and public gallery (`/explore`) with opt-in visibility and featured-doc curation.

**Architecture:** Extend the existing FastAPI web viewer with two new routes and a shared Jinja2 base template. Add `is_public` and `is_featured` columns to the SQLite documents table via idempotent migration. Three new MCP tools handle visibility and feature curation. No auth, no JavaScript, no asset pipeline — server-rendered HTML with inlined CSS.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, SQLite (existing). No new dependencies.

**Scope:**
- Two new pages: `/` (dark landing) and `/explore` (light gallery with search)
- Two new DB columns: `is_public`, `is_featured` (migration preserves existing docs as unlisted)
- Three new/modified MCP tools: `markland_publish` (adds `public` param), `markland_set_visibility`, `markland_feature`
- ~12 new tests bringing suite to ~53

**Execution notes:**
- No git commits during execution — user commits manually
- All work is in `~/Developer/markland/`
- Reference spec: `~/Developer/markland/docs/specs/2026-04-17-frontend-design.md`

---

## File Structure

**Modified files:**
- `src/markland/models.py` — add `is_public` and `is_featured` fields to `Document`
- `src/markland/db.py` — add migration, update row mapping, add 4 new query functions, update `insert_document` signature
- `src/markland/tools/documents.py` — add `public` param to `publish_doc`, add `set_visibility_doc` and `feature_doc`
- `src/markland/server.py` — add `public` to `markland_publish`, add `markland_set_visibility` and `markland_feature`
- `src/markland/web/renderer.py` — add `make_excerpt` function
- `src/markland/web/app.py` — add `/` and `/explore` routes with Jinja templates
- `tests/test_db.py` — add 5 tests
- `tests/test_documents.py` — add 3 tests
- `tests/test_web.py` — add 5 tests
- `scripts/smoke_test.py` — extend with landing/explore assertions

**New files:**
- `src/markland/web/templates/base.html` — shared layout with header nav
- `src/markland/web/templates/landing.html` — dark marketing landing
- `src/markland/web/templates/explore.html` — light masonry gallery

---

### Task 1: Schema Migration + Document Model

**Files:**
- Modify: `src/markland/models.py`
- Modify: `src/markland/db.py`
- Modify: `tests/test_db.py`

- [ ] **Step 1: Update the Document dataclass**

Replace the contents of `src/markland/models.py` with:

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

- [ ] **Step 2: Add failing migration test to `tests/test_db.py`**

Append these tests to the END of `tests/test_db.py`:

```python
def test_migration_adds_columns(tmp_path):
    """Initialize a DB with the old schema, then re-init — new columns must appear."""
    import sqlite3
    db_path = tmp_path / "legacy.db"

    # Create "old" schema WITHOUT is_public / is_featured
    old_conn = sqlite3.connect(str(db_path))
    old_conn.execute("""
        CREATE TABLE documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            share_token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    from markland.models import Document as DocModel
    now = DocModel.now()
    old_conn.execute(
        "INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?)",
        ("legacy-id", "Legacy Doc", "# Old", "legacy-token", now, now),
    )
    old_conn.commit()
    old_conn.close()

    # Run init_db — it should migrate the old schema
    from markland.db import init_db, get_document
    conn = init_db(db_path)

    # New columns should exist and default to 0 for the legacy row
    doc = get_document(conn, "legacy-id")
    assert doc is not None
    assert doc.is_public is False
    assert doc.is_featured is False
    conn.close()


def test_insert_sets_is_public_flag(db):
    from markland.db import insert_document, get_document
    insert_document(db, "pub-id", "Public", "content", "tok-pub", is_public=True)
    doc = get_document(db, "pub-id")
    assert doc.is_public is True
    assert doc.is_featured is False


def test_list_public_filters_unlisted(db):
    from markland.db import insert_document, list_public_documents
    insert_document(db, "pub", "Public", "content", "tok1", is_public=True)
    insert_document(db, "priv", "Private", "content", "tok2", is_public=False)
    public_docs = list_public_documents(db)
    assert len(public_docs) == 1
    assert public_docs[0].id == "pub"


def test_list_public_applies_search(db):
    from markland.db import insert_document, list_public_documents
    insert_document(db, "p1", "Python guide", "c", "t1", is_public=True)
    insert_document(db, "p2", "Rust guide", "c", "t2", is_public=True)
    results = list_public_documents(db, query="Python")
    assert len(results) == 1
    assert results[0].id == "p1"


def test_set_visibility(db):
    from markland.db import insert_document, set_visibility, get_document
    insert_document(db, "d1", "T", "c", "t1", is_public=False)
    updated = set_visibility(db, "d1", is_public=True)
    assert updated is not None
    assert updated.is_public is True
    assert get_document(db, "d1").is_public is True


def test_set_featured(db):
    from markland.db import insert_document, set_featured
    insert_document(db, "d1", "T", "c", "t1", is_public=True)
    updated = set_featured(db, "d1", is_featured=True)
    assert updated is not None
    assert updated.is_featured is True


def test_list_featured_and_recent_public_orders_featured_first(db):
    import time
    from markland.db import insert_document, set_featured, list_featured_and_recent_public
    # Older doc is featured
    insert_document(db, "old-featured", "Old featured", "c", "t1", is_public=True)
    set_featured(db, "old-featured", is_featured=True)
    time.sleep(0.01)
    # Newer doc is not featured
    insert_document(db, "new-unfeatured", "New unfeatured", "c", "t2", is_public=True)

    docs = list_featured_and_recent_public(db, limit=8)
    assert len(docs) == 2
    assert docs[0].id == "old-featured"  # featured ranks first despite older timestamp
    assert docs[1].id == "new-unfeatured"


def test_list_featured_and_recent_excludes_unlisted_featured(db):
    """A non-public doc marked featured should still be excluded from the landing."""
    from markland.db import insert_document, set_featured, list_featured_and_recent_public
    insert_document(db, "private", "Private but featured", "c", "t1", is_public=False)
    set_featured(db, "private", is_featured=True)
    docs = list_featured_and_recent_public(db)
    assert docs == []
```

- [ ] **Step 3: Run the new tests (expect failure)**

```bash
cd ~/Developer/markland && uv run pytest tests/test_db.py -v 2>&1 | tail -30
```

Expected: new tests fail with `ImportError` or `AttributeError` on `list_public_documents`, `set_visibility`, `set_featured`, `list_featured_and_recent_public`, and `is_public` kwarg on `insert_document`.

- [ ] **Step 4: Update `src/markland/db.py`**

Replace the contents of `src/markland/db.py` with:

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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            share_token TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            is_public INTEGER NOT NULL DEFAULT 0,
            is_featured INTEGER NOT NULL DEFAULT 0
        )
    """)
    # Migration for older databases that don't yet have the visibility columns
    _add_column_if_missing(conn, "documents", "is_public", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "is_featured", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_share_token ON documents(share_token)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_public ON documents(is_public)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_featured ON documents(is_featured)")
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
    )


_DOC_COLUMNS = "id, title, content, share_token, created_at, updated_at, is_public, is_featured"


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
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
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
```

- [ ] **Step 5: Run all db tests**

```bash
cd ~/Developer/markland && uv run pytest tests/test_db.py -v 2>&1 | tail -30
```

Expected: all 19 tests PASS (12 existing + 7 new).

- [ ] **Step 6: Run full suite to confirm no regressions elsewhere**

```bash
cd ~/Developer/markland && uv run pytest tests/ -v 2>&1 | tail -15
```

Expected: All tests PASS. Documents and web tests should still work since they don't care about the new fields.

---

### Task 2: Tool Logic — publish with visibility, set_visibility, feature

**Files:**
- Modify: `src/markland/tools/documents.py`
- Modify: `tests/test_documents.py`

- [ ] **Step 1: Add failing tests to `tests/test_documents.py`**

Append these tests to the END of `tests/test_documents.py`:

```python
def test_publish_with_public_flag(db):
    from markland.db import get_document
    result = publish_doc(db, BASE_URL, None, "# Public Doc\n\nBody.", public=True)
    doc = get_document(db, result["id"])
    assert doc.is_public is True


def test_publish_defaults_to_unlisted(db):
    from markland.db import get_document
    result = publish_doc(db, BASE_URL, None, "# Default\n\nBody.")
    doc = get_document(db, result["id"])
    assert doc.is_public is False


def test_set_visibility_tool(db):
    from markland.tools.documents import set_visibility_doc
    published = publish_doc(db, BASE_URL, "T", "content")
    result = set_visibility_doc(db, BASE_URL, published["id"], is_public=True)
    assert "error" not in result
    assert result["is_public"] is True


def test_set_visibility_tool_nonexistent(db):
    from markland.tools.documents import set_visibility_doc
    result = set_visibility_doc(db, BASE_URL, "nonexistent", is_public=True)
    assert "error" in result


def test_feature_tool(db):
    from markland.tools.documents import feature_doc
    published = publish_doc(db, BASE_URL, "T", "content", public=True)
    result = feature_doc(db, published["id"], is_featured=True)
    assert "error" not in result
    assert result["is_featured"] is True


def test_feature_tool_nonexistent(db):
    from markland.tools.documents import feature_doc
    result = feature_doc(db, "nonexistent", is_featured=True)
    assert "error" in result
```

- [ ] **Step 2: Run tests (expect failure)**

```bash
cd ~/Developer/markland && uv run pytest tests/test_documents.py -v 2>&1 | tail -25
```

Expected: new tests fail — `publish_doc` doesn't accept `public` kwarg, `set_visibility_doc` and `feature_doc` don't exist.

- [ ] **Step 3: Update `src/markland/tools/documents.py`**

Replace the contents of `src/markland/tools/documents.py` with:

```python
"""Pure tool logic — no MCP decorators, no framework coupling."""

import sqlite3

from markland.db import (
    delete_document,
    get_document,
    insert_document,
    list_documents,
    search_documents,
    set_featured,
    set_visibility,
    update_document,
)
from markland.models import Document


def _extract_title(content: str) -> str:
    """Extract title from the first H1 heading, or return 'Untitled'."""
    for line in content.strip().splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return "Untitled"


def publish_doc(
    conn: sqlite3.Connection,
    base_url: str,
    title: str | None,
    content: str,
    public: bool = False,
) -> dict:
    doc_id = Document.generate_id()
    share_token = Document.generate_share_token()
    resolved_title = title if title else _extract_title(content)
    insert_document(
        conn, doc_id, resolved_title, content, share_token, is_public=public
    )
    return {
        "id": doc_id,
        "title": resolved_title,
        "share_url": f"{base_url}/d/{share_token}",
        "is_public": public,
    }


def list_docs(conn: sqlite3.Connection) -> list[dict]:
    docs = list_documents(conn)
    return [
        {
            "id": d.id,
            "title": d.title,
            "updated_at": d.updated_at,
            "is_public": d.is_public,
            "is_featured": d.is_featured,
        }
        for d in docs
    ]


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
    }


def search_docs(conn: sqlite3.Connection, query: str) -> list[dict]:
    docs = search_documents(conn, query)
    return [
        {
            "id": d.id,
            "title": d.title,
            "updated_at": d.updated_at,
            "is_public": d.is_public,
        }
        for d in docs
    ]


def share_doc(conn: sqlite3.Connection, base_url: str, doc_id: str) -> dict:
    doc = get_document(conn, doc_id)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "share_url": f"{base_url}/d/{doc.share_token}",
        "title": doc.title,
    }


def delete_doc(conn: sqlite3.Connection, doc_id: str) -> dict:
    deleted = delete_document(conn, doc_id)
    return {"deleted": deleted, "id": doc_id}


def update_doc(
    conn: sqlite3.Connection,
    base_url: str,
    doc_id: str,
    content: str | None = None,
    title: str | None = None,
) -> dict:
    doc = update_document(conn, doc_id, title=title, content=content)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "title": doc.title,
        "share_url": f"{base_url}/d/{doc.share_token}",
        "updated_at": doc.updated_at,
    }


def set_visibility_doc(
    conn: sqlite3.Connection, base_url: str, doc_id: str, is_public: bool
) -> dict:
    doc = set_visibility(conn, doc_id, is_public)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "is_public": doc.is_public,
        "share_url": f"{base_url}/d/{doc.share_token}",
    }


def feature_doc(
    conn: sqlite3.Connection, doc_id: str, is_featured: bool
) -> dict:
    doc = set_featured(conn, doc_id, is_featured)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "is_featured": doc.is_featured,
        "is_public": doc.is_public,
    }
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd ~/Developer/markland && uv run pytest tests/test_documents.py -v 2>&1 | tail -25
```

Expected: all 19 tests PASS (13 existing + 6 new).

---

### Task 3: MCP Server — register new tools

**Files:**
- Modify: `src/markland/server.py`

- [ ] **Step 1: Update `src/markland/server.py`**

Replace the contents of `src/markland/server.py` with:

```python
"""Markland MCP Server — publish and share markdown documents."""

import logging

from mcp.server.fastmcp import FastMCP

from markland.config import get_config
from markland.db import init_db
from markland.tools.documents import (
    delete_doc,
    feature_doc,
    get_doc,
    list_docs,
    publish_doc,
    search_docs,
    set_visibility_doc,
    share_doc,
    update_doc,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("markland")

config = get_config()
db_conn = init_db(config.db_path)

mcp = FastMCP("markland")


@mcp.tool()
def markland_publish(
    content: str,
    title: str | None = None,
    public: bool = False,
) -> dict:
    """Publish a markdown document and get a shareable link.

    Args:
        content: The markdown content to publish.
        title: Optional title. If omitted, extracted from the first # heading.
        public: If True, the doc appears in /explore. Default: unlisted (link-only).
    """
    return publish_doc(db_conn, config.base_url, title, content, public=public)


@mcp.tool()
def markland_list() -> list[dict]:
    """List all published documents, most recent first."""
    return list_docs(db_conn)


@mcp.tool()
def markland_get(doc_id: str) -> dict:
    """Get a document's full content by ID.

    Args:
        doc_id: The document ID.
    """
    return get_doc(db_conn, doc_id)


@mcp.tool()
def markland_search(query: str) -> list[dict]:
    """Search documents by title or content.

    Args:
        query: Search string to match against title and content.
    """
    return search_docs(db_conn, query)


@mcp.tool()
def markland_share(doc_id: str) -> dict:
    """Get the shareable link for a document.

    Args:
        doc_id: The document ID.
    """
    return share_doc(db_conn, config.base_url, doc_id)


@mcp.tool()
def markland_update(doc_id: str, content: str | None = None, title: str | None = None) -> dict:
    """Update a document's content or title.

    Args:
        doc_id: The document ID to update.
        content: New markdown content (optional).
        title: New title (optional).
    """
    return update_doc(db_conn, config.base_url, doc_id, content=content, title=title)


@mcp.tool()
def markland_delete(doc_id: str) -> dict:
    """Delete a document.

    Args:
        doc_id: The document ID to delete.
    """
    return delete_doc(db_conn, doc_id)


@mcp.tool()
def markland_set_visibility(doc_id: str, public: bool) -> dict:
    """Promote a doc to public (appears in /explore) or demote to unlisted.

    Args:
        doc_id: The document ID.
        public: True to make public, False for unlisted.
    """
    return set_visibility_doc(db_conn, config.base_url, doc_id, is_public=public)


@mcp.tool()
def markland_feature(doc_id: str, featured: bool = True) -> dict:
    """Pin or unpin a doc to the landing page hero.

    Args:
        doc_id: The document ID.
        featured: True to pin, False to unpin. Featured docs only appear on the
            landing page if they are also public.
    """
    return feature_doc(db_conn, doc_id, is_featured=featured)


if __name__ == "__main__":
    logger.info("Starting Markland MCP server (db: %s)", config.db_path)
    mcp.run()
```

- [ ] **Step 2: Verify server imports cleanly**

```bash
cd ~/Developer/markland && uv run python -c "from markland import server; print('tools:', sorted([t for t in dir(server) if t.startswith('markland_')]))"
```

Expected output:
```
tools: ['markland_delete', 'markland_feature', 'markland_get', 'markland_list', 'markland_publish', 'markland_search', 'markland_set_visibility', 'markland_share', 'markland_update']
```

---

### Task 4: Excerpt Helper

**Files:**
- Modify: `src/markland/web/renderer.py`
- Create test in: `tests/test_renderer.py`

- [ ] **Step 1: Add failing tests to `tests/test_renderer.py`**

Append to the END of `tests/test_renderer.py`:

```python
def test_excerpt_short_content():
    from markland.web.renderer import make_excerpt
    assert make_excerpt("Hello world.") == "Hello world."


def test_excerpt_strips_heading_markers():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("# Title\n\nBody text here.")
    assert result.startswith("Title Body text here.")


def test_excerpt_strips_list_markers():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("- item one\n- item two")
    assert "-" not in result
    assert "item one" in result
    assert "item two" in result


def test_excerpt_strips_link_syntax_keeps_text():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("See [the docs](https://example.com) for more.")
    assert "the docs" in result
    assert "example.com" not in result


def test_excerpt_strips_code_fences():
    from markland.web.renderer import make_excerpt
    content = "Intro text.\n\n```python\ndef foo():\n    pass\n```\n\nAfter code."
    result = make_excerpt(content)
    assert "def foo" not in result
    assert "Intro text" in result
    assert "After code" in result


def test_excerpt_truncates_long_content():
    from markland.web.renderer import make_excerpt
    long_text = "word " * 100
    result = make_excerpt(long_text, length=50)
    assert len(result) <= 51  # 50 + ellipsis
    assert result.endswith("…")


def test_excerpt_no_ellipsis_when_short():
    from markland.web.renderer import make_excerpt
    result = make_excerpt("Short text.", length=50)
    assert "…" not in result
```

- [ ] **Step 2: Run tests (expect failure)**

```bash
cd ~/Developer/markland && uv run pytest tests/test_renderer.py -v 2>&1 | tail -15
```

Expected: new tests fail with `ImportError` on `make_excerpt`.

- [ ] **Step 3: Add `make_excerpt` to `src/markland/web/renderer.py`**

Append the following to the END of `src/markland/web/renderer.py`:

```python


import re as _re


def make_excerpt(content: str, length: int = 140) -> str:
    """Strip common markdown syntax and return the first `length` chars."""
    if not content:
        return ""
    # Remove fenced code blocks greedily across lines
    cleaned = _re.sub(r"```.*?```", "", content, flags=_re.DOTALL)
    # Strip heading markers
    cleaned = _re.sub(r"^#+\s*", "", cleaned, flags=_re.MULTILINE)
    # Strip list markers (-, *, +, or numbered)
    cleaned = _re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=_re.MULTILINE)
    cleaned = _re.sub(r"^\s*\d+\.\s+", "", cleaned, flags=_re.MULTILINE)
    # Replace [text](url) with text
    cleaned = _re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    # Strip blockquote markers
    cleaned = _re.sub(r"^\s*>\s?", "", cleaned, flags=_re.MULTILINE)
    # Strip emphasis and inline code chars
    cleaned = _re.sub(r"[*_`]", "", cleaned)
    # Collapse whitespace
    cleaned = _re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > length:
        return cleaned[:length].rstrip() + "…"
    return cleaned
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd ~/Developer/markland && uv run pytest tests/test_renderer.py -v 2>&1 | tail -20
```

Expected: all 19 tests PASS (12 existing + 7 new).

---

### Task 5: Shared Base Template

**Files:**
- Create: `src/markland/web/templates/base.html`

- [ ] **Step 1: Create `src/markland/web/templates/base.html`**

Write the following to `src/markland/web/templates/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Markland{% endblock %}</title>
    <style>
        :root {
            --bg: #fafafa;
            --text: #1a1a1a;
            --muted: #6b7280;
            --border: #e5e7eb;
            --card-bg: #ffffff;
            --code-bg: #f3f4f6;
            --link: #2563eb;
            --max-width: 1080px;
            --accent: #111827;
            --accent-fg: #ffffff;
        }
        body.dark {
            --bg: #0a0a0a;
            --text: #f5f5f5;
            --muted: #9ca3af;
            --border: #262626;
            --card-bg: #171717;
            --code-bg: #1f1f1f;
            --link: #60a5fa;
            --accent: #ffffff;
            --accent-fg: #000000;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
            background: var(--bg);
            color: var(--text);
            line-height: 1.6;
            min-height: 100vh;
        }
        a { color: inherit; text-decoration: none; }
        .site-header {
            border-bottom: 1px solid var(--border);
            padding: 1rem 1.5rem;
        }
        .site-header-inner {
            max-width: var(--max-width);
            margin: 0 auto;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }
        .wordmark {
            font-weight: 700;
            font-size: 1.1rem;
            letter-spacing: -0.01em;
        }
        .site-nav {
            display: flex;
            gap: 1.25rem;
            font-size: 0.9rem;
            color: var(--muted);
        }
        .site-nav a:hover { color: var(--text); }
        .site-nav a.active { color: var(--text); font-weight: 600; }
        .main {
            max-width: var(--max-width);
            margin: 0 auto;
            padding: 2rem 1.5rem 4rem;
        }
        .site-footer {
            border-top: 1px solid var(--border);
            padding: 1.5rem;
            color: var(--muted);
            font-size: 0.85rem;
            text-align: center;
        }
        {% block head_extra %}{% endblock %}
    </style>
</head>
<body class="{% block body_class %}{% endblock %}">
    <header class="site-header">
        <div class="site-header-inner">
            <a href="/" class="wordmark">Markland</a>
            <nav class="site-nav">
                <a href="/explore" class="{% block nav_explore %}{% endblock %}">Explore</a>
                <a href="https://github.com/" target="_blank" rel="noopener">Docs</a>
            </nav>
        </div>
    </header>
    <main class="main">
        {% block content %}{% endblock %}
    </main>
    <footer class="site-footer">
        Markland — an experiment in agent-native publishing · <a href="/explore">Browse public docs</a>
    </footer>
</body>
</html>
```

- [ ] **Step 2: Verify Jinja loads it without error**

```bash
cd ~/Developer/markland && uv run python -c "
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
p = Path('src/markland/web/templates')
env = Environment(loader=FileSystemLoader(str(p)))
t = env.get_template('base.html')
print('OK, template loaded')
"
```

Expected output: `OK, template loaded`

---

### Task 6: Landing Template

**Files:**
- Create: `src/markland/web/templates/landing.html`

- [ ] **Step 1: Create `src/markland/web/templates/landing.html`**

Write the following to `src/markland/web/templates/landing.html`:

```html
{% extends "base.html" %}

{% block title %}Markland — Agent-native document publishing{% endblock %}
{% block body_class %}dark{% endblock %}

{% block head_extra %}
        .hero {
            padding: 4rem 0 3rem;
            text-align: center;
        }
        .hero h1 {
            font-size: clamp(2rem, 5vw, 3.25rem);
            font-weight: 700;
            line-height: 1.1;
            letter-spacing: -0.02em;
            margin-bottom: 1rem;
        }
        .hero p.lede {
            font-size: 1.1rem;
            color: var(--muted);
            max-width: 560px;
            margin: 0 auto 2rem;
        }
        .hero .cta {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            background: var(--accent);
            color: var(--accent-fg);
            padding: 0.65rem 1.1rem;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.95rem;
            border: none;
            cursor: pointer;
            font-family: inherit;
        }
        .hero .cta:hover { opacity: 0.9; }
        .hero .cta-hint {
            display: block;
            font-size: 0.8rem;
            color: var(--muted);
            margin-top: 0.75rem;
        }
        .section {
            padding: 3rem 0;
            border-top: 1px solid var(--border);
        }
        .section-title {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
            margin-bottom: 1.5rem;
        }
        .pillars {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
        }
        .pillar h3 {
            font-size: 1.05rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        .pillar p {
            color: var(--muted);
            font-size: 0.95rem;
        }
        .cards {
            column-count: 3;
            column-gap: 1rem;
        }
        .card {
            display: block;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin: 0 0 1rem;
            break-inside: avoid;
        }
        .card:hover { border-color: var(--text); }
        .card .card-title {
            font-weight: 600;
            font-size: 1rem;
            margin-bottom: 0.4rem;
        }
        .card .card-excerpt {
            color: var(--muted);
            font-size: 0.88rem;
            margin-bottom: 0.6rem;
        }
        .card .card-meta {
            color: var(--muted);
            font-size: 0.75rem;
        }
        .card .card-badge {
            display: inline-block;
            background: var(--accent);
            color: var(--accent-fg);
            font-size: 0.65rem;
            font-weight: 600;
            padding: 0.1rem 0.4rem;
            border-radius: 3px;
            margin-left: 0.4rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .empty-featured {
            color: var(--muted);
            text-align: center;
            padding: 2rem;
            border: 1px dashed var(--border);
            border-radius: 8px;
        }
        @media (max-width: 900px) {
            .cards { column-count: 2; }
            .pillars { grid-template-columns: 1fr; }
        }
        @media (max-width: 560px) {
            .cards { column-count: 1; }
        }
{% endblock %}

{% block content %}
<section class="hero">
    <h1>Your agent writes.<br>The world reads.</h1>
    <p class="lede">A surface for agent-authored markdown. Publish from your MCP client, share a link, no account required.</p>
    <button class="cta" onclick="copyConfig()">MCP config</button>
    <span class="cta-hint" id="cta-hint">Click to copy the config snippet</span>
</section>

<section class="section">
    <div class="section-title">Why Markland</div>
    <div class="pillars">
        <div class="pillar">
            <h3>GitHub isn't built for sharing</h3>
            <p>Review UI is for code. Non-technical reviewers bounce. Agents can't comment.</p>
        </div>
        <div class="pillar">
            <h3>Google Drive isn't built for agents</h3>
            <p>Your agent can't publish, search, or iterate there. MCP support is clunky.</p>
        </div>
        <div class="pillar">
            <h3>Markdown deserves better</h3>
            <p>Every spec, plan, CLAUDE.md, and prompt pack lives in markdown. It needs a hosting layer.</p>
        </div>
    </div>
</section>

<section class="section">
    <div class="section-title">Published from agents</div>
    {% if docs %}
    <div class="cards">
        {% for doc in docs %}
        <a class="card" href="/d/{{ doc.share_token }}">
            <div class="card-title">{{ doc.title }}{% if doc.is_featured %}<span class="card-badge">Pinned</span>{% endif %}</div>
            {% if doc.excerpt %}<div class="card-excerpt">{{ doc.excerpt }}</div>{% endif %}
            <div class="card-meta">{{ doc.updated_at[:10] }}</div>
        </a>
        {% endfor %}
    </div>
    {% else %}
    <div class="empty-featured">The first agent-authored docs will appear here soon.</div>
    {% endif %}
</section>

<script>
const MCP_SNIPPET = {{ mcp_config_json | safe }};
function copyConfig() {
    const text = JSON.stringify(MCP_SNIPPET, null, 2);
    navigator.clipboard.writeText(text).then(() => {
        const hint = document.getElementById('cta-hint');
        hint.textContent = 'Copied to clipboard ✓';
        setTimeout(() => { hint.textContent = 'Click to copy the config snippet'; }, 2500);
    }).catch(() => {
        const hint = document.getElementById('cta-hint');
        hint.textContent = 'Copy failed — open scripts/mcp-config-snippet.json';
    });
}
</script>
{% endblock %}
```

- [ ] **Step 2: Verify template parses**

```bash
cd ~/Developer/markland && uv run python -c "
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('src/markland/web/templates'))
t = env.get_template('landing.html')
html = t.render(docs=[], mcp_config_json='{}')
assert 'Your agent writes' in html
print('OK, landing template rendered')
"
```

Expected output: `OK, landing template rendered`

---

### Task 7: Explore Template

**Files:**
- Create: `src/markland/web/templates/explore.html`

- [ ] **Step 1: Create `src/markland/web/templates/explore.html`**

Write the following to `src/markland/web/templates/explore.html`:

```html
{% extends "base.html" %}

{% block title %}Explore — Markland{% endblock %}
{% block nav_explore %}active{% endblock %}

{% block head_extra %}
        .explore-header {
            margin-bottom: 2rem;
        }
        .explore-header h1 {
            font-size: 1.75rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }
        .explore-header p {
            color: var(--muted);
            font-size: 0.95rem;
        }
        .search-row {
            display: flex;
            gap: 0.75rem;
            margin-bottom: 2rem;
            align-items: center;
        }
        .search-row form {
            flex: 1;
            display: flex;
            gap: 0.5rem;
        }
        .search-row input {
            flex: 1;
            padding: 0.6rem 0.85rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            background: var(--card-bg);
            color: var(--text);
            font-size: 0.95rem;
            font-family: inherit;
        }
        .search-row input:focus {
            outline: 2px solid var(--link);
            outline-offset: -1px;
        }
        .search-row button {
            padding: 0.6rem 1rem;
            background: var(--accent);
            color: var(--accent-fg);
            border: none;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.9rem;
            cursor: pointer;
            font-family: inherit;
        }
        .sort-dropdown {
            padding: 0.6rem 0.85rem;
            border: 1px solid var(--border);
            border-radius: 6px;
            background: var(--card-bg);
            color: var(--text);
            font-size: 0.9rem;
            font-family: inherit;
        }
        .result-count {
            color: var(--muted);
            font-size: 0.85rem;
            margin-bottom: 1rem;
        }
        .cards {
            column-count: 3;
            column-gap: 1rem;
        }
        .card {
            display: block;
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 1rem;
            margin: 0 0 1rem;
            break-inside: avoid;
        }
        .card:hover { border-color: var(--text); }
        .card .card-title {
            font-weight: 600;
            font-size: 1rem;
            margin-bottom: 0.4rem;
        }
        .card .card-excerpt {
            color: var(--muted);
            font-size: 0.88rem;
            margin-bottom: 0.6rem;
        }
        .card .card-meta {
            color: var(--muted);
            font-size: 0.75rem;
        }
        .empty-state {
            text-align: center;
            padding: 4rem 1rem;
            color: var(--muted);
        }
        .empty-state strong { color: var(--text); display: block; margin-bottom: 0.5rem; }
        @media (max-width: 900px) {
            .cards { column-count: 2; }
        }
        @media (max-width: 560px) {
            .cards { column-count: 1; }
            .search-row { flex-direction: column; align-items: stretch; }
        }
{% endblock %}

{% block content %}
<div class="explore-header">
    <h1>Explore</h1>
    <p>Public docs published by agents via Markland.</p>
</div>

<div class="search-row">
    <form method="get" action="/explore">
        <input type="text" name="q" placeholder="Search title or content..." value="{{ query or '' }}" autofocus>
        <button type="submit">Search</button>
    </form>
    <select class="sort-dropdown" disabled title="More sort options coming later">
        <option>Recent</option>
    </select>
</div>

{% if docs %}
{% if total > docs|length %}
<div class="result-count">Showing {{ docs|length }} of {{ total }} docs</div>
{% endif %}
<div class="cards">
    {% for doc in docs %}
    <a class="card" href="/d/{{ doc.share_token }}">
        <div class="card-title">{{ doc.title }}</div>
        {% if doc.excerpt %}<div class="card-excerpt">{{ doc.excerpt }}</div>{% endif %}
        <div class="card-meta">{{ doc.updated_at[:10] }}</div>
    </a>
    {% endfor %}
</div>
{% else %}
<div class="empty-state">
    {% if query %}
    <strong>No docs matched "{{ query }}"</strong>
    Try a different search.
    {% else %}
    <strong>Nothing here yet.</strong>
    Publish a doc from your agent to see it listed.
    {% endif %}
</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Verify template parses**

```bash
cd ~/Developer/markland && uv run python -c "
from pathlib import Path
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('src/markland/web/templates'))
t = env.get_template('explore.html')
html_empty = t.render(docs=[], query=None, total=0)
assert 'Nothing here yet' in html_empty
html_search_empty = t.render(docs=[], query='python', total=0)
assert 'No docs matched' in html_search_empty
print('OK, explore template rendered both empty states')
"
```

Expected output: `OK, explore template rendered both empty states`

---

### Task 8: Route Handlers

**Files:**
- Modify: `src/markland/web/app.py`
- Modify: `tests/test_web.py`

- [ ] **Step 1: Add failing route tests to `tests/test_web.py`**

Append to the END of `tests/test_web.py`:

```python
@pytest.fixture
def client_with_public_docs(tmp_path):
    from markland.db import init_db, insert_document, set_featured
    from markland.web.app import create_app
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    # 1 private doc, 2 public docs (one featured)
    insert_document(conn, "priv", "Private Doc", "Secret.", "priv-token", is_public=False)
    insert_document(conn, "pub1", "Public First", "Body for first public doc.", "pub1-token", is_public=True)
    insert_document(conn, "pub2", "Python Guide", "A guide to Python for agents.", "pub2-token", is_public=True)
    set_featured(conn, "pub1", is_featured=True)
    app = create_app(conn)
    return TestClient(app)


def test_landing_renders_empty(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Your agent writes" in response.text
    assert "first agent-authored docs" in response.text


def test_landing_shows_public_docs_with_featured_first(client_with_public_docs):
    response = client_with_public_docs.get("/")
    assert response.status_code == 200
    assert "Public First" in response.text
    assert "Python Guide" in response.text
    # Featured should render the Pinned badge
    assert "Pinned" in response.text
    # Private doc must NOT appear
    assert "Private Doc" not in response.text
    # Featured doc should appear before the non-featured one
    assert response.text.index("Public First") < response.text.index("Python Guide")


def test_explore_empty_shows_empty_state(client):
    response = client.get("/explore")
    assert response.status_code == 200
    assert "Nothing here yet" in response.text


def test_explore_lists_public_docs_only(client_with_public_docs):
    response = client_with_public_docs.get("/explore")
    assert response.status_code == 200
    assert "Public First" in response.text
    assert "Python Guide" in response.text
    assert "Private Doc" not in response.text


def test_explore_search_filters(client_with_public_docs):
    response = client_with_public_docs.get("/explore?q=Python")
    assert response.status_code == 200
    assert "Python Guide" in response.text
    assert "Public First" not in response.text


def test_explore_search_empty_shows_search_empty_state(client_with_public_docs):
    response = client_with_public_docs.get("/explore?q=zzznomatches")
    assert response.status_code == 200
    assert "No docs matched" in response.text
```

- [ ] **Step 2: Run tests (expect failure)**

```bash
cd ~/Developer/markland && uv run pytest tests/test_web.py -v 2>&1 | tail -25
```

Expected: new tests fail — `/` returns the placeholder HTML, `/explore` returns 404.

- [ ] **Step 3: Update `src/markland/web/app.py`**

Replace the contents of `src/markland/web/app.py` with:

```python
"""FastAPI web viewer for shared Markland documents."""

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.db import (
    get_document_by_token,
    list_featured_and_recent_public,
    list_public_documents,
)
from markland.web.renderer import make_excerpt, render_markdown

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent / "scripts"


def _load_mcp_snippet() -> dict:
    """Load the MCP config snippet for the landing-page copy button."""
    snippet_path = _SCRIPTS_DIR / "mcp-config-snippet.json"
    try:
        return json.loads(snippet_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"markland": {"type": "stdio", "command": "uv", "args": ["run", "..."]}}


def _doc_to_card(doc) -> dict:
    """Convert a Document into the dict the templates expect (adds excerpt)."""
    return {
        "id": doc.id,
        "title": doc.title,
        "share_token": doc.share_token,
        "updated_at": doc.updated_at,
        "is_public": doc.is_public,
        "is_featured": doc.is_featured,
        "excerpt": make_excerpt(doc.content),
    }


def create_app(db_conn: sqlite3.Connection) -> FastAPI:
    app = FastAPI(title="Markland", docs_url=None, redoc_url=None)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    landing_tpl = env.get_template("landing.html")
    explore_tpl = env.get_template("explore.html")
    document_tpl = env.get_template("document.html")

    mcp_snippet = _load_mcp_snippet()
    mcp_snippet_json = json.dumps(mcp_snippet)

    @app.get("/health")
    def health():
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    def landing():
        docs = list_featured_and_recent_public(db_conn, limit=8)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            landing_tpl.render(docs=cards, mcp_config_json=mcp_snippet_json)
        )

    @app.get("/explore", response_class=HTMLResponse)
    def explore(q: str | None = None):
        query = (q or "").strip() or None
        docs = list_public_documents(db_conn, query=query, limit=50)
        total_docs = list_public_documents(db_conn, query=query, limit=10_000)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            explore_tpl.render(docs=cards, query=query, total=len(total_docs))
        )

    @app.get("/d/{share_token}", response_class=HTMLResponse)
    def view_document(share_token: str):
        doc = get_document_by_token(db_conn, share_token)
        if doc is None:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Document not found</h1>"
                "</body></html>",
                status_code=404,
            )
        content_html = render_markdown(doc.content)
        html = document_tpl.render(
            title=doc.title,
            content_html=content_html,
            created_at=doc.created_at,
        )
        return HTMLResponse(html)

    return app
```

- [ ] **Step 4: Run web tests to verify pass**

```bash
cd ~/Developer/markland && uv run pytest tests/test_web.py -v 2>&1 | tail -25
```

Expected: all 10 web tests PASS (4 existing + 6 new).

- [ ] **Step 5: Run the full test suite**

```bash
cd ~/Developer/markland && uv run pytest tests/ -v 2>&1 | tail -15
```

Expected: All tests PASS (~53 total).

---

### Task 9: Extend Smoke Test

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Replace `scripts/smoke_test.py`**

Replace the contents of `scripts/smoke_test.py` with:

```python
"""Automated end-to-end smoke test.

Starts the web server in a background thread, exercises all tool functions,
verifies the shared URL renders AND the landing + explore pages work.
"""

import os
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

os.environ["MARKLAND_DATA_DIR"] = str(_ROOT / ".smoke-data")
os.environ["MARKLAND_WEB_PORT"] = "8952"
os.environ["MARKLAND_BASE_URL"] = "http://127.0.0.1:8952"

shutil.rmtree(_ROOT / ".smoke-data", ignore_errors=True)

from markland.config import get_config, reset_config  # noqa: E402

reset_config()
config = get_config()

import uvicorn  # noqa: E402

from markland.db import init_db  # noqa: E402
from markland.tools.documents import (  # noqa: E402
    delete_doc,
    feature_doc,
    get_doc,
    list_docs,
    publish_doc,
    search_docs,
    set_visibility_doc,
    share_doc,
    update_doc,
)
from markland.web.app import create_app  # noqa: E402

db_conn = init_db(config.db_path)
app = create_app(db_conn)


def start_server():
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=config.web_port, log_level="warning")
    )
    server.run()


def fetch(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def assert_ok(label: str, cond: bool, detail: str = ""):
    prefix = "PASS" if cond else "FAIL"
    print(f"[{prefix}] {label}{': ' + detail if detail else ''}")
    if not cond:
        raise SystemExit(1)


def main():
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    time.sleep(2.0)

    # Health
    code, body = fetch(f"{config.base_url}/health")
    assert_ok("health endpoint", code == 200 and '"ok"' in body)

    # Publish an unlisted doc (existing behavior)
    pub = publish_doc(db_conn, config.base_url, None, "# Private Smoke\n\nShh.")
    assert_ok("publish unlisted returns id", "id" in pub)
    assert_ok("publish unlisted defaults to is_public False", pub["is_public"] is False)
    doc_id = pub["id"]

    # Fetch the share URL
    code, body = fetch(pub["share_url"])
    assert_ok("share URL returns 200", code == 200)
    assert_ok("rendered HTML contains title", "Private Smoke" in body)

    # List / get / search / share / update / delete — smoke flow
    assert_ok("list returns one doc", len(list_docs(db_conn)) == 1)
    assert_ok("get returns content", "Shh" in get_doc(db_conn, doc_id).get("content", ""))
    assert_ok("search finds match", len(search_docs(db_conn, "Smoke")) == 1)
    assert_ok("share returns url", "share_url" in share_doc(db_conn, config.base_url, doc_id))
    updated = update_doc(db_conn, config.base_url, doc_id, content="# Updated Private\n\nChanged.")
    assert_ok("update succeeds", "error" not in updated)
    _, updated_body = fetch(pub["share_url"])
    assert_ok("updated content visible via URL", "Updated Private" in updated_body)

    # Landing should be empty (no public docs yet)
    code, landing_body = fetch(f"{config.base_url}/")
    assert_ok("landing returns 200", code == 200)
    assert_ok("landing shows empty featured", "first agent-authored docs" in landing_body)
    assert_ok("private doc hidden from landing", "Updated Private" not in landing_body)

    # Explore should be empty
    code, explore_body = fetch(f"{config.base_url}/explore")
    assert_ok("explore returns 200", code == 200)
    assert_ok("explore shows empty state", "Nothing here yet" in explore_body)

    # Now publish a public + featured doc
    public_pub = publish_doc(
        db_conn, config.base_url, "Published Smoke", "# Published Smoke\n\nSee me on the landing.", public=True
    )
    feat_result = feature_doc(db_conn, public_pub["id"], is_featured=True)
    assert_ok("feature tool succeeds", "error" not in feat_result and feat_result["is_featured"] is True)

    # Landing should now show the public doc with Pinned badge
    _, landing_body2 = fetch(f"{config.base_url}/")
    assert_ok("landing shows public featured title", "Published Smoke" in landing_body2)
    assert_ok("landing shows Pinned badge", "Pinned" in landing_body2)

    # Explore should show the public doc
    _, explore_body2 = fetch(f"{config.base_url}/explore")
    assert_ok("explore shows public doc", "Published Smoke" in explore_body2)

    # Search on explore
    _, search_body = fetch(f"{config.base_url}/explore?q=Published")
    assert_ok("explore search matches", "Published Smoke" in search_body)

    _, no_match_body = fetch(f"{config.base_url}/explore?q=zzznomatches")
    assert_ok("explore search empty-state on miss", "No docs matched" in no_match_body)

    # Visibility toggle: demote back to unlisted, confirm it disappears from explore
    demote = set_visibility_doc(db_conn, config.base_url, public_pub["id"], is_public=False)
    assert_ok("set_visibility demote succeeds", demote["is_public"] is False)
    _, explore_body3 = fetch(f"{config.base_url}/explore")
    assert_ok("demoted doc disappears from explore", "Published Smoke" not in explore_body3)

    # Cleanup
    delete_doc(db_conn, doc_id)
    delete_doc(db_conn, public_pub["id"])
    code, _ = fetch(pub["share_url"])
    assert_ok("deleted doc returns 404", code == 404)

    shutil.rmtree(_ROOT / ".smoke-data", ignore_errors=True)

    print("\n[OK] All smoke tests passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the smoke test**

```bash
cd ~/Developer/markland && uv run python scripts/smoke_test.py 2>&1 | tail -40
```

Expected: every line starts with `[PASS]`, ends with `[OK] All smoke tests passed.`

---

### Task 10: Final Verification

- [ ] **Step 1: Run full test suite**

```bash
cd ~/Developer/markland && uv run pytest tests/ -v 2>&1 | tail -20
```

Expected: All tests PASS. Totals:
- `test_db.py` — 19 tests
- `test_documents.py` — 19 tests
- `test_renderer.py` — 19 tests
- `test_web.py` — 10 tests
- **Total: 67 tests** (was 41 before this plan)

- [ ] **Step 2: Run smoke test one more time**

```bash
cd ~/Developer/markland && uv run python scripts/smoke_test.py 2>&1 | tail -40
```

Expected: `[OK] All smoke tests passed.`

- [ ] **Step 3: Verify MCP server still imports with new tools**

```bash
cd ~/Developer/markland && uv run python -c "from markland import server; print('tools:', sorted([t for t in dir(server) if t.startswith('markland_')]))"
```

Expected output:
```
tools: ['markland_delete', 'markland_feature', 'markland_get', 'markland_list', 'markland_publish', 'markland_search', 'markland_set_visibility', 'markland_share', 'markland_update']
```

- [ ] **Step 4: Visual check — start web server and load pages**

```bash
cd ~/Developer/markland && MARKLAND_WEB_PORT=8953 uv run python src/markland/run_web.py > /tmp/markland-visual.log 2>&1 &
sleep 3
curl -s http://127.0.0.1:8953/ -o /tmp/landing.html
curl -s http://127.0.0.1:8953/explore -o /tmp/explore.html
kill %1 2>/dev/null
wait 2>/dev/null
echo "Landing size: $(wc -c < /tmp/landing.html) bytes"
echo "Explore size: $(wc -c < /tmp/explore.html) bytes"
grep -q "Your agent writes" /tmp/landing.html && echo "Landing OK" || echo "Landing FAIL"
grep -q "Explore" /tmp/explore.html && echo "Explore OK" || echo "Explore FAIL"
```

Expected: Landing and Explore both render successfully, both marked OK.

- [ ] **Step 5: Report completion**

Print:

```
Markland Frontend complete.
- 67 tests passing (was 41)
- Smoke test passing with 20+ assertions (was 15)
- New routes: /, /explore
- New MCP tools: markland_set_visibility, markland_feature
- markland_publish now accepts public=True

To verify in browser:
  cd ~/Developer/markland && uv run python src/markland/run_web.py
  open http://127.0.0.1:8950/
```
