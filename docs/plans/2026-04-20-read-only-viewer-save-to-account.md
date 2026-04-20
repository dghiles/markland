# Read-only Viewer Mobile Polish + Save-to-Account Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two CSS/renderer fixes for the mobile viewer and a fork-or-bookmark "Save to Markland" CTA for non-owners on public docs.

**Architecture:** Additive migrations on the existing SQLite schema (one column + one table). One new service module (`service/save.py`), one new web router (`web/save_routes.py`), one new signed cookie (reusing the existing `session_secret`), one Jinja partial included into `document.html`. No framework changes; no feature flag.

**Tech Stack:** FastAPI, Jinja2, SQLite (stdlib `sqlite3`), `itsdangerous` (already used for `mk_session`), `markdown-it-py`, vanilla CSS/JS, `pytest` + FastAPI `TestClient`, Playwright MCP for mobile verification.

**Spec:** `docs/specs/2026-04-19-read-only-viewer-save-to-account-design.md`

---

## File Structure

**Create:**
- `src/markland/service/save.py` — `fork_document()` + bookmark helpers.
- `src/markland/service/pending_intent.py` — signed-cookie helpers for the logged-out resume flow.
- `src/markland/web/save_routes.py` — FastAPI router for `/d/{token}/fork`, `/d/{token}/bookmark`, `/resume`.
- `src/markland/web/templates/_save_dialog.html` — Jinja partial (desktop popover + mobile sticky bar + bottom sheet).
- `tests/test_renderer_mobile.py`
- `tests/test_db_bookmarks_and_forks.py`
- `tests/test_service_save.py`
- `tests/test_pending_intent.py`
- `tests/test_save_routes.py`
- `tests/test_resume_flow.py`
- `tests/test_dashboard_bookmarks.py`
- `tests/test_document_view_forked_from.py`

**Modify:**
- `src/markland/db.py` — migration + bookmarks CRUD + list helper + `_DOC_COLUMNS` update.
- `src/markland/models.py` — add `forked_from_doc_id` to `Document`.
- `src/markland/web/renderer.py` — wrap `<table>` in `<div class="table-scroll">`.
- `src/markland/web/templates/document.html` — CSS fixes, `_save_dialog.html` include, fork-attribution line.
- `src/markland/web/app.py:321-371` (`view_document`) — resolve `forked_from`, pass to template.
- `src/markland/web/auth_routes.py:124-154` (`verify_page`) — check pending-intent cookie and route to `/resume` when present.
- `src/markland/web/dashboard.py` — pass `bookmarks` to the template.
- `src/markland/web/templates/dashboard.html` — render "Saved" section.

---

## Execution conventions

- **Run the test suite** with `uv run pytest <path> -v` from the repo root. Full suite is `uv run pytest tests/ -v`.
- **Commits:** one per task (or sub-task where noted). Do not squash across tasks.
- **Import style:** follow `from markland.module import thing` (see `src/markland/web/app.py` for the pattern).
- **Datetime:** use `Document.now()` (UTC ISO) for any new timestamps — it matches the rest of the codebase.
- **Principal access in routes:** `principal = getattr(request.state, "principal", None)` — set by `principal_middleware`. The user's id is `principal.principal_id` when `principal.principal_type == "user"`.

---

## Task 1: Mobile CSS fixes + table scroll wrapper

**Files:**
- Modify: `src/markland/web/renderer.py`
- Modify: `src/markland/web/templates/document.html:85-205` (CSS block) and `document.html:233-235` (`.content` div)
- Test: `tests/test_renderer_mobile.py`

This task removes page-level horizontal scroll at 375px by: (a) wrapping rendered `<table>` in a scroll container, (b) applying `overflow-wrap: anywhere` to content elements and inline `<code>`.

- [ ] **Step 1: Write the failing renderer test**

Create `tests/test_renderer_mobile.py`:

```python
"""Mobile-rendering guarantees: wide tables get a horizontal scroll wrapper."""

from markland.web.renderer import render_markdown


def test_table_is_wrapped_in_scroll_container():
    md = (
        "| A | B | C | D | E |\n"
        "|---|---|---|---|---|\n"
        "| 1 | 2 | 3 | 4 | 5 |\n"
    )
    html = render_markdown(md)
    assert '<div class="table-scroll">' in html
    assert "</div>" in html
    # Sanity: the wrapper closes before the next block. No nested table-scroll.
    assert html.count('<div class="table-scroll">') == 1
    assert html.count("<table>") == 1


def test_non_table_markdown_has_no_wrapper():
    html = render_markdown("# Heading\n\nA paragraph.")
    assert "table-scroll" not in html
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/test_renderer_mobile.py -v`
Expected: FAIL — `'<div class="table-scroll">' in html` is False.

- [ ] **Step 3: Implement the renderer override**

Edit `src/markland/web/renderer.py`. Replace the `_build_markdown_renderer()` body so that after `md.use(tasklists_plugin)`, the table rules are overridden:

```python
def _build_markdown_renderer() -> MarkdownIt:
    md = MarkdownIt(
        "gfm-like",
        {
            "html": False,
            "linkify": False,
            "typographer": True,
            "highlight": _highlight_code,
        },
    )
    md.use(tasklists_plugin)

    default_table_open = md.renderer.rules.get("table_open")
    default_table_close = md.renderer.rules.get("table_close")

    def table_open(tokens, idx, options, env):
        inner = (
            default_table_open(tokens, idx, options, env)
            if default_table_open
            else "<table>\n"
        )
        return '<div class="table-scroll">' + inner

    def table_close(tokens, idx, options, env):
        inner = (
            default_table_close(tokens, idx, options, env)
            if default_table_close
            else "</table>\n"
        )
        return inner + "</div>\n"

    md.renderer.rules["table_open"] = table_open
    md.renderer.rules["table_close"] = table_close
    return md
```

- [ ] **Step 4: Run the test — should pass**

Run: `uv run pytest tests/test_renderer_mobile.py -v`
Expected: PASS on both tests.

- [ ] **Step 5: Apply the CSS fixes in `document.html`**

Open `src/markland/web/templates/document.html`. In the `<style>` block, add these rules after the existing `.content img` rule (around line 187, before the Pygments tokens section):

```css
.content, .content p, .content li, .content td, .content th {
    overflow-wrap: anywhere;
    word-break: break-word;
}
.content code { overflow-wrap: anywhere; }

.content .table-scroll {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin: 1.3rem 0;
    border: 1px solid var(--outline);
    border-radius: var(--radius);
}
.content .table-scroll table {
    margin: 0;
    border: none;
    border-radius: 0;
}
```

The existing `.content table` rule (lines 160–170) keeps defining typography/padding; the new `.content .table-scroll` rule supplies the outer border+radius that the table itself used to carry.

- [ ] **Step 6: Smoke-run the suite to confirm no regression**

Run: `uv run pytest tests/ -v`
Expected: all tests still pass (plus the two new ones).

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/renderer.py src/markland/web/templates/document.html tests/test_renderer_mobile.py
git commit -m "fix(viewer): wrap tables in scroll container and wrap long tokens on mobile"
```

---

## Task 2: Schema migration — `forked_from_doc_id` + `bookmarks`

**Files:**
- Modify: `src/markland/db.py:23-80` (`init_db`) and `src/markland/db.py:257` (`_DOC_COLUMNS`) and `src/markland/db.py:241-253` (`_row_to_doc`)
- Modify: `src/markland/models.py:8-31` (`Document` dataclass)
- Test: `tests/test_db_bookmarks_and_forks.py`

- [ ] **Step 1: Write the failing schema test**

Create `tests/test_db_bookmarks_and_forks.py`:

```python
"""Migrations + bookmarks CRUD for the save-to-account feature."""

from pathlib import Path

from markland.db import init_db


def _column_names(conn, table: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?", (table,)
    ).fetchone()
    return row is not None


def test_init_db_adds_forked_from_and_bookmarks(tmp_path: Path):
    db = tmp_path / "markland.db"
    conn = init_db(db)

    assert "forked_from_doc_id" in _column_names(conn, "documents")
    assert _table_exists(conn, "bookmarks")

    cols = _column_names(conn, "bookmarks")
    assert cols == ["user_id", "doc_id", "created_at"]


def test_init_db_is_idempotent_on_reinit(tmp_path: Path):
    db = tmp_path / "markland.db"
    conn_a = init_db(db)
    conn_a.close()
    conn_b = init_db(db)  # second run must not raise

    assert "forked_from_doc_id" in _column_names(conn_b, "documents")
    assert _table_exists(conn_b, "bookmarks")
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/test_db_bookmarks_and_forks.py -v`
Expected: FAIL — column and table missing.

- [ ] **Step 3: Add the `forked_from_doc_id` column + `bookmarks` table in `init_db()`**

Edit `src/markland/db.py`, inside `init_db()` right after the existing `_add_column_if_missing(conn, "documents", "version", ...)` call (line 45):

```python
    _add_column_if_missing(
        conn, "documents", "forked_from_doc_id", "TEXT"
    )
