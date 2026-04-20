"""Save-to-account service helpers: fork a public doc, toggle a bookmark."""

from __future__ import annotations

import sqlite3

from markland import db
from markland.models import Document


def _user_can_view(
    conn: sqlite3.Connection, *, doc: Document, user_id: str
) -> bool:
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
