"""Permission-aware doc CRUD. All MCP and HTTP handlers call through here."""

from __future__ import annotations

import sqlite3

from markland import db
from markland.models import Document
from markland.service import audit
from markland.service import metrics
from markland.service.auth import Principal
from markland.service.permissions import (
    NotFound,
    PermissionDenied,
    check_permission,
)


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
        "version": doc.version,
    }


def _resolve_owner_id(principal: Principal) -> str | None:
    """Return the user_id the doc should be owned by.

    For user tokens, this is principal.principal_id.
    For agent tokens (Plan 4), this is the agent's owning user_id; service-owned
    agents have no human owner so docs they publish have owner_id=None and
    only the agent itself can access them until a grant is created.
    """
    if principal.principal_type == "user":
        return principal.principal_id
    return principal.user_id


def publish(
    conn: sqlite3.Connection,
    base_url: str,
    principal: Principal,
    content: str,
    title: str | None = None,
    public: bool = False,
) -> dict:
    if principal.principal_type == "agent" and principal.user_id is None:
        # Service-owned agents have no natural owning user; no hosted product
        # surface for service agents exists at launch.
        raise PermissionError("invalid_argument: service_agent_cannot_publish")
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
    result = {
        "id": doc_id,
        "title": resolved_title,
        "share_url": f"{base_url}/d/{share_token}",
        "is_public": public,
        "owner_id": owner_id,
    }
    audit.record(
        conn,
        action="publish",
        principal=principal,
        doc_id=doc_id,
        metadata={"title": resolved_title, "is_public": bool(public)},
    )
    metrics.emit_first_time("first_publish", principal_id=principal.principal_id)
    return result


def list_for_principal(
    conn: sqlite3.Connection, principal: Principal
) -> list[dict]:
    docs = db.list_documents_for_principal(conn, principal.principal_id)
    return [_doc_to_summary(d) for d in docs]


def list_for_principal_paginated(
    conn: sqlite3.Connection,
    principal: Principal,
    *,
    limit: int = 50,
    cursor: str | None = None,
    cap: int = 200,
) -> tuple[list[dict], str | None]:
    """Paginated list of docs the principal can view.

    Returns (rows, next_cursor) where rows are doc dicts (full doc fields,
    not yet projected to envelope shape). Uses (updated_at, id) DESC keyset
    pagination for stable ordering across rows with equal timestamps.
    """
    from markland._mcp_envelopes import decode_cursor, encode_cursor

    limit = min(max(1, int(limit)), cap)

    where_clauses = [
        "(d.owner_id = ? OR d.id IN "
        "(SELECT doc_id FROM grants WHERE principal_id = ?))"
    ]
    params: list = [principal.principal_id, principal.principal_id]

    if cursor:
        last_id, last_updated_at = decode_cursor(cursor)
        where_clauses.append("(d.updated_at, d.id) < (?, ?)")
        params.extend([last_updated_at, last_id])

    d_prefixed = ", ".join("d." + c for c in db._DOC_COLUMNS.split(", "))
    sql = (
        f"SELECT {d_prefixed} FROM documents d "
        f"WHERE {' AND '.join(where_clauses)} "
        "ORDER BY d.updated_at DESC, d.id DESC "
        "LIMIT ?"
    )
    params.append(limit + 1)  # over-fetch by one to detect more pages

    rows = conn.execute(sql, params).fetchall()
    docs = [db._row_to_doc(row) for row in rows]

    has_more = len(docs) > limit
    page = docs[:limit]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            last_id=last.id, last_updated_at=last.updated_at
        )

    # Project to dict form (full doc fields) so the caller can apply
    # doc_summary / doc_envelope as needed.
    page_dicts = [
        {
            "id": d.id,
            "title": d.title,
            "content": d.content,
            "share_token": d.share_token,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "is_public": d.is_public,
            "is_featured": d.is_featured,
            "owner_id": d.owner_id,
            "version": d.version,
            "forked_from_doc_id": d.forked_from_doc_id,
        }
        for d in page
    ]
    return page_dicts, next_cursor