```

SQLite does not enforce `REFERENCES` on `ADD COLUMN`; we keep the reference in the create-table path for new DBs and rely on application code for parent resolution on existing DBs. Also update the inline `CREATE TABLE documents` literal (line 28) to add the new column to new DBs:

Change:
```python
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
            owner_id TEXT,
            version INTEGER NOT NULL DEFAULT 1
        )
    """)
```

To:
```python
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
            owner_id TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            forked_from_doc_id TEXT REFERENCES documents(id) ON DELETE SET NULL
        )
    """)
```

Then add the bookmarks table at the bottom of the `CREATE TABLE` block, just before the `CREATE INDEX` lines for `idx_share_token`:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks (
            user_id    TEXT NOT NULL,
            doc_id     TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (user_id, doc_id),
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id)"
    )
```

- [ ] **Step 4: Update `_DOC_COLUMNS` and `_row_to_doc` so Document queries pull the new column**

Edit `src/markland/db.py`. Change the `_DOC_COLUMNS` constant (around line 256):

```python
_DOC_COLUMNS = (
    "id, title, content, share_token, created_at, updated_at, "
    "is_public, is_featured, owner_id, version, forked_from_doc_id"
)
```

Update `_row_to_doc` (around line 241) to include the new column:

```python
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
        version=row[9],
        forked_from_doc_id=row[10],
    )
```

Update `insert_document` (around line 262) so the column list matches. The current insert omits `forked_from_doc_id`; SQLite will default it to NULL, which is correct for non-fork publishes. Add an optional keyword argument so fork callers can pass it:

```python
def insert_document(
    conn: sqlite3.Connection,
    doc_id: str,
    title: str,
    content: str,
    share_token: str,
    is_public: bool = False,
    owner_id: str | None = None,
    forked_from_doc_id: str | None = None,
) -> str:
    now = Document.now()
    conn.execute(
        f"""
        INSERT INTO documents ({_DOC_COLUMNS})
        VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 1, ?)
        """,
        (
            doc_id, title, content, share_token, now, now,
            1 if is_public else 0, owner_id, forked_from_doc_id,
        ),
    )
    conn.commit()
    return doc_id
```

- [ ] **Step 5: Add `forked_from_doc_id` to the `Document` dataclass**

Edit `src/markland/models.py:8-19`. Append the new field:

```python
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
    version: int = 1
    forked_from_doc_id: str | None = None
```

- [ ] **Step 6: Run the schema test + the full suite**

Run: `uv run pytest tests/test_db_bookmarks_and_forks.py -v`
Expected: PASS.

Then: `uv run pytest tests/ -v`
Expected: all green. If an existing test instantiates `Document(...)` positionally, review whether the added trailing default field is safe (it is — it has a default).

- [ ] **Step 7: Commit**

```bash
git add src/markland/db.py src/markland/models.py tests/test_db_bookmarks_and_forks.py
git commit -m "feat(db): add forked_from_doc_id column and bookmarks table"
```

---

## Task 3: `db.py` bookmarks CRUD helpers

**Files:**
- Modify: `src/markland/db.py`
- Test: `tests/test_db_bookmarks_and_forks.py` (extend)

- [ ] **Step 1: Write failing tests for the helpers**

Append to `tests/test_db_bookmarks_and_forks.py`:

```python
from markland.db import (
    init_db,
    insert_document,
    list_bookmarks_for_user,
    remove_bookmark,
    upsert_bookmark,
)
from markland.models import Document


def _seed_doc(conn, *, owner_id: str = "user_owner", is_public: bool = True) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, "T", "C", share, is_public=is_public, owner_id=owner_id,
    )
    return Document(
        id=doc_id, title="T", content="C", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=is_public, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_upsert_bookmark_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "m.db")
    doc = _seed_doc(conn)

    upsert_bookmark(conn, user_id="u1", doc_id=doc.id)
    upsert_bookmark(conn, user_id="u1", doc_id=doc.id)

    rows = conn.execute(
        "SELECT user_id, doc_id FROM bookmarks"
    ).fetchall()
    assert rows == [("u1", doc.id)]


def test_remove_bookmark_noop_when_missing(tmp_path):
    conn = init_db(tmp_path / "m.db")
    doc = _seed_doc(conn)
    # Remove without inserting — must not raise, must return False.
    removed = remove_bookmark(conn, user_id="u1", doc_id=doc.id)
    assert removed is False


def test_list_bookmarks_filters_to_visible_public_docs_and_orders_by_created_at_desc(tmp_path):
    conn = init_db(tmp_path / "m.db")
    doc_a = _seed_doc(conn, is_public=True)
    doc_b = _seed_doc(conn, is_public=True)
    doc_priv = _seed_doc(conn, is_public=False)

    # Oldest first in insert order; reverse in return.
    upsert_bookmark(conn, user_id="u1", doc_id=doc_a.id)
    upsert_bookmark(conn, user_id="u1", doc_id=doc_b.id)
    upsert_bookmark(conn, user_id="u1", doc_id=doc_priv.id)

    docs = list_bookmarks_for_user(conn, user_id="u1")
    ids = [d.id for d in docs]
    # Private doc filtered out (u1 has no grant on it).
    assert doc_priv.id not in ids
    # Newest first.
    assert ids == [doc_b.id, doc_a.id]


def test_bookmarks_cascade_on_doc_delete(tmp_path):
    from markland.db import delete_document

    conn = init_db(tmp_path / "m.db")
    doc = _seed_doc(conn)
    upsert_bookmark(conn, user_id="u1", doc_id=doc.id)

    delete_document(conn, doc.id)

    rows = conn.execute("SELECT * FROM bookmarks").fetchall()
    assert rows == []
```

- [ ] **Step 2: Run — expected FAIL** (imports missing)

Run: `uv run pytest tests/test_db_bookmarks_and_forks.py -v`
Expected: ImportError on `upsert_bookmark`, `remove_bookmark`, `list_bookmarks_for_user`.

- [ ] **Step 3: Implement the helpers in `db.py`**

Append to `src/markland/db.py` (beneath the existing bookmark-adjacent helpers; anywhere below `list_grants_for_doc` is fine):

```python
def upsert_bookmark(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    doc_id: str,
) -> None:
    """Insert a bookmark. No-op if the row already exists."""
    conn.execute(
        """
        INSERT INTO bookmarks (user_id, doc_id, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, doc_id) DO NOTHING
        """,
        (user_id, doc_id, Document.now()),
    )
    conn.commit()


def remove_bookmark(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    doc_id: str,
) -> bool:
    """Remove a bookmark. Returns True iff a row was deleted."""
    cursor = conn.execute(
        "DELETE FROM bookmarks WHERE user_id = ? AND doc_id = ?",
        (user_id, doc_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_bookmarks_for_user(
    conn: sqlite3.Connection,
    *,
    user_id: str,
) -> list[Document]:
    """Return docs the user has bookmarked AND can still view (public or granted)."""
    rows = conn.execute(
        f"""
        SELECT {_DOC_COLUMNS}
        FROM documents d
        JOIN bookmarks b ON b.doc_id = d.id
        WHERE b.user_id = ?
          AND (
              d.is_public = 1
              OR EXISTS (
                  SELECT 1 FROM grants g
                  WHERE g.doc_id = d.id AND g.principal_id = ?
              )
          )
        ORDER BY b.created_at DESC
        """,
        (user_id, user_id),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]
```

- [ ] **Step 4: Run the new tests**

Run: `uv run pytest tests/test_db_bookmarks_and_forks.py -v`
Expected: PASS on all four new tests.

- [ ] **Step 5: Commit**

```bash
git add src/markland/db.py tests/test_db_bookmarks_and_forks.py
git commit -m "feat(db): bookmark upsert/remove/list helpers"
```

---

## Task 4: Fork service — `service/save.py::fork_document`

**Files:**
- Create: `src/markland/service/save.py`
- Test: `tests/test_service_save.py`

`fork_document` is the write-path counterpart to `service/docs.py::publish`. It copies a source doc into a new doc owned by a new user, seeds revision 1, and stores the parent pointer.

- [ ] **Step 1: Write failing tests**

Create `tests/test_service_save.py`:

