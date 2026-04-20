"""SQLite database operations for document + grant storage."""

import sqlite3
from datetime import datetime, timezone
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
            owner_id TEXT,
            version INTEGER NOT NULL DEFAULT 1,
            forked_from_doc_id TEXT REFERENCES documents(id) ON DELETE SET NULL
        )
    """)
    # Migration for older databases that don't yet have the new columns
    _add_column_if_missing(conn, "documents", "is_public", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "is_featured", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(conn, "documents", "owner_id", "TEXT")
    _add_column_if_missing(conn, "documents", "version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(conn, "documents", "forked_from_doc_id", "TEXT")
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_revisions_doc ON revisions(doc_id, id DESC)"
    )
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_share_token ON documents(share_token)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_public ON documents(is_public)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_featured ON documents(is_featured)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_owner ON documents(owner_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_grants_principal ON grants(principal_id, doc_id)"
    )
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL,
            label TEXT,
            principal_type TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_hash ON tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            email      TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source     TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            owner_type TEXT NOT NULL CHECK (owner_type IN ('user', 'service')),
            owner_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked_at TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_agents_owner ON agents(owner_type, owner_id)"
    )
    ensure_invites_schema(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS device_authorizations (
            device_code    TEXT PRIMARY KEY,
            user_code      TEXT NOT NULL UNIQUE,
            status         TEXT NOT NULL CHECK (status IN ('pending','authorized','expired','denied')),
            user_id        TEXT,
            invite_token   TEXT,
            created_at     TEXT NOT NULL,
            expires_at     TEXT NOT NULL,
            polled_last    TEXT,
            authorized_at  TEXT,
            consumed_at    TEXT
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_device_user_code "
        "ON device_authorizations (user_code)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS presence (
            doc_id         TEXT NOT NULL,
            principal_id   TEXT NOT NULL,
            principal_type TEXT NOT NULL CHECK (principal_type IN ('user', 'agent')),
            status         TEXT NOT NULL CHECK (status IN ('reading', 'editing')),
            note           TEXT,
            updated_at     TEXT NOT NULL,
            expires_at     TEXT NOT NULL,
            PRIMARY KEY (doc_id, principal_id),
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_presence_expires ON presence(expires_at)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT,
            action TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            principal_type TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_created_at ON audit_log (created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_doc_id ON audit_log (doc_id)"
    )
    conn.commit()
    return conn


def record_audit(
    conn: sqlite3.Connection,
    *,
    doc_id: str | None,
    action: str,
    principal_id: str,
    principal_type: str,
    metadata: dict | None = None,
) -> None:
    """Insert one audit row. Commits. Callers should treat raises as fatal — the
    audit *service* wrapper in service/audit.py is what swallows exceptions."""
    import json as _json

    conn.execute(
        """
        INSERT INTO audit_log (doc_id, action, principal_id, principal_type, metadata)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            doc_id,
            action,
            principal_id,
            principal_type,
            _json.dumps(metadata or {}, separators=(",", ":"), sort_keys=True),
        ),
    )
    conn.commit()


def ensure_invites_schema(conn: sqlite3.Connection) -> None:
    """Create the invites table + token_hash index if they don't exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS invites (
            id TEXT PRIMARY KEY,
            token_hash TEXT UNIQUE NOT NULL,
            doc_id TEXT NOT NULL,
            level TEXT NOT NULL CHECK (level IN ('view', 'edit')),
            single_use INTEGER NOT NULL DEFAULT 1,
            uses_remaining INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_invites_token_hash
            ON invites (token_hash);

        CREATE INDEX IF NOT EXISTS idx_invites_doc
            ON invites (doc_id);
        """
    )
    conn.commit()


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


_DOC_COLUMNS = (
    "id, title, content, share_token, created_at, updated_at, "
    "is_public, is_featured, owner_id, version, forked_from_doc_id"
)


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
        (doc_id, title, content, share_token, now, now, 1 if is_public else 0, owner_id, forked_from_doc_id),
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
    """Union of owned docs and docs directly granted to this principal_id."""
    d_prefixed = ", ".join("d." + c for c in _DOC_COLUMNS.split(", "))
    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT {_DOC_COLUMNS} FROM documents WHERE owner_id = ?
            UNION
            SELECT {d_prefixed}
            FROM documents d
            JOIN grants g ON g.doc_id = d.id
            WHERE g.principal_id = ?
        )
        ORDER BY updated_at DESC
        """,
        (principal_id, principal_id),
    ).fetchall()
    return [_row_to_doc(row) for row in rows]


def list_shared_with_principal(
    conn: sqlite3.Connection, principal_id: str
) -> list[Document]:
    """Docs where this principal has a grant but is NOT the owner."""
    d_prefixed = ", ".join("d." + c for c in _DOC_COLUMNS.split(", "))
    rows = conn.execute(
        f"""
        SELECT {d_prefixed}
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
    d_prefixed = ", ".join("d." + c for c in _DOC_COLUMNS.split(", "))
    rows = conn.execute(
        f"""
        SELECT * FROM (
            SELECT {_DOC_COLUMNS} FROM documents
            WHERE owner_id = ? AND (title LIKE ? OR content LIKE ?)
            UNION
            SELECT {d_prefixed}
            FROM documents d JOIN grants g ON g.doc_id = d.id
            WHERE g.principal_id = ? AND (d.title LIKE ? OR d.content LIKE ?)
        )
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


def add_waitlist_email(
    conn: sqlite3.Connection,
    email: str,
    source: str | None = None,
) -> bool:
    """
    Insert email into waitlist. Returns True if inserted, False if already present.
    Uses INSERT OR IGNORE so duplicate submits are idempotent.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT OR IGNORE INTO waitlist (email, created_at, source) VALUES (?, ?, ?)",
        (email, created_at, source),
    )
    conn.commit()
    return cur.rowcount > 0


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


# --- Bookmarks CRUD --------------------------------------------------------


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
    d_prefixed = ", ".join("d." + c for c in _DOC_COLUMNS.split(", "))
    rows = conn.execute(
        f"""
        SELECT {d_prefixed}
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


# --- Revisions (Plan 8) -------------------------------------------------


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
