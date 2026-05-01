"""Tests for the markland_list_my_agents MCP tool."""

import pytest

from markland.db import init_db
from markland.server import build_mcp
from markland.service import agents as agents_svc
from markland.service.auth import Principal


def _mk_user(conn, uid, email):
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (uid, email, uid, "2026-04-19T00:00:00+00:00"),
    )
    conn.commit()


class _Ctx:
    def __init__(self, principal):
        self.principal = principal


def _user_principal(uid="usr_alice"):
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id=uid,
    )


def _agent_principal(aid, owner_user_id):
    return Principal(
        principal_id=aid,
        principal_type="agent",
        display_name=aid,
        is_admin=False,
        user_id=owner_user_id,
    )


@pytest.fixture
def harness(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _mk_user(conn, "usr_alice", "alice@x")
    handlers = build_mcp(conn, base_url="http://t").markland_handlers
    return conn, handlers


def test_user_principal_sees_own_agents(harness):
    conn, h = harness
    a1 = agents_svc.create_agent(conn, "usr_alice", "a1")
    a2 = agents_svc.create_agent(conn, "usr_alice", "a2")
    result = h["markland_list_my_agents"](_Ctx(_user_principal()))
    assert isinstance(result, dict)
    assert isinstance(result["items"], list)
    ids = [r["id"] for r in result["items"]]
    assert a1.id in ids and a2.id in ids


def test_agent_principal_sees_only_self(harness):
    conn, h = harness
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    result = h["markland_list_my_agents"](
        _Ctx(_agent_principal(a.id, "usr_alice"))
    )
    assert isinstance(result, dict)
    assert isinstance(result["items"], list)
    assert len(result["items"]) == 1
    assert result["items"][0]["id"] == a.id


def test_service_agent_principal_returns_empty(harness):
    conn, h = harness
    sa = agents_svc.create_service_agent(conn, "svc_openclaw", "Claw")
    result = h["markland_list_my_agents"](
        _Ctx(_agent_principal(sa.id, owner_user_id=None))
    )
    assert isinstance(result, dict)
    assert result["items"] == []