def list_shared_with(
    conn: sqlite3.Connection, principal: Principal
) -> list[dict]:
    docs = db.list_shared_with_principal(conn, principal.principal_id)
    return [_doc_to_summary(d) for d in docs]


def get(
    conn: sqlite3.Connection,
    principal_or_doc_id,
    doc_id_or_principal=None,
    base_url: str = "",
):
    """Return a Document or a dict depending on call form.

    Two call forms are supported to span the Plan 3 dict API and the
    Plan 8 Document-returning API:

    1. Legacy: `get(conn, principal, doc_id, base_url="")` returns a dict
       (used by MCP `markland_get` and HTTP handlers that want share_url).
    2. Plan 8: `get(conn, doc_id, principal)` returns a `Document` object
       including `version` (used by versioning tests and the HTTP
       `/api/docs/{id}` handler).

    Both run through `check_permission(..., "view")`.
    """
    # Disambiguate by type.
    if isinstance(principal_or_doc_id, Principal):
        principal = principal_or_doc_id
        doc_id = doc_id_or_principal
        check_permission(conn, principal, doc_id, "view")
        doc = db.get_document(conn, doc_id)
        assert doc is not None
        return _doc_to_full(doc, base_url)
    # Plan 8 form.
    doc_id = principal_or_doc_id
    principal = doc_id_or_principal
    check_permission(conn, principal, doc_id, "view")
    return db.get_document(conn, doc_id)


def search(
    conn: sqlite3.Connection, principal: Principal, query: str
) -> list[dict]:
    docs = db.search_documents_for_principal(conn, principal.principal_id, query)
    return [_doc_to_summary(d) for d in docs]


def search_paginated(
    conn: sqlite3.Connection,
    principal: Principal,
    query: str,
    *,
    limit: int = 50,
    cursor: str | None = None,
    cap: int = 200,
) -> tuple[list[dict], str | None]:
    """Paginated search of docs the principal can view.

    Returns (rows, next_cursor) using (updated_at, id) DESC keyset
    pagination for stable ordering across rows with equal timestamps.
    """
    from markland._mcp_envelopes import decode_cursor, encode_cursor

    limit = min(max(1, int(limit)), cap)
    pattern = f"%{query}%"
    pid = principal.principal_id

    where_clauses = [
        "((d.owner_id = ? AND (d.title LIKE ? OR d.content LIKE ?)) "
        "OR d.id IN (SELECT g.doc_id FROM grants g WHERE g.principal_id = ?) "
        "AND (d.title LIKE ? OR d.content LIKE ?))"
    ]
    # NB: rewriting as a clearer UNION via subquery would change semantics; we
    # mirror search_documents_for_principal's union structure but in a single
    # query so keyset pagination works.
    sql_inner = (
        f"SELECT {db._DOC_COLUMNS} FROM documents "
        "WHERE owner_id = ? AND (title LIKE ? OR content LIKE ?) "
        "UNION "
        f"SELECT {', '.join('d.' + c for c in db._DOC_COLUMNS.split(', '))} "
        "FROM documents d JOIN grants g ON g.doc_id = d.id "
        "WHERE g.principal_id = ? AND (d.title LIKE ? OR d.content LIKE ?)"
    )
    inner_params: list = [pid, pattern, pattern, pid, pattern, pattern]

    outer_where: list[str] = []
    outer_params: list = []
    if cursor:
        last_id, last_updated_at = decode_cursor(cursor)
        outer_where.append("(updated_at, id) < (?, ?)")
        outer_params.extend([last_updated_at, last_id])

    where_sql = ("WHERE " + " AND ".join(outer_where)) if outer_where else ""
    sql = (
        f"SELECT * FROM ({sql_inner}) {where_sql} "
        "ORDER BY updated_at DESC, id DESC LIMIT ?"
    )
    params = inner_params + outer_params + [limit + 1]

    rows = conn.execute(sql, params).fetchall()
    docs = [db._row_to_doc(row) for row in rows]

    has_more = len(docs) > limit
    page = docs[:limit]

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            last_id=last.id, last_updated_at=last.updated_at
        )

    page_dicts = [
        {
            "id": d.id,
            "title": d.title,
            "content": d.content,
            "share_token": d.share_token,
            "created_at": d.created_at,
            "updated_at": d.updated_at,
            "is_public": d.is_public,
            "is_featured": d.is_featured,
            "owner_id": d.owner_id,
            "version": d.version,
            "forked_from_doc_id": d.forked_from_doc_id,
        }
        for d in page
    ]
    return page_dicts, next_cursor


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


