"""Tests for the agents service."""

import pytest

from markland.db import init_db


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


def test_agents_table_exists_with_expected_columns(conn):
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='agents'"
    ).fetchone()
    assert row is not None, "agents table missing"
    sql = row[0]
    for col in (
        "id",
        "display_name",
        "owner_type",
        "owner_id",
        "created_at",
        "revoked_at",
    ):
        assert col in sql


def test_agents_table_primary_key_is_id(conn):
    cols = conn.execute("PRAGMA table_info(agents)").fetchall()
    pk_cols = [c[1] for c in cols if c[5]]
    assert pk_cols == ["id"]


def test_agent_dataclass_generates_prefixed_id():
    from markland.models import Agent

    aid = Agent.generate_id()
    assert aid.startswith("agt_")
    assert len(aid) >= len("agt_") + 16


def test_agent_dataclass_now_returns_iso8601():
    from markland.models import Agent

    ts = Agent.now()
    assert "T" in ts and ts.endswith("+00:00")


def test_agent_dataclass_fields():
    from markland.models import Agent

    a = Agent(
        id="agt_abc",
        display_name="scribe",
        owner_type="user",
        owner_id="usr_xyz",
        created_at="2026-04-19T00:00:00+00:00",
        revoked_at=None,
    )
    assert a.id == "agt_abc"
    assert a.owner_type == "user"
    assert a.revoked_at is None


def _make_user(conn, user_id="usr_alice", email="alice@example.com"):
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (user_id, email, "Alice", "2026-04-19T00:00:00+00:00"),
    )
    conn.commit()


def test_create_agent_inserts_row_owned_by_user(conn):
    from markland.service import agents as agents_svc

    _make_user(conn)
    agent = agents_svc.create_agent(
        conn, owner_user_id="usr_alice", display_name="scribe"
    )
    assert agent.id.startswith("agt_")
    assert agent.owner_type == "user"
    assert agent.owner_id == "usr_alice"
    assert agent.display_name == "scribe"
    assert agent.revoked_at is None


def test_create_agent_rejects_missing_user(conn):
    from markland.service import agents as agents_svc

    with pytest.raises(ValueError, match="user_not_found"):
        agents_svc.create_agent(conn, owner_user_id="usr_nobody", display_name="x")


def test_create_agent_requires_display_name(conn):
    from markland.service import agents as agents_svc

    _make_user(conn)
    with pytest.raises(ValueError, match="display_name_required"):
        agents_svc.create_agent(conn, owner_user_id="usr_alice", display_name="   ")


def test_list_agents_returns_only_active_user_owned(conn):
    from markland.service import agents as agents_svc

    _make_user(conn)
    a1 = agents_svc.create_agent(conn, "usr_alice", "a1")
    a2 = agents_svc.create_agent(conn, "usr_alice", "a2")
    agents_svc.revoke_agent(conn, a2.id, owner_user_id="usr_alice")

    listed = agents_svc.list_agents(conn, owner_user_id="usr_alice")
    listed_ids = [a.id for a in listed]
    assert a1.id in listed_ids
    assert a2.id not in listed_ids


def test_revoke_agent_is_soft_delete(conn):
    from markland.service import agents as agents_svc

    _make_user(conn)
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    agents_svc.revoke_agent(conn, a.id, owner_user_id="usr_alice")
    row = conn.execute(
        "SELECT revoked_at FROM agents WHERE id=?", (a.id,)
    ).fetchone()
    assert row[0] is not None


def test_revoke_agent_rejects_non_owner(conn):
    from markland.service import agents as agents_svc

    _make_user(conn, "usr_alice", "alice@x")
    _make_user(conn, "usr_bob", "bob@x")
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    with pytest.raises(PermissionError):
        agents_svc.revoke_agent(conn, a.id, owner_user_id="usr_bob")


def test_revoke_unknown_agent_raises(conn):
    from markland.service import agents as agents_svc

    _make_user(conn)
    with pytest.raises(LookupError):
        agents_svc.revoke_agent(conn, "agt_nope", owner_user_id="usr_alice")


def test_create_service_agent_uses_service_owner(conn):
    from markland.service import agents as agents_svc

    a = agents_svc.create_service_agent(
        conn, service_id="svc_openclaw", display_name="Claw"
    )
    assert a.owner_type == "service"
    assert a.owner_id == "svc_openclaw"


def test_get_agent_returns_none_when_missing(conn):
    from markland.service import agents as agents_svc

    assert agents_svc.get_agent(conn, "agt_missing") is None


def test_get_agent_returns_agent(conn):
    from markland.service import agents as agents_svc

    _make_user(conn)
    a = agents_svc.create_agent(conn, "usr_alice", "scribe")
    got = agents_svc.get_agent(conn, a.id)
    assert got is not None
    assert got.id == a.id
