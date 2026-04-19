"""MCP tools are ownership-aware and surface grant operations."""

from unittest.mock import MagicMock

import pytest

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
    assert {d["id"] for d in out} == {a["id"]}


def test_get_denies_stranger_as_not_found(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="secret", title="A")
    out = h["markland_get"](_Ctx(bob), doc_id=a["id"])
    assert out == {"error": "not_found"}


def test_update_requires_edit(harness):
    conn, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    out = h["markland_update"](_Ctx(bob), doc_id=a["id"], if_version=1, content="new")
    assert out == {"error": "not_found"}


def test_delete_requires_owner(harness):
    conn, h, ec = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    h["markland_grant"](_Ctx(alice), doc_id=a["id"], principal="b@x", level="edit")
    out = h["markland_delete"](_Ctx(bob), doc_id=a["id"])
    assert out == {"error": "forbidden"}
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
    assert len(listed) == 1 and listed[0]["principal_id"] == "usr_bob"

    revoke_out = h["markland_revoke"](
        _Ctx(alice), doc_id=a["id"], principal="usr_bob"
    )
    assert revoke_out["revoked"] is True
    assert h["markland_list_grants"](_Ctx(alice), doc_id=a["id"]) == []


def test_non_owner_cannot_grant(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    bob = _user("usr_bob")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    h["markland_grant"](_Ctx(alice), doc_id=a["id"], principal="b@x", level="edit")
    out = h["markland_grant"](
        _Ctx(bob), doc_id=a["id"], principal="b@x", level="edit"
    )
    assert out == {"error": "forbidden"}


def test_grant_with_unknown_email_returns_invalid_argument(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    out = h["markland_grant"](
        _Ctx(alice), doc_id=a["id"], principal="nobody@x", level="view"
    )
    assert out == {"error": "invalid_argument", "reason": "target_not_found"}


def test_grant_with_unknown_agent_id_returns_not_found(harness):
    _, h, _ = harness
    alice = _user("usr_alice")
    a = h["markland_publish"](_Ctx(alice), content="x", title="A")
    out = h["markland_grant"](
        _Ctx(alice), doc_id=a["id"], principal="agt_future", level="view"
    )
    assert out == {"error": "not_found"}