MAX_REVISIONS_PER_DOC = 50


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

    `if_version` is REQUIRED and must equal the current stored version;
    otherwise `ConflictError` is raised with the current server state. On
    success, the pre-update state is snapshotted to `revisions`, the version
    is incremented, and `revisions` for this doc are pruned to
    `MAX_REVISIONS_PER_DOC`.

    Raises:
        ValueError: if the doc does not exist.
        PermissionDenied: if the principal lacks edit access.
        ConflictError: if `if_version` does not match the stored version.
    """
    # Permission check must happen BEFORE we start the BEGIN IMMEDIATE write
    # transaction so a read-only principal cannot acquire the write lock.
    check_permission(conn, principal, doc_id, "edit")

    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            f"SELECT {db._DOC_COLUMNS} FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            raise ValueError(f"Document {doc_id} not found")
        doc = db._row_to_doc(row)

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
        db.insert_revision(
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

        db.prune_revisions(conn, doc.id, keep=MAX_REVISIONS_PER_DOC)

        conn.execute("COMMIT")
    except Exception:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise

    refreshed = db.get_document(conn, doc.id)
    assert refreshed is not None
    audit.record(
        conn,
        action="update",
        principal=principal,
        doc_id=doc_id,
        metadata={"new_version": refreshed.version},
    )
    return refreshed


def delete(
    conn: sqlite3.Connection, principal: Principal, doc_id: str
) -> dict:
    check_permission(conn, principal, doc_id, "owner")
    deleted = db.delete_document(conn, doc_id)
    if deleted:
        audit.record(
            conn,
            action="delete",
            principal=principal,
            doc_id=doc_id,
            metadata={},
        )
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


def publish_doc(
    conn: sqlite3.Connection,
    *,
    base_url: str,
    principal: Principal,
    title: str | None = None,
    content: str = "",
    is_public: bool = False,
) -> dict:
    """Keyword-only facade over `publish(...)` for tests and new callers."""
    return publish(
        conn,
        base_url,
        principal,
        content,
        title=title,
        public=is_public,
    )


def get_doc(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
) -> Document:
    """Return the Document (Plan 8 form). Enforces view permission."""
    check_permission(conn, principal, doc_id, "view")
    doc = db.get_document(conn, doc_id)
    if doc is None:
        raise NotFound(f"document {doc_id}")
    return doc


def update_doc(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
    content: str | None = None,
    title: str | None = None,
    if_version: int,
) -> Document:
    """Canonical keyword-only update facade (spec: plan 10)."""
    return update(
        conn,
        doc_id,
        principal,
        content=content,
        title=title,
        if_version=if_version,
    )


def delete_doc(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
    doc_id: str,
) -> dict:
    return delete(conn, principal, doc_id)


def list_docs(
    conn: sqlite3.Connection,
    *,
    principal: Principal,
) -> list[dict]:
    return list_for_principal(conn, principal)


__all__ = [
    "publish",
    "publish_doc",
    "list_for_principal",
    "list_docs",
    "list_shared_with",
    "get",
    "get_doc",
    "search",
    "share_link",
    "update",
    "update_doc",
    "delete",
    "delete_doc",
    "set_visibility",
    "feature",
    # re-exports for callers
    "NotFound",
    "PermissionDenied",
]
