"""End-to-end: two users, publish -> grant view -> grant edit -> update."""

from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from markland.db import init_db
from markland.server import build_mcp


BASE = "https://markland.test"


class _Ctx:
    def __init__(self, principal):
        self.principal = principal


def _seed_users(conn, **email_by_uid: str) -> None:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, created_at) VALUES (?, ?, '2026-01-01')",
            (uid, email),
        )
    conn.commit()


def _user(uid: str):
    from markland.service.permissions import Principal

    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def test_two_user_share_flow(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _seed_users(conn, usr_alice="a@x", usr_bob="b@x")
    alice = _user("usr_alice")
    bob = _user("usr_bob")

    email = MagicMock()
    h = build_mcp(conn, base_url=BASE, email_client=email).markland_handlers

    # 1. Alice publishes
    doc = h["markland_publish"](_Ctx(alice), content="# Draft\nv1")
    assert doc["owner_id"] == "usr_alice"
    doc_id = doc["id"]

    # 2. Bob cannot see or modify
    with pytest.raises(ToolError) as exc_info:
        h["markland_get"](_Ctx(bob), doc_id=doc_id)
    assert exc_info.value.data["code"] == "not_found"
    with pytest.raises(ToolError) as exc_info:
        h["markland_update"](
            _Ctx(bob), doc_id=doc_id, if_version=1, content="hacked"
        )
    assert exc_info.value.data["code"] == "not_found"

    # 3. Alice grants view
    grant_out = h["markland_grant"](
        _Ctx(alice), doc_id=doc_id, principal="b@x", level="view"
    )
    assert grant_out["level"] == "view"
    email.send.assert_called_once()

    # 4. Bob can now read but not write
    view = h["markland_get"](_Ctx(bob), doc_id=doc_id)
    assert view["content"] == "# Draft\nv1"
    with pytest.raises(ToolError) as exc_info:
        h["markland_update"](
            _Ctx(bob), doc_id=doc_id, if_version=1, content="hacked"
        )
    assert exc_info.value.data["code"] == "forbidden"

    # 5. Alice upgrades Bob to edit
    h["markland_grant"](
        _Ctx(alice), doc_id=doc_id, principal="b@x", level="edit"
    )
    updated = h["markland_update"](
        _Ctx(bob), doc_id=doc_id, if_version=1, content="# Draft\nv2"
    )
    assert updated["id"] == doc_id

    # 6. Alice confirms the new content
    final = h["markland_get"](_Ctx(alice), doc_id=doc_id)
    assert final["content"] == "# Draft\nv2"

    # 7. Alice revokes -- Bob is locked out
    h["markland_revoke"](_Ctx(alice), doc_id=doc_id, principal="usr_bob")
    with pytest.raises(ToolError) as exc_info:
        h["markland_get"](_Ctx(bob), doc_id=doc_id)
    assert exc_info.value.data["code"] == "not_found"