```python
"""fork_document + toggle_bookmark service helpers."""

import pytest

from markland.db import (
    init_db,
    insert_document,
    get_document,
    upsert_grant,
)
from markland.models import Document, Grant
from markland.service.save import (
    fork_document,
    toggle_bookmark,
)


def _seed(conn, *, owner_id="user_owner", is_public=True) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, "Original Title", "Original content.", share,
        is_public=is_public, owner_id=owner_id,
    )
    doc = get_document(conn, doc_id)
    assert doc is not None
    return doc


def test_fork_creates_new_doc_owned_by_new_user_with_pointer(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=True)

    fork = fork_document(conn, source=source, new_owner_id="bob")

    assert fork.id != source.id
    assert fork.share_token != source.share_token
    assert fork.title == source.title
    assert fork.content == source.content
    assert fork.owner_id == "bob"
    assert fork.is_public is False  # forks default to private
    assert fork.forked_from_doc_id == source.id

    # Revision 1 seeded.
    n = conn.execute(
        "SELECT COUNT(*) FROM revisions WHERE doc_id = ?", (fork.id,)
    ).fetchone()[0]
    assert n == 1


def test_fork_rejects_owner_forking_own_doc(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=True)

    with pytest.raises(ValueError):
        fork_document(conn, source=source, new_owner_id="alice")


def test_fork_rejects_private_doc_without_grant(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=False)

    with pytest.raises(PermissionError):
        fork_document(conn, source=source, new_owner_id="bob")


def test_fork_allows_private_doc_with_view_grant(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=False)
    upsert_grant(
        conn,
        doc_id=source.id,
        principal_id="bob",
        principal_type="user",
        level="view",
        granted_by="alice",
    )

    fork = fork_document(conn, source=source, new_owner_id="bob")
    assert fork.owner_id == "bob"


def test_toggle_bookmark_insert_then_remove(tmp_path):
    conn = init_db(tmp_path / "m.db")
    source = _seed(conn, owner_id="alice", is_public=True)

    toggle_bookmark(conn, user_id="bob", doc_id=source.id, bookmarked=True)
    toggle_bookmark(conn, user_id="bob", doc_id=source.id, bookmarked=True)  # idempotent

    rows = conn.execute("SELECT user_id FROM bookmarks").fetchall()
    assert rows == [("bob",)]

    toggle_bookmark(conn, user_id="bob", doc_id=source.id, bookmarked=False)
    rows = conn.execute("SELECT user_id FROM bookmarks").fetchall()
    assert rows == []
```

Note on `upsert_grant`: check the existing signature in `db.py` (around line 536). If the kwarg names differ (e.g. `by_user_id` instead of `granted_by`), adjust the test's call to match the real signature — do NOT invent new kwargs.

