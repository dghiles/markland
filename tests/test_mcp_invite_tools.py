"""End-to-end tests for the invite MCP tools via the in-process handler map."""

import pytest

from markland.db import init_db
from markland.server import build_mcp
from markland.service.auth import Principal


BASE = "https://markland.dev"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


class _Ctx:
    def __init__(self, principal: Principal):
        self.principal = principal


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_mallory', 'mallory@example.com', 'Mallory', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 't', 'c', 'tok', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
        "0, 0, 'usr_alice')"
    )
    conn.commit()
    handlers = build_mcp(conn, base_url=BASE).markland_handlers
    return conn, handlers


def test_markland_create_invite_owner_succeeds(harness):
    _, h = harness
    out = h["markland_create_invite"](
        _Ctx(_user("usr_alice")), doc_id="doc_a", level="view"
    )
    assert out["invite_id"].startswith("inv_")
    assert out["url"].startswith("https://markland.dev/invite/")
    assert out["level"] == "view"
    assert out["expires_at"] is None


def test_markland_create_invite_non_owner_denied(harness):
    _, h = harness
    # Non-owner cannot see the (private) doc, so it's masked as not_found
    # per spec §12.5 — identical to how other owner-only tools mask.
    out = h["markland_create_invite"](
        _Ctx(_user("usr_mallory")), doc_id="doc_a", level="view"
    )
    assert out == {"error": "not_found"}


def test_markland_create_invite_viewer_forbidden(harness):
    conn, h = harness
    # Grant mallory view-only, then she attempts to create an invite — the
    # doc is visible but action requires "owner", so check_permission raises
    # PermissionDenied → {"error": "forbidden"}.
    conn.execute(
        "INSERT INTO grants (doc_id, principal_id, principal_type, level, granted_by, granted_at) "
        "VALUES ('doc_a', 'usr_mallory', 'user', 'view', 'usr_alice', '2026-01-02T00:00:00+00:00')"
    )
    conn.commit()
    out = h["markland_create_invite"](
        _Ctx(_user("usr_mallory")), doc_id="doc_a", level="view"
    )
    assert out == {"error": "forbidden"}


def test_markland_create_invite_bad_level_rejected(harness):
    _, h = harness
    with pytest.raises(ValueError):
        h["markland_create_invite"](
            _Ctx(_user("usr_alice")), doc_id="doc_a", level="admin"
        )


def test_markland_revoke_invite_owner_succeeds(harness):
    conn, h = harness
    r = h["markland_create_invite"](
        _Ctx(_user("usr_alice")), doc_id="doc_a", level="view"
    )
    result = h["markland_revoke_invite"](
        _Ctx(_user("usr_alice")), invite_id=r["invite_id"]
    )
    assert result == {"revoked": True, "invite_id": r["invite_id"]}
    row = conn.execute(
        "SELECT revoked_at FROM invites WHERE id = ?", (r["invite_id"],)
    ).fetchone()
    assert row[0] is not None


def test_markland_revoke_invite_non_owner_denied(harness):
    _, h = harness
    r = h["markland_create_invite"](
        _Ctx(_user("usr_alice")), doc_id="doc_a", level="view"
    )
    out = h["markland_revoke_invite"](
        _Ctx(_user("usr_mallory")), invite_id=r["invite_id"]
    )
    assert out == {"error": "not_found"}


def test_markland_create_invite_expires_in_days(harness):
    _, h = harness
    out = h["markland_create_invite"](
        _Ctx(_user("usr_alice")), doc_id="doc_a", level="edit", expires_in_days=7
    )
    assert out["expires_at"] is not None
