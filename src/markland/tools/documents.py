"""Thin shims over `markland.service.docs` for legacy/test call sites.

New code should go through `markland.service.docs` directly with an
explicit `Principal`. These wrappers exist so Plan 8 tests (and the
existing `scripts/smoke_test.py`) have a principal-less publish/get/update
surface.
"""

from __future__ import annotations

import sqlite3

from markland import db as _db
from markland.models import Document
from markland.service import docs as _docs
from markland.service.auth import Principal
from markland.service.docs import _extract_title  # noqa: F401  (re-export)


def _default_principal(principal_id: str = "admin") -> Principal:
    """Best-effort admin-like principal for test/tool call sites that don't
    carry one. Matches the Plan 2 canonical shape."""
    return Principal(
        principal_id=principal_id,
        principal_type="user",
        display_name=None,
        is_admin=True,
        user_id=principal_id,
    )


def publish_doc(
    conn: sqlite3.Connection,
    base_url: str,
    title_or_principal,
    content: str | None = None,
    public: bool = False,
) -> dict:
    """Accepts either a (title, content) legacy pair or a Principal + content.

    Legacy 4-positional form used by Plan 8 tests and scripts/smoke_test.py:
        publish_doc(conn, base_url, title, content, public=...)
    Modern form (Principal first):
        publish_doc(conn, base_url, principal, content=..., public=...)
    """
    # Disambiguate the overload.
    if isinstance(title_or_principal, Principal):
        principal = title_or_principal
        assert content is not None, "content required"
        return _docs.publish(
            conn, base_url, principal, content, title=None, public=public
        )
    # Legacy path: title may be None (treated as "auto-extract from content").
    title = title_or_principal
    body = content if content is not None else ""
    resolved_title = title if title else _extract_title(body)
    doc_id = Document.generate_id()
    share_token = Document.generate_share_token()
    _db.insert_document(
        conn,
        doc_id,
        resolved_title,
        body,
        share_token,
        is_public=public,
        owner_id=None,
    )
    return {
        "id": doc_id,
        "title": resolved_title,
        "share_url": f"{base_url}/d/{share_token}",
        "is_public": public,
        "owner_id": None,
    }


def get_doc(conn: sqlite3.Connection, doc_id: str) -> dict:
    """Direct DB read — does not enforce permissions. For legacy/test use."""
    doc = _db.get_document(conn, doc_id)
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


def list_docs(conn: sqlite3.Connection) -> list[dict]:
    docs = _db.list_documents(conn)
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


def search_docs(conn: sqlite3.Connection, query: str) -> list[dict]:
    docs = _db.search_documents(conn, query)
    return [
        {
            "id": d.id,
            "title": d.title,
            "updated_at": d.updated_at,
        }
        for d in docs
    ]


def share_doc(conn: sqlite3.Connection, base_url: str, doc_id: str) -> dict:
    doc = _db.get_document(conn, doc_id)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {"share_url": f"{base_url}/d/{doc.share_token}", "title": doc.title}


def update_doc(
    conn: sqlite3.Connection,
    base_url: str,
    doc_id: str,
    principal: Principal | None = None,
    *,
    content: str | None = None,
    title: str | None = None,
    if_version: int,
) -> dict:
    """Update via the service layer with optimistic concurrency control.

    Lets `ConflictError` propagate so the MCP boundary can translate it;
    returns a plain error dict for `not found`.
    """
    p = principal if principal is not None else _default_principal()
    try:
        doc = _docs.update(
            conn,
            doc_id,
            p,
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


def delete_doc(conn: sqlite3.Connection, doc_id: str) -> dict:
    deleted = _db.delete_document(conn, doc_id)
    return {"deleted": deleted, "id": doc_id}


def set_visibility_doc(
    conn: sqlite3.Connection, base_url: str, doc_id: str, is_public: bool
) -> dict:
    doc = _db.set_visibility(conn, doc_id, is_public)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "is_public": doc.is_public,
        "share_url": f"{base_url}/d/{doc.share_token}",
    }


def feature_doc(
    conn: sqlite3.Connection, doc_id: str, is_featured: bool = True
) -> dict:
    doc = _db.set_featured(conn, doc_id, is_featured)
    if doc is None:
        return {"error": f"Document {doc_id} not found"}
    return {
        "id": doc.id,
        "is_featured": doc.is_featured,
        "is_public": doc.is_public,
    }
