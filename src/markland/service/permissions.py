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


def _owner_id_for_principal(principal: Principal) -> str | None:
    """For user principals, the doc-owner identity is principal_id.

    For agent principals (Plan 4), it will be the agent's owning user_id
    (stored as principal.user_id). Today agents have no `agents` row so we
    return principal.user_id which is None for bare agent principals.
    """
    if principal.principal_type == "user":
        return principal.principal_id
    return principal.user_id


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
    owner_identity = _owner_id_for_principal(principal)
    if doc.owner_id is not None and owner_identity is not None and owner_identity == doc.owner_id:
        return "owner"

    # (2) Direct grant (doc, principal_id)
    grant = get_grant(conn, doc_id, principal.principal_id)
    if grant is not None:
        if action in _LEVEL_TO_MAX_ACTION[grant.level]:
            return grant.level
        raise PermissionDenied(
            f"grant level '{grant.level}' does not permit {action}"
        )

    # (3) Agent inheritance — user-owned agent inherits its owner's grant.
    if principal.principal_type == "agent" and principal.user_id is not None:
        owner_grant = conn.execute(
            "SELECT level FROM grants "
            "WHERE doc_id = ? AND principal_id = ? AND principal_type = 'user'",
            (doc_id, principal.user_id),
        ).fetchone()
        if owner_grant is not None:
            inherited_level = owner_grant[0]
            if action == "view":
                return inherited_level  # "view" or "edit" — either allows view
            if action == "edit":
                if inherited_level == "edit":
                    return "edit"
                raise PermissionDenied(
                    "edit requires edit-level grant"
                )

    # (4) Public + view
    if doc.is_public:
        if action == "view":
            return "public"
        # Public doc is visible but read-only to strangers — surface a
        # distinct PermissionDenied rather than NotFound, since the
        # existence of the doc is already disclosed by its public listing.
        raise PermissionDenied(
            f"public doc only permits view, not {action}"
        )

    # (5) Share-token flow is handled outside this function — `/d/{share_token}`
    # reads the doc directly via `get_document_by_token` and never goes through
    # check_permission.

    # (6) Deny — mask as NotFound to prevent ID enumeration (spec §12.5).
    raise NotFound(f"document {doc_id}")


__all__ = [
    "Principal",
    "PermissionError",
    "NotFound",
    "PermissionDenied",
    "check_permission",
]
