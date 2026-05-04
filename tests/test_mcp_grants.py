"""MCP tools are ownership-aware and surface grant operations."""

from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from markland.db import init_db
from markland.server import build_mcp
from markland.service.auth import Principal


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def _seed_users(conn, **email_by_uid: str) -> None:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


class _Ctx:
    """Stand-in for FastMCP's Context carrying a Principal."""

    def __init__(self, principal: Principal):
        self.principal = principal


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    email_client = MagicMock()
    handlers = build_mcp(
        conn, base_url=BASE, email_client=email_client
    ).markland_handlers
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
    assert isinstance(out, dict)
    assert isinstance(out["items"], list)
    assert {d["id"] for d in out["items"]} == {a["id"]}


def test_get_denies_stranger_as_not_found(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="secret", title="A")
    with pytest.raises(ToolError) as exc_info:
        h["markland_get"](_Ctx(bob), doc_id=a["id"])
    assert exc_info.value.data["code"] == "not_found"


def test_update_requires_edit(harness):
    conn, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    with pytest.raises(ToolError) as exc_info:
        h["markland_update"](_Ctx(bob), doc_id=a["id"], if_version=1, content="new")
    assert exc_info.value.data["code"] == "not_found"


def test_delete_requires_owner(harness):
    conn, h, ec = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    h["markland_grant"](_Ctx(alice), doc_id=a["id"], principal="b@x", level="edit")
    with pytest.raises(ToolError) as exc_info:
        h["markland_delete"](_Ctx(bob), doc_id=a["id"])
    assert exc_info.value.data["code"] == "forbidden"
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
    assert isinstance(listed, dict)
    assert isinstance(listed["items"], list)
    assert len(listed["items"]) == 1 and listed["items"][0]["principal_id"] == "usr_bob"

    revoke_out = h["markland_revoke"](
        _Ctx(alice), doc_id=a["id"], principal="usr_bob"
    )
    assert revoke_out["revoked"] is True
    after = h["markland_list_grants"](_Ctx(alice), doc_id=a["id"])
    assert after["items"] == []


def test_non_owner_cannot_grant(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    h["markland_grant"](_Ctx(alice), doc_id=a["id"], principal="b@x", level="edit")
    with pytest.raises(ToolError) as exc_info:
        h["markland_grant"](
            _Ctx(bob), doc_id=a["id"], principal="b@x", level="edit"
        )
    assert exc_info.value.data["code"] == "forbidden"


def test_grant_with_unknown_email_silently_creates_invite(harness):
    """P2-E / markland-yi1: an MCP grant to an unknown email no longer
    raises invalid_argument with reason=target_not_found (which leaked
    membership). It silently creates an invite and returns the same
    grant-shaped envelope."""
    conn, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    result = h["markland_grant"](
        _Ctx(alice), doc_id=a["id"], principal="nobody@x", level="view"
    )
    # Same shape as a successful grant.
    assert result["doc_id"] == a["id"]
    assert result["level"] == "view"
    # Invite was created.
    rows = conn.execute(
        "SELECT id FROM invites WHERE doc_id = ?", (a["id"],)
    ).fetchall()
    assert len(rows) == 1


def test_grant_with_non_email_target_still_invalid_argument(harness):
    """A non-email, non-agt_ target (typo) still raises invalid_argument
    — this is a real input error, not enumeration."""
    _, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    with pytest.raises(ToolError) as exc_info:
        h["markland_grant"](
            _Ctx(alice), doc_id=a["id"], principal="not-an-email", level="view"
        )
    assert exc_info.value.data["code"] == "invalid_argument"


def test_grant_with_unknown_agent_id_returns_not_found(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    with pytest.raises(ToolError) as exc_info:
        h["markland_grant"](
            _Ctx(alice), doc_id=a["id"], principal="agt_future", level="view"
        )
    assert exc_info.value.data["code"] == "not_found"