- [ ] **Step 2: Run — expected FAIL** (module doesn't exist)

Run: `uv run pytest tests/test_service_save.py -v`
Expected: ImportError on `markland.service.save`.

- [ ] **Step 3: Implement `service/save.py`**

Create `src/markland/service/save.py`:

```python
"""Save-to-account service helpers: fork a public doc, toggle a bookmark."""

from __future__ import annotations

import sqlite3

from markland import db
from markland.models import Document


def _user_can_view(
    conn: sqlite3.Connection, *, doc: Document, user_id: str
) -> bool:
    """A user can view if the doc is public, they own it, or they hold a grant."""
    if doc.is_public:
        return True
    if doc.owner_id == user_id:
        return True
    row = conn.execute(
        "SELECT 1 FROM grants WHERE doc_id = ? AND principal_id = ?",
        (doc.id, user_id),
    ).fetchone()
    return row is not None


def fork_document(
    conn: sqlite3.Connection,
    *,
    source: Document,
    new_owner_id: str,
) -> Document:
    """Copy `source` into a new doc owned by `new_owner_id`; seed revision 1.

    Raises:
        ValueError: if `new_owner_id` is the same as the source's owner.
        PermissionError: if `new_owner_id` cannot view the source.
    """
    if source.owner_id == new_owner_id:
        raise ValueError("cannot_fork_own_doc")
    if not _user_can_view(conn, doc=source, user_id=new_owner_id):
        raise PermissionError("source_not_viewable")

    new_id = Document.generate_id()
    new_share = Document.generate_share_token()
    db.insert_document(
        conn,
        new_id,
        source.title,
        source.content,
        new_share,
        is_public=False,
        owner_id=new_owner_id,
        forked_from_doc_id=source.id,
    )
    db.insert_revision(
        conn,
        doc_id=new_id,
        version=1,
        title=source.title,
        content=source.content,
        principal_id=new_owner_id,
        principal_type="user",
    )
    forked = db.get_document(conn, new_id)
    assert forked is not None
    return forked


def toggle_bookmark(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    doc_id: str,
    bookmarked: bool,
) -> None:
    """Upsert when `bookmarked=True`, remove when `bookmarked=False`. Idempotent."""
    if bookmarked:
        db.upsert_bookmark(conn, user_id=user_id, doc_id=doc_id)
    else:
        db.remove_bookmark(conn, user_id=user_id, doc_id=doc_id)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_service_save.py -v`
Expected: PASS on all five.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/save.py tests/test_service_save.py
git commit -m "feat(service): fork_document and toggle_bookmark helpers"
```

---

## Task 5: Pending-intent cookie module

**Files:**
- Create: `src/markland/service/pending_intent.py`
- Test: `tests/test_pending_intent.py`

This module is a narrow wrapper around `itsdangerous` that signs/reads a `{action, share_token, exp}` payload and exposes cookie name + TTL constants. It mirrors the style of `service/sessions.py`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_pending_intent.py`:

```python
"""Signed pending-intent cookies for the logged-out save-to-account resume flow."""

import time

import pytest

from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    PENDING_INTENT_MAX_AGE_SECONDS,
    InvalidPendingIntent,
    PendingIntent,
    issue_pending_intent,
    read_pending_intent,
)


SECRET = "test-secret"


def test_roundtrip_signed_payload():
    token = issue_pending_intent(
        secret=SECRET,
        action="fork",
        share_token="abc123",
    )
    intent = read_pending_intent(token, secret=SECRET)
    assert intent == PendingIntent(action="fork", share_token="abc123")


def test_read_rejects_tampered_token():
    token = issue_pending_intent(
        secret=SECRET, action="bookmark", share_token="abc123"
    )
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    with pytest.raises(InvalidPendingIntent):
        read_pending_intent(tampered, secret=SECRET)


def test_read_rejects_wrong_secret():
    token = issue_pending_intent(secret=SECRET, action="fork", share_token="x")
    with pytest.raises(InvalidPendingIntent):
        read_pending_intent(token, secret="other-secret")


def test_read_rejects_unknown_action():
    # Issuing with a bogus action should fail fast.
    with pytest.raises(ValueError):
        issue_pending_intent(secret=SECRET, action="explode", share_token="x")


def test_cookie_name_and_max_age_constants():
    assert PENDING_INTENT_COOKIE_NAME == "markland_pending_intent"
    assert PENDING_INTENT_MAX_AGE_SECONDS == 30 * 60
```

- [ ] **Step 2: Run — expected FAIL**

Run: `uv run pytest tests/test_pending_intent.py -v`
Expected: ImportError on `markland.service.pending_intent`.

- [ ] **Step 3: Implement the module**

Create `src/markland/service/pending_intent.py`:

```python
"""Signed cookie for 'resume this action after login' on the save-to-account flow.

Cookie name: `markland_pending_intent`. Payload: `{action, share_token}`,
signed via itsdangerous with the same `session_secret` used for `mk_session`.
TTL: 30 minutes — long enough for an email magic link to arrive and be clicked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from itsdangerous import BadSignature, SignatureExpired
from itsdangerous.serializer import Serializer
from itsdangerous import TimestampSigner

PENDING_INTENT_COOKIE_NAME = "markland_pending_intent"
PENDING_INTENT_MAX_AGE_SECONDS = 30 * 60  # 30 minutes
_SALT = "mk.pending_intent.v1"

_VALID_ACTIONS = ("fork", "bookmark")


class InvalidPendingIntent(Exception):
    """Raised when a pending-intent token is missing, tampered, or expired."""


@dataclass(frozen=True)
class PendingIntent:
    action: Literal["fork", "bookmark"]
    share_token: str


def _signer(secret: str) -> TimestampSigner:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return TimestampSigner(secret, salt=_SALT)


def issue_pending_intent(
    *,
    secret: str,
    action: str,
    share_token: str,
) -> str:
    """Return a signed cookie value carrying `{action, share_token}`."""
    if action not in _VALID_ACTIONS:
        raise ValueError(f"invalid action: {action!r}")
    if not share_token:
        raise ValueError("share_token must be non-empty")
    serializer = Serializer(secret, salt=_SALT)
    raw = serializer.dumps({"action": action, "share_token": share_token})
    return _signer(secret).sign(raw.encode("utf-8")).decode("utf-8")


def read_pending_intent(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = PENDING_INTENT_MAX_AGE_SECONDS,
) -> PendingIntent:
    """Parse a cookie. Raises `InvalidPendingIntent` on any failure."""
    if not token:
        raise InvalidPendingIntent("empty token")
    try:
        unsigned = _signer(secret).unsign(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidPendingIntent("expired") from e
    except BadSignature as e:
        raise InvalidPendingIntent("bad signature") from e
    try:
        serializer = Serializer(secret, salt=_SALT)
        payload = serializer.loads(unsigned.decode("utf-8"))
    except BadSignature as e:
        raise InvalidPendingIntent("bad payload") from e
    if not isinstance(payload, dict):
        raise InvalidPendingIntent("malformed payload")
    action = payload.get("action")
    share_token = payload.get("share_token")
    if action not in _VALID_ACTIONS or not isinstance(share_token, str) or not share_token:
        raise InvalidPendingIntent("malformed payload")
    return PendingIntent(action=action, share_token=share_token)
```

- [ ] **Step 4: Run**

Run: `uv run pytest tests/test_pending_intent.py -v`
Expected: PASS on all five.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/pending_intent.py tests/test_pending_intent.py
git commit -m "feat(auth): signed pending-intent cookie for post-login action resume"
```

---

## Task 6: Save routes — `/fork`, `/bookmark` (POST/DELETE)

**Files:**
- Create: `src/markland/web/save_routes.py`
- Modify: `src/markland/web/app.py` (register router)
- Test: `tests/test_save_routes.py`

Auth behavior:
- Anonymous `POST /fork` or `/bookmark` → set pending-intent cookie, redirect to `/login?next=/resume`.
- Logged-in non-owner `POST /fork` → run `fork_document`, 303 to `/d/{new_token}`.
- Owner `POST /fork` → 400 JSON.
- Logged-in `POST /bookmark` → `toggle_bookmark(..., True)`, 303 back to the source doc.
- Logged-in `DELETE /bookmark` → `toggle_bookmark(..., False)`, 303 back to the source doc.
- Anonymous `DELETE /bookmark` → 401.

The `/resume` route lives in the next task (Task 7) to keep diffs small; this task stops at setting the cookie.

- [ ] **Step 1: Check how existing routers are mounted**

Read `src/markland/web/app.py:373-399` to see the `build_auth_router` / `build_identity_router` / `build_grants_router` / `build_dashboard_router` pattern. New router must accept `conn`, `session_secret`, and `base_url` kwargs the same way.

- [ ] **Step 2: Write failing route tests**

Create `tests/test_save_routes.py`:

```python
"""Integration tests for /d/{token}/fork and /d/{token}/bookmark."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, insert_document, upsert_grant
from markland.models import Document
from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    read_pending_intent,
)
from markland.service.sessions import issue_session
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build_app_and_conn(tmp_path):
    db = tmp_path / "m.db"
    conn = init_db(db)
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://test")
    return app, conn


def _seed_public_doc(conn, *, owner_id="alice") -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, "T", "body", share, is_public=True, owner_id=owner_id)
    return Document(
        id=doc_id, title="T", content="body", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=True, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def _make_user(conn, email: str) -> str:
    return upsert_user_by_email(conn, email).id


def _login_cookie(user_id: str) -> str:
    return issue_session(user_id, secret=SECRET)


def test_anonymous_fork_sets_pending_intent_and_redirects_to_login(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn)
    client = TestClient(app)

    r = client.post(f"/d/{doc.share_token}/fork", follow_redirects=False)

    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]
    assert "next=%2Fresume" in r.headers["location"] or "next=/resume" in r.headers["location"]

    intent_cookie = r.cookies.get(PENDING_INTENT_COOKIE_NAME)
    assert intent_cookie
    intent = read_pending_intent(intent_cookie, secret=SECRET)
    assert intent.action == "fork"
    assert intent.share_token == doc.share_token


def test_logged_in_non_owner_fork_creates_copy_and_redirects(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn, owner_id=_make_user(conn, "alice@example.com"))
    bob_id = _make_user(conn, "bob@example.com")
    client = TestClient(app)

    r = client.post(
        f"/d/{doc.share_token}/fork",
        cookies={"mk_session": _login_cookie(bob_id)},
        follow_redirects=False,
    )

    assert r.status_code in (302, 303)
    assert r.headers["location"].startswith("/d/")
    # New share token — never the same as the source.
    new_token = r.headers["location"].rsplit("/", 1)[-1]
    assert new_token != doc.share_token

    new_doc = conn.execute(
        "SELECT owner_id, forked_from_doc_id, is_public FROM documents WHERE share_token = ?",
        (new_token,),
    ).fetchone()
    assert new_doc[0] == bob_id
    assert new_doc[1] == doc.id
    assert new_doc[2] == 0  # forks private by default


def test_owner_fork_returns_400(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    doc = _seed_public_doc(conn, owner_id=alice)
    client = TestClient(app)

    r = client.post(
        f"/d/{doc.share_token}/fork",
        cookies={"mk_session": _login_cookie(alice)},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_fork_private_doc_without_grant_returns_403(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    alice = _make_user(conn, "alice@example.com")
    bob = _make_user(conn, "bob@example.com")

    # Private doc.
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, "T", "body", share, is_public=False, owner_id=alice)

    client = TestClient(app)
    r = client.post(
        f"/d/{share}/fork",
        cookies={"mk_session": _login_cookie(bob)},
        follow_redirects=False,
    )
    assert r.status_code == 403


def test_bookmark_is_idempotent(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    bob = _make_user(conn, "bob@example.com")
    doc = _seed_public_doc(conn, owner_id=_make_user(conn, "alice@example.com"))
    client = TestClient(app)
    cookies = {"mk_session": _login_cookie(bob)}

    r1 = client.post(f"/d/{doc.share_token}/bookmark", cookies=cookies, follow_redirects=False)
    r2 = client.post(f"/d/{doc.share_token}/bookmark", cookies=cookies, follow_redirects=False)
    assert r1.status_code in (302, 303)
    assert r2.status_code in (302, 303)

    rows = conn.execute(
        "SELECT user_id FROM bookmarks WHERE user_id = ? AND doc_id = ?", (bob, doc.id)
    ).fetchall()
    assert len(rows) == 1


def test_anonymous_bookmark_sets_pending_intent_and_redirects(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn)
    client = TestClient(app)

    r = client.post(f"/d/{doc.share_token}/bookmark", follow_redirects=False)
    assert r.status_code in (302, 303)
    intent_cookie = r.cookies.get(PENDING_INTENT_COOKIE_NAME)
    assert intent_cookie
    intent = read_pending_intent(intent_cookie, secret=SECRET)
    assert intent.action == "bookmark"
    assert intent.share_token == doc.share_token


def test_delete_bookmark_removes_row(tmp_path):
    from markland.db import upsert_bookmark

    app, conn = _build_app_and_conn(tmp_path)
    bob = _make_user(conn, "bob@example.com")
    doc = _seed_public_doc(conn, owner_id=_make_user(conn, "alice@example.com"))
    upsert_bookmark(conn, user_id=bob, doc_id=doc.id)
    client = TestClient(app)

    r = client.delete(
        f"/d/{doc.share_token}/bookmark",
        cookies={"mk_session": _login_cookie(bob)},
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303)
    rows = conn.execute("SELECT * FROM bookmarks").fetchall()
    assert rows == []


def test_anonymous_delete_bookmark_returns_401(tmp_path):
    app, conn = _build_app_and_conn(tmp_path)
    doc = _seed_public_doc(conn)
    client = TestClient(app)

    r = client.delete(f"/d/{doc.share_token}/bookmark", follow_redirects=False)
    assert r.status_code == 401
```

- [ ] **Step 3: Run — expected FAIL**

Run: `uv run pytest tests/test_save_routes.py -v`
Expected: 404s everywhere — routes don't exist.

- [ ] **Step 4: Implement the router**

Create `src/markland/web/save_routes.py`:

```python
"""POST /d/{token}/fork, POST /d/{token}/bookmark, DELETE /d/{token}/bookmark."""

from __future__ import annotations

import sqlite3
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from markland.db import get_document_by_token
from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    PENDING_INTENT_MAX_AGE_SECONDS,
    issue_pending_intent,
)
from markland.service.save import fork_document, toggle_bookmark


def _current_user_id(request: Request) -> str | None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return None
    if getattr(principal, "principal_type", None) != "user":
        return None
    return principal.principal_id


def _set_pending_cookie(resp: RedirectResponse, cookie_value: str, *, secure: bool) -> None:
    resp.set_cookie(
        key=PENDING_INTENT_COOKIE_NAME,
        value=cookie_value,
        max_age=PENDING_INTENT_MAX_AGE_SECONDS,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def build_router(
    *,
    conn: sqlite3.Connection,
    session_secret: str,
    base_url: str,
) -> APIRouter:
    r = APIRouter()
    secure_cookie = base_url.startswith("https://")

    def _start_login_with_intent(action: str, share_token: str) -> RedirectResponse:
        cookie = issue_pending_intent(
            secret=session_secret, action=action, share_token=share_token
        )
        resp = RedirectResponse(
            url=f"/login?next={quote('/resume', safe='')}", status_code=303
        )
        _set_pending_cookie(resp, cookie, secure=secure_cookie)
        return resp

    @r.post("/d/{share_token}/fork")
    def fork_doc(share_token: str, request: Request):
        doc = get_document_by_token(conn, share_token)
        if doc is None:
            raise HTTPException(404, "document_not_found")

        user_id = _current_user_id(request)
        if user_id is None:
            return _start_login_with_intent("fork", share_token)

        try:
            new_doc = fork_document(conn, source=doc, new_owner_id=user_id)
        except ValueError:
            raise HTTPException(400, "cannot_fork_own_doc")
        except PermissionError:
            raise HTTPException(403, "source_not_viewable")

        return RedirectResponse(f"/d/{new_doc.share_token}", status_code=303)

    @r.post("/d/{share_token}/bookmark")
    def add_bookmark(share_token: str, request: Request):
        doc = get_document_by_token(conn, share_token)
        if doc is None:
            raise HTTPException(404, "document_not_found")

        user_id = _current_user_id(request)
        if user_id is None:
            return _start_login_with_intent("bookmark", share_token)

        # Re-check visibility at action time to prevent TOCTOU on stale links.
        from markland.service.save import _user_can_view

        if not _user_can_view(conn, doc=doc, user_id=user_id):
            raise HTTPException(403, "source_not_viewable")

        toggle_bookmark(conn, user_id=user_id, doc_id=doc.id, bookmarked=True)
        return RedirectResponse(f"/d/{share_token}", status_code=303)

    @r.delete("/d/{share_token}/bookmark")
    def remove_bookmark_route(share_token: str, request: Request):
        user_id = _current_user_id(request)
        if user_id is None:
            raise HTTPException(401, "login_required")

        doc = get_document_by_token(conn, share_token)
        if doc is None:
            raise HTTPException(404, "document_not_found")

        toggle_bookmark(conn, user_id=user_id, doc_id=doc.id, bookmarked=False)
        return JSONResponse({"bookmarked": False})

    return r
```

Note: the `_user_can_view` import is from the `service/save.py` module created in Task 4. It's a private helper there; import via `from markland.service.save import _user_can_view` is deliberate — both modules are internal. If this feels wrong, the plan-reviewer can promote `_user_can_view` to `user_can_view` (public) in Task 4 with no other cost.

- [ ] **Step 5: Mount the router in `create_app`**

Edit `src/markland/web/app.py`. Below the existing `app.include_router(build_dashboard_router(conn=db_conn))` near line 398, add:

```python
    from markland.web.save_routes import build_router as build_save_router
    app.include_router(
        build_save_router(
            conn=db_conn,
            session_secret=session_secret,
            base_url=base_url,
        )
    )
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_save_routes.py -v`
Expected: all eight tests PASS.

Then: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/save_routes.py src/markland/web/app.py tests/test_save_routes.py
git commit -m "feat(web): /fork and /bookmark routes with logged-out intent capture"
```

---

## Task 7: `/resume` route + auth landing hook

**Files:**
- Modify: `src/markland/web/save_routes.py` (add `GET /resume`)
- Modify: `src/markland/web/auth_routes.py:124-154` (`verify_page`): redirect to `/resume` when pending-intent cookie is present
- Test: `tests/test_resume_flow.py`

`/resume` reads the cookie, clears it, executes the action, and 303s to the result URL. The magic-link `verify_page` must check for the cookie AFTER issuing the session and redirect to `/resume` instead of wherever it would normally go.

- [ ] **Step 1: Write failing end-to-end tests**

Create `tests/test_resume_flow.py`:

```python
"""Logged-out save-to-account: magic link → /resume → action complete."""

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.models import Document
from markland.service.pending_intent import (
    PENDING_INTENT_COOKIE_NAME,
    issue_pending_intent,
)
from markland.service.magic_link import issue_magic_link_token
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://test")
    return app, conn


def _seed_public(conn, *, owner_id="alice") -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, "T", "b", share, is_public=True, owner_id=owner_id)
    return Document(
        id=doc_id, title="T", content="b", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=True, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_verify_page_with_pending_intent_redirects_to_resume(tmp_path):
    app, conn = _build(tmp_path)
    doc = _seed_public(conn, owner_id=upsert_user_by_email(conn, "alice@x.com").id)

    intent = issue_pending_intent(
        secret=SECRET, action="fork", share_token=doc.share_token
    )
    magic = issue_magic_link_token("bob@example.com", secret=SECRET)

    client = TestClient(app)
    r = client.get(
        f"/verify?token={magic}",
        cookies={PENDING_INTENT_COOKIE_NAME: intent},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"] == "/resume"
    assert "mk_session" in r.cookies


def test_resume_fork_creates_doc_and_clears_cookie(tmp_path):
    from markland.service.sessions import issue_session

    app, conn = _build(tmp_path)
    alice = upsert_user_by_email(conn, "alice@x.com").id
    bob = upsert_user_by_email(conn, "bob@x.com").id
    doc = _seed_public(conn, owner_id=alice)

    intent = issue_pending_intent(
        secret=SECRET, action="fork", share_token=doc.share_token
    )
    session = issue_session(bob, secret=SECRET)
    client = TestClient(app)

    r = client.get(
        "/resume",
        cookies={"mk_session": session, PENDING_INTENT_COOKIE_NAME: intent},
        follow_redirects=False,
    )

    assert r.status_code == 303
    assert r.headers["location"].startswith("/d/")
    # Cookie cleared by Set-Cookie with Max-Age=0 or expires in the past.
    set_cookies = r.headers.get("set-cookie", "")
    assert PENDING_INTENT_COOKIE_NAME in set_cookies

    new_token = r.headers["location"].rsplit("/", 1)[-1]
    forked = conn.execute(
        "SELECT owner_id, forked_from_doc_id FROM documents WHERE share_token = ?",
        (new_token,),
    ).fetchone()
    assert forked[0] == bob
    assert forked[1] == doc.id


def test_resume_bookmark_inserts_and_clears_cookie(tmp_path):
    from markland.service.sessions import issue_session

    app, conn = _build(tmp_path)
    bob = upsert_user_by_email(conn, "bob@x.com").id
    doc = _seed_public(conn, owner_id=upsert_user_by_email(conn, "alice@x.com").id)

    intent = issue_pending_intent(
        secret=SECRET, action="bookmark", share_token=doc.share_token
    )
    session = issue_session(bob, secret=SECRET)
    client = TestClient(app)

    r = client.get(
        "/resume",
        cookies={"mk_session": session, PENDING_INTENT_COOKIE_NAME: intent},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == f"/d/{doc.share_token}"
    rows = conn.execute(
        "SELECT user_id FROM bookmarks WHERE user_id = ? AND doc_id = ?", (bob, doc.id)
    ).fetchall()
    assert len(rows) == 1


def test_resume_without_cookie_redirects_to_dashboard(tmp_path):
    from markland.service.sessions import issue_session

    app, conn = _build(tmp_path)
    bob = upsert_user_by_email(conn, "bob@x.com").id
    session = issue_session(bob, secret=SECRET)
    client = TestClient(app)

    r = client.get(
        "/resume",
        cookies={"mk_session": session},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_resume_requires_login(tmp_path):
    app, conn = _build(tmp_path)
    client = TestClient(app)

    r = client.get("/resume", follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/login" in r.headers["location"]
```

- [ ] **Step 2: Run — expected FAIL**

Run: `uv run pytest tests/test_resume_flow.py -v`
Expected: all FAIL — `/resume` not implemented; `/verify` does not yet consult the pending-intent cookie.

- [ ] **Step 3: Implement `/resume` in `save_routes.py`**

Append inside `build_router(...)` in `src/markland/web/save_routes.py`, before the `return r`:

```python
    @r.get("/resume")
    def resume(request: Request):
        user_id = _current_user_id(request)
        if user_id is None:
            return RedirectResponse(
                url=f"/login?next={quote('/resume', safe='')}",
                status_code=303,
            )

        from markland.service.pending_intent import (
            InvalidPendingIntent,
            read_pending_intent,
        )

        cookie = request.cookies.get(PENDING_INTENT_COOKIE_NAME, "")
        if not cookie:
            return RedirectResponse("/dashboard", status_code=303)

        try:
            intent = read_pending_intent(cookie, secret=session_secret)
        except InvalidPendingIntent:
            resp = RedirectResponse("/dashboard", status_code=303)
            resp.delete_cookie(PENDING_INTENT_COOKIE_NAME, path="/")
            return resp

        doc = get_document_by_token(conn, intent.share_token)
        if doc is None:
            resp = RedirectResponse("/dashboard", status_code=303)
            resp.delete_cookie(PENDING_INTENT_COOKIE_NAME, path="/")
            return resp

        target: str
        if intent.action == "fork":
            try:
                new_doc = fork_document(conn, source=doc, new_owner_id=user_id)
                target = f"/d/{new_doc.share_token}"
            except ValueError:
                # User is the owner — nothing to fork. Send them to the doc.
                target = f"/d/{doc.share_token}"
            except PermissionError:
                target = "/dashboard"
        else:  # bookmark
            from markland.service.save import _user_can_view

            if _user_can_view(conn, doc=doc, user_id=user_id):
                toggle_bookmark(
                    conn, user_id=user_id, doc_id=doc.id, bookmarked=True
                )
            target = f"/d/{doc.share_token}"

        resp = RedirectResponse(target, status_code=303)
        resp.delete_cookie(PENDING_INTENT_COOKIE_NAME, path="/")
        return resp
```

- [ ] **Step 4: Hook `verify_page` to check the pending-intent cookie**

Edit `src/markland/web/auth_routes.py:124-154`. After `target = safe_return_to(return_to)` and BEFORE the `if target == "/"` branch, add:

```python
        pending = request.cookies.get("markland_pending_intent", "")
        if pending:
            target = "/resume"
```

Replace the existing response assembly (`resp = HTMLResponse(...)` / `resp = RedirectResponse(...)`) to always take the redirect branch when `target != "/"`:

```python
        if target == "/":
            resp = HTMLResponse(verify_sent_tpl.render())
        else:
            resp = RedirectResponse(target, status_code=303)
```

(The existing code already does this; confirm no change is needed there — only the `pending` check above is new.)

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_resume_flow.py -v`
Expected: all five tests PASS.

Then: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/save_routes.py src/markland/web/auth_routes.py tests/test_resume_flow.py
git commit -m "feat(web): /resume and magic-link hook for post-login action resume"
```

---

## Task 8: `_save_dialog.html` partial — CTA UI

**Files:**
- Create: `src/markland/web/templates/_save_dialog.html`
- Modify: `src/markland/web/templates/document.html:217-219` (owner branch)

The partial owns: the desktop inline button + popover, and the mobile sticky bar + bottom sheet. Progressive-enhanced — the options are real `<form>` posts; JS only handles show/hide.

- [ ] **Step 1: Create `_save_dialog.html`**

Create `src/markland/web/templates/_save_dialog.html`:

```html
{# Included from document.html when the viewer is NOT the owner.
   Renders:
   - Desktop (≥641px): a small button in the .meta row with an anchored popover.
   - Mobile (≤640px): a sticky bottom bar that opens a full-width bottom sheet.
   Both options are real <form method="post"> elements — JS only toggles visibility. #}

<style>
  .save-root { position: relative; }
  .save-btn-desktop {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 0.82rem;
    color: var(--text);
    background: var(--surface-2);
    border: 1px solid var(--outline);
    border-radius: 999px;
    padding: 0.35rem 0.85rem;
    cursor: pointer;
  }
  .save-btn-desktop:hover { border-color: var(--outline-strong); }
  .save-popover {
    position: absolute;
    right: 0;
    top: calc(100% + 0.5rem);
    min-width: 200px;
    background: var(--surface-2);
    border: 1px solid var(--outline);
    border-radius: 14px;
    padding: 0.3rem;
    z-index: 10;
    display: none;
    box-shadow: 0 8px 24px rgba(0,0,0,0.35);
  }
  .save-popover[data-open="true"] { display: block; }
  .save-popover form { display: block; }
  .save-popover button {
    display: block;
    width: 100%;
    text-align: left;
    background: transparent;
    border: none;
    color: var(--text);
    font-family: var(--font-display);
    font-size: 0.9rem;
    padding: 0.55rem 0.75rem;
    border-radius: 10px;
    cursor: pointer;
  }
  .save-popover button:hover { background: rgba(255,255,255,0.06); }

  /* Mobile sticky bar + sheet. Hidden on desktop. */
  .save-mobile-bar { display: none; }
  .save-sheet-backdrop { display: none; }
  .save-sheet { display: none; }

  @media (max-width: 640px) {
    .save-btn-desktop { display: none; }

    .save-mobile-bar {
      display: block;
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      padding: 0.8rem 1rem max(0.8rem, env(safe-area-inset-bottom)) 1rem;
      background: var(--surface);
      border-top: 1px solid var(--outline);
      z-index: 20;
    }
    .save-mobile-bar button {
      width: 100%;
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1rem;
      color: var(--text);
      background: var(--blue);
      border: none;
      border-radius: 12px;
      padding: 0.85rem 1rem;
      cursor: pointer;
    }

    .save-sheet-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,0.55);
      z-index: 30;
      display: none;
    }
    .save-sheet-backdrop[data-open="true"] { display: block; }

    .save-sheet {
      display: block;
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      background: var(--surface-2);
      border-top: 1px solid var(--outline);
      border-radius: 18px 18px 0 0;
      padding: 1.2rem 1rem max(1.2rem, env(safe-area-inset-bottom)) 1rem;
      z-index: 40;
      transform: translateY(100%);
      transition: transform 0.22s ease;
    }
    .save-sheet[data-open="true"] { transform: translateY(0); }
    .save-sheet form { display: block; margin: 0.4rem 0; }
    .save-sheet button {
      width: 100%;
      text-align: left;
      font-family: var(--font-display);
      font-size: 1rem;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--outline);
      border-radius: 12px;
      padding: 0.85rem 1rem;
      cursor: pointer;
    }
    .save-sheet .save-cancel {
      width: 100%;
      margin-top: 0.6rem;
      background: transparent;
      color: var(--muted);
      border: none;
      font-family: var(--font-display);
      font-size: 0.95rem;
      padding: 0.6rem;
      cursor: pointer;
    }
  }
</style>

<div class="save-root">
  <button type="button" class="save-btn-desktop" data-save-open>
    Save to Markland ▾
  </button>

  <div class="save-popover" data-save-popover role="menu" aria-hidden="true">
    <form method="post" action="/d/{{ share_token }}/fork">
      <button type="submit" role="menuitem">Save a copy</button>
    </form>
    <form method="post" action="/d/{{ share_token }}/bookmark">
      <button type="submit" role="menuitem">Add to library</button>
    </form>
  </div>

  <div class="save-mobile-bar">
    <button type="button" data-save-open>Save to Markland</button>
  </div>

  <div class="save-sheet-backdrop" data-save-backdrop></div>
  <div class="save-sheet" data-save-sheet role="dialog" aria-label="Save this document">
    <form method="post" action="/d/{{ share_token }}/fork">
      <button type="submit">Save a copy</button>
    </form>
    <form method="post" action="/d/{{ share_token }}/bookmark">
      <button type="submit">Add to library</button>
    </form>
    <button type="button" class="save-cancel" data-save-close>Cancel</button>
  </div>
</div>

<script>
(function () {
  const root = document.currentScript.previousElementSibling;  // .save-root
  if (!root) return;
  const popover = root.querySelector('[data-save-popover]');
  const sheet = root.querySelector('[data-save-sheet]');
  const backdrop = root.querySelector('[data-save-backdrop]');
  const openBtns = root.querySelectorAll('[data-save-open]');
  const closeBtns = root.querySelectorAll('[data-save-close]');

  function setOpen(open) {
    if (popover) {
      popover.dataset.open = open ? 'true' : 'false';
      popover.setAttribute('aria-hidden', open ? 'false' : 'true');
    }
    if (sheet) sheet.dataset.open = open ? 'true' : 'false';
    if (backdrop) backdrop.dataset.open = open ? 'true' : 'false';
  }

  openBtns.forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    setOpen(true);
  }));
  closeBtns.forEach(b => b.addEventListener('click', () => setOpen(false)));
  if (backdrop) backdrop.addEventListener('click', () => setOpen(false));
  document.addEventListener('click', (e) => {
    if (!root.contains(e.target)) setOpen(false);
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') setOpen(false);
  });
})();
</script>
```

- [ ] **Step 2: Include the partial in `document.html`**

Edit `src/markland/web/templates/document.html:217-219`. Replace:

```jinja
{% if is_owner %}
  {% include "_share_dialog.html" %}
{% endif %}
```

With:

```jinja
{% if is_owner %}
  {% include "_share_dialog.html" %}
{% else %}
  {% include "_save_dialog.html" %}
{% endif %}
```

Pass `share_token` into the render context — confirm that `view_document` already passes it, and if not (check `app.py:362-370`), add it to the render call:

```python
html = document_tpl.render(
    title=doc.title,
    content_html=content_html,
    created_at=doc.created_at,
    is_owner=is_owner,
    grants=grants_for_template,
    doc_id=doc.id,
    share_token=doc.share_token,
    active_principals=active_principals,
)
```

- [ ] **Step 3: Smoke-check with the existing view test**

Existing document render tests (grep for `client.get.*"/d/"`) should still pass. If any test asserts exact HTML length, update it.

Run: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/markland/web/templates/_save_dialog.html src/markland/web/templates/document.html src/markland/web/app.py
git commit -m "feat(ui): save-to-Markland CTA partial with desktop popover + mobile sheet"
```

---

## Task 9: Fork attribution on the fork's view

**Files:**
- Modify: `src/markland/web/app.py` (`view_document`)
- Modify: `src/markland/web/templates/document.html:54-84` (`.meta` row)
- Test: `tests/test_document_view_forked_from.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_document_view_forked_from.py`:

```python
"""view_document must render 'Forked from X' when forked_from_doc_id is set."""

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.models import Document
from markland.web.app import create_app


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret="s", base_url="http://t")
    return app, conn


def _insert_doc(conn, **kw) -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(
        conn, doc_id, kw.get("title", "T"), kw.get("content", "c"), share,
        is_public=kw.get("is_public", True), owner_id=kw.get("owner_id"),
        forked_from_doc_id=kw.get("forked_from_doc_id"),
    )
    doc = Document(
        id=doc_id, title=kw.get("title", "T"), content=kw.get("content", "c"),
        share_token=share, created_at=Document.now(), updated_at=Document.now(),
        is_public=kw.get("is_public", True), is_featured=False,
        owner_id=kw.get("owner_id"), version=1,
        forked_from_doc_id=kw.get("forked_from_doc_id"),
    )
    return doc


def test_fork_with_public_parent_renders_link(tmp_path):
    app, conn = _build(tmp_path)
    parent = _insert_doc(conn, title="Parent Title", owner_id="alice", is_public=True)
    fork = _insert_doc(
        conn, title="Parent Title", owner_id="bob", is_public=True,
        forked_from_doc_id=parent.id,
    )
    client = TestClient(app)

    r = client.get(f"/d/{fork.share_token}")
    assert r.status_code == 200
    body = r.text
    assert "Forked from" in body
    assert f'/d/{parent.share_token}' in body
    assert "Parent Title" in body


def test_fork_with_private_parent_renders_title_without_link(tmp_path):
    app, conn = _build(tmp_path)
    parent = _insert_doc(conn, title="Private Parent", owner_id="alice", is_public=False)
    fork = _insert_doc(
        conn, title="Private Parent", owner_id="bob", is_public=True,
        forked_from_doc_id=parent.id,
    )
    client = TestClient(app)

    r = client.get(f"/d/{fork.share_token}")
    body = r.text
    assert "Forked from" in body
    # Anonymous viewer cannot access the private parent — no link.
    assert f'/d/{parent.share_token}' not in body
    assert "Private Parent" in body


def test_non_fork_has_no_forked_from_line(tmp_path):
    app, conn = _build(tmp_path)
    doc = _insert_doc(conn, owner_id="alice")
    client = TestClient(app)

    r = client.get(f"/d/{doc.share_token}")
    assert "Forked from" not in r.text
```

- [ ] **Step 2: Run — expected FAIL**

Run: `uv run pytest tests/test_document_view_forked_from.py -v`
Expected: FAIL — "Forked from" never appears.

- [ ] **Step 3: Resolve `forked_from` in `view_document`**

Edit `src/markland/web/app.py` inside `view_document` (around line 322). After `doc = get_document_by_token(db_conn, share_token)` (and the None check), add:

```python
        forked_from = None
        forked_from_visible = False
        if doc.forked_from_doc_id:
            from markland.db import get_document

            parent = get_document(db_conn, doc.forked_from_doc_id)
            if parent is not None:
                forked_from = parent
                # Visible if public, or owned by viewer, or viewer has a grant.
                if parent.is_public:
                    forked_from_visible = True
                elif principal_user_id and parent.owner_id == principal_user_id:
                    forked_from_visible = True
                elif principal_user_id:
                    grant_row = db_conn.execute(
                        "SELECT 1 FROM grants WHERE doc_id = ? AND principal_id = ?",
                        (parent.id, principal_user_id),
                    ).fetchone()
                    forked_from_visible = grant_row is not None
```

Note: `principal_user_id` is already computed earlier in the function. Keep it.

Pass into the template render call:

```python
        html = document_tpl.render(
            title=doc.title,
            content_html=content_html,
            created_at=doc.created_at,
            is_owner=is_owner,
            grants=grants_for_template,
            doc_id=doc.id,
            share_token=doc.share_token,
            active_principals=active_principals,
            forked_from=forked_from,
            forked_from_visible=forked_from_visible,
        )
```

- [ ] **Step 4: Render the attribution in `document.html`**

Edit `src/markland/web/templates/document.html`. Inside the `.meta` div (after the existing `<span>Published …</span>`, around line 215):

```jinja
            <span>Published {{ created_at[:10] }}</span>
            {% if forked_from %}
            <span class="forked-from" style="font-family: var(--font-display); font-size: 0.78rem; color: var(--muted);">
              Forked from
              {% if forked_from_visible %}
                <a href="/d/{{ forked_from.share_token }}" style="color: var(--text); text-decoration: underline; text-underline-offset: 2px;">{{ forked_from.title }}</a>
              {% else %}
                {{ forked_from.title }}
              {% endif %}
            </span>
            {% endif %}
```

- [ ] **Step 5: Run**

Run: `uv run pytest tests/test_document_view_forked_from.py -v`
Expected: all three PASS.

Then: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/app.py src/markland/web/templates/document.html tests/test_document_view_forked_from.py
git commit -m "feat(viewer): render 'Forked from' attribution on forks"
```

---

## Task 10: Dashboard "Saved" section

**Files:**
- Modify: `src/markland/web/dashboard.py`
- Modify: `src/markland/web/templates/dashboard.html`
- Test: `tests/test_dashboard_bookmarks.py`

- [ ] **Step 1: Look at the current dashboard template to follow its card style**

Read `src/markland/web/templates/dashboard.html` to see how `owned` and `shared` are currently rendered. Mirror that structure for `bookmarks`.

- [ ] **Step 2: Write failing tests**

Create `tests/test_dashboard_bookmarks.py`:

```python
"""Dashboard '/dashboard' surfaces a 'Saved' section for bookmarks."""

from fastapi.testclient import TestClient

from markland.db import init_db, insert_document, upsert_bookmark
from markland.models import Document
from markland.service.sessions import issue_session
from markland.service.users import upsert_user_by_email
from markland.web.app import create_app

SECRET = "test-secret"


def _build(tmp_path):
    conn = init_db(tmp_path / "m.db")
    app = create_app(db_conn=conn, session_secret=SECRET, base_url="http://t")
    return app, conn


def _seed(conn, *, owner_id, is_public=True, title="T") -> Document:
    doc_id = Document.generate_id()
    share = Document.generate_share_token()
    insert_document(conn, doc_id, title, "c", share, is_public=is_public, owner_id=owner_id)
    return Document(
        id=doc_id, title=title, content="c", share_token=share,
        created_at=Document.now(), updated_at=Document.now(),
        is_public=is_public, is_featured=False, owner_id=owner_id,
        version=1, forked_from_doc_id=None,
    )


def test_dashboard_shows_saved_section_with_public_bookmarks(tmp_path):
    app, conn = _build(tmp_path)
    alice = upsert_user_by_email(conn, "alice@x.com").id
    bob = upsert_user_by_email(conn, "bob@x.com").id
    d1 = _seed(conn, owner_id=alice, title="Doc One")
    d2 = _seed(conn, owner_id=alice, title="Doc Two")
    upsert_bookmark(conn, user_id=bob, doc_id=d1.id)
    upsert_bookmark(conn, user_id=bob, doc_id=d2.id)

    client = TestClient(app)
    r = client.get("/dashboard", cookies={"mk_session": issue_session(bob, secret=SECRET)})
    assert r.status_code == 200
    assert "Saved" in r.text
    assert "Doc One" in r.text
    assert "Doc Two" in r.text


def test_dashboard_filters_out_bookmarks_that_became_private(tmp_path):
    app, conn = _build(tmp_path)
    alice = upsert_user_by_email(conn, "alice@x.com").id
    bob = upsert_user_by_email(conn, "bob@x.com").id
    public_doc = _seed(conn, owner_id=alice, is_public=True, title="Still Public")
    private_doc = _seed(conn, owner_id=alice, is_public=False, title="Gone Private")
    upsert_bookmark(conn, user_id=bob, doc_id=public_doc.id)
    upsert_bookmark(conn, user_id=bob, doc_id=private_doc.id)

    client = TestClient(app)
    r = client.get("/dashboard", cookies={"mk_session": issue_session(bob, secret=SECRET)})
    assert "Still Public" in r.text
    assert "Gone Private" not in r.text


def test_dashboard_has_no_saved_section_when_no_bookmarks(tmp_path):
    app, conn = _build(tmp_path)
    bob = upsert_user_by_email(conn, "bob@x.com").id

    client = TestClient(app)
    r = client.get("/dashboard", cookies={"mk_session": issue_session(bob, secret=SECRET)})
    # The literal "Saved" header must not be present when there are no bookmarks.
    assert ">Saved<" not in r.text
```

- [ ] **Step 3: Run — expected FAIL**

Run: `uv run pytest tests/test_dashboard_bookmarks.py -v`
Expected: FAIL — dashboard doesn't mention "Saved".

- [ ] **Step 4: Extend the dashboard handler**

Edit `src/markland/web/dashboard.py`. Replace the import block and handler body:

```python
from markland.db import (
    list_bookmarks_for_user,
    list_documents_for_owner,
    list_shared_with_principal,
)
```

Inside `dashboard()`, after the existing `shared_docs = ...` assignment, add:

```python
        bookmarked_docs = list_bookmarks_for_user(conn, user_id=principal.principal_id)
        bookmarks = [
            {
                "title": d.title,
                "share_token": d.share_token,
                "updated_at": d.updated_at,
                "owner_display": _owner_display(d.owner_id),
            }
            for d in bookmarked_docs
        ]
```

Pass `bookmarks` into the template render:

```python
        return HTMLResponse(tpl.render(owned=owned, shared=shared, bookmarks=bookmarks))
```

- [ ] **Step 5: Render the "Saved" section in `dashboard.html`**

Edit `src/markland/web/templates/dashboard.html`. Find the existing "Shared with me" section and add a peer section below it (style to match):

```jinja
{% if bookmarks %}
<section>
  <h2>Saved</h2>
  <ul>
    {% for b in bookmarks %}
    <li>
      <a href="/d/{{ b.share_token }}">{{ b.title }}</a>
      <span> — by {{ b.owner_display }}</span>
      <form method="post" action="/d/{{ b.share_token }}/bookmark?_method=DELETE" style="display:inline;">
        <input type="hidden" name="_method" value="DELETE" />
        <button type="submit">Remove</button>
      </form>
    </li>
    {% endfor %}
  </ul>
</section>
{% endif %}
```

Because browsers submit `POST` for `<form method="post">`, we use a small JS-free fetch alternative: use a plain `<button>` with `formmethod="delete"` is not supported reliably, so we add a minimal inline script that intercepts the click and calls `fetch(..., {method:"DELETE"})`, then reloads. Replace the `<form>` above with:

```jinja
{% if bookmarks %}
<section>
  <h2>Saved</h2>
  <ul>
    {% for b in bookmarks %}
    <li>
      <a href="/d/{{ b.share_token }}">{{ b.title }}</a>
      <span> — by {{ b.owner_display }}</span>
      <button type="button" data-remove-bookmark="/d/{{ b.share_token }}/bookmark">Remove</button>
    </li>
    {% endfor %}
  </ul>
</section>
<script>
(function () {
  document.querySelectorAll('[data-remove-bookmark]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      fetch(btn.getAttribute('data-remove-bookmark'), {method: 'DELETE'})
        .then(function () { window.location.reload(); });
    });
  });
})();
</script>
{% endif %}
```

Match the surrounding styling — if `dashboard.html` uses bespoke CSS classes for owned/shared sections, apply the same classes to the new `<section>` and `<li>` elements.

- [ ] **Step 6: Run**

Run: `uv run pytest tests/test_dashboard_bookmarks.py -v`
Expected: all three PASS.

Then: `uv run pytest tests/ -v`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/dashboard.py src/markland/web/templates/dashboard.html tests/test_dashboard_bookmarks.py
git commit -m "feat(dashboard): 'Saved' section surfaces bookmarked docs"
```

---

## Task 11: End-to-end mobile verification (Playwright)

**Files:**
- None (manual verification).

- [ ] **Step 1: Start the local web server**

```bash
uv run python -m markland.run_web
```

(Runs in background on port 8950 by default. Verify it's up with `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8950/`.)

- [ ] **Step 2: Seed the stress-test doc**

Run this Python snippet (save to `/tmp/seed.py` or inline via `uv run python -c`):

```python
from markland.config import get_config
from markland.db import init_db, insert_document
from markland.models import Document

cfg = get_config()
conn = init_db(cfg.db_path)
content = """# Mobile smoke test

A short paragraph with a **bold** bit, some *italic*, and a [very-long-link-label-that-should-wrap-or-scroll](https://markland.dev/some/very/long/path/that/keeps/going/longlonglonglonglong).

## Code

```python
def hello(name: str) -> str:
    return f"This is a long line of code that will probably overflow a narrow viewport so we can see how the pre block behaves on a phone: {name}"
```

## Table

| Column A | Column B with a long heading | Column C | Column D | Column E long heading too |
|---|---|---|---|---|
| data one | data two somewhat long | data three | data four | data five |
| another row | yet more data in this cell | cell content | foo | bar |
| third row | qux | quux | corge | grault |

## A long inline code span

Run `this_is_a_very_long_command_name_without_breaks --flag=value --another=thing` in your terminal.

## Quote

> A pull quote that spans a line or two to verify blockquote rendering on mobile.
"""

doc_id = Document.generate_id()
share_token = Document.generate_share_token()
insert_document(conn, doc_id=doc_id, title="Mobile smoke test", content=content, share_token=share_token, is_public=True, owner_id=None)
print("SHARE_TOKEN=" + share_token)
```

- [ ] **Step 3: Drive Playwright through the MCP tools**

(This step is run by the agentic worker using Playwright MCP tools in conversation.)

1. `mcp__plugin_playwright_playwright__browser_resize(width=375, height=667)`
2. `mcp__plugin_playwright_playwright__browser_navigate(url="http://127.0.0.1:8950/d/{SHARE_TOKEN}")`
3. `mcp__plugin_playwright_playwright__browser_evaluate(function="() => ({ vw: window.innerWidth, sw: document.documentElement.scrollWidth, wrapperOk: !!document.querySelector('.table-scroll') && document.querySelector('.table-scroll').scrollWidth > document.querySelector('.table-scroll').clientWidth })")`

Expected result: `{ vw: 375, sw: <= 375, wrapperOk: true }`.

4. `mcp__plugin_playwright_playwright__browser_take_screenshot(filename="mobile-post-fix.png", fullPage=true, type="png")` — attach to the PR for review.

- [ ] **Step 4: Verify CTA is present on the mobile viewport**

Same session, evaluate:

```javascript
() => ({
  hasMobileBar: !!document.querySelector('.save-mobile-bar button'),
  desktopButtonHiddenOnMobile: window.getComputedStyle(document.querySelector('.save-btn-desktop')).display === 'none'
})
```

Expected: `{ hasMobileBar: true, desktopButtonHiddenOnMobile: true }`.

- [ ] **Step 5: Verify at desktop width too**

1. `browser_resize(width=1280, height=800)`
2. Evaluate:

```javascript
() => ({
  hasDesktopBtn: !!document.querySelector('.save-btn-desktop'),
  mobileBarHiddenOnDesktop: window.getComputedStyle(document.querySelector('.save-mobile-bar')).display === 'none'
})
```

Expected: `{ hasDesktopBtn: true, mobileBarHiddenOnDesktop: true }`.

- [ ] **Step 6: Stop the server**

If started via `run_in_background`, it'll be auto-cleaned; otherwise `kill`.

- [ ] **Step 7: Commit the screenshot (optional)**

If the PR workflow accepts a screenshot attachment, upload `mobile-post-fix.png` on the PR. No new code to commit.

---

## Self-review before handoff

(Plan author runs this inline; no subagent.)

1. **Spec coverage:**
   - Mobile CSS fixes → Task 1 ✓
   - `forked_from_doc_id` + `bookmarks` migration → Task 2 ✓
   - Fork service → Task 4 ✓
   - Bookmark helpers → Task 3 ✓
   - Pending-intent cookie → Task 5 ✓
   - `/fork`, `/bookmark` routes → Task 6 ✓
   - `/resume` + verify hook → Task 7 ✓
   - Save-dialog UI → Task 8 ✓
   - Fork attribution → Task 9 ✓
   - Dashboard "Saved" → Task 10 ✓
   - Mobile Playwright verification → Task 11 ✓

2. **Placeholder scan:** No "TBD"/"TODO"/"similar to Task N"/"add validation". Each code block is complete.

3. **Type consistency:** `toggle_bookmark(conn, *, user_id, doc_id, bookmarked)` signature is consistent between Task 4 (service) and all call sites (Tasks 6, 7). `fork_document(conn, *, source, new_owner_id)` is consistent between Task 4 and Tasks 6, 7. `PendingIntent(action, share_token)` dataclass used consistently in Tasks 5, 7.

---

## Execution options

1. **Subagent-Driven (recommended)** — one fresh subagent per task, review gate between tasks.
2. **Inline Execution** — execute in this session with `executing-plans`; review at the end of each task.
