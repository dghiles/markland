"""Tests for agent-token creation and resolution."""

import pytest

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import auth as auth_svc


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    c.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        ("usr_alice", "alice@x", "Alice", "2026-04-19T00:00:00+00:00"),
    )
    c.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        ("usr_bob", "bob@x", "Bob", "2026-04-19T00:00:00+00:00"),
    )
    c.commit()
    yield c
    c.close()


def test_create_agent_token_returns_prefixed_plaintext(conn):
    agent = agents_svc.create_agent(conn, "usr_alice", "scribe")
    tok_id, plaintext = auth_svc.create_agent_token(
        conn, agent_id=agent.id, owner_user_id="usr_alice", label="laptop"
    )
    assert tok_id.startswith("tok_")
    assert plaintext.startswith("mk_agt_")
    assert len(plaintext) > len("mk_agt_") + 30


def test_create_agent_token_rejects_non_owner(conn):
    agent = agents_svc.create_agent(conn, "usr_alice", "scribe")
    with pytest.raises(PermissionError):
        auth_svc.create_agent_token(
            conn, agent_id=agent.id, owner_user_id="usr_bob", label="x"
        )


def test_create_agent_token_rejects_revoked_agent(conn):
    agent = agents_svc.create_agent(conn, "usr_alice", "scribe")
    agents_svc.revoke_agent(conn, agent.id, owner_user_id="usr_alice")
    with pytest.raises(ValueError, match="agent_revoked"):
        auth_svc.create_agent_token(
            conn, agent_id=agent.id, owner_user_id="usr_alice", label="x"
        )


def test_create_agent_token_rejects_unknown(conn):
    with pytest.raises(LookupError):
        auth_svc.create_agent_token(
            conn, agent_id="agt_nope", owner_user_id="usr_alice", label="x"
        )


def test_resolve_agent_token_returns_user_owner_as_user_id(conn):
    agent = agents_svc.create_agent(conn, "usr_alice", "scribe")
    _, plaintext = auth_svc.create_agent_token(
        conn, agent_id=agent.id, owner_user_id="usr_alice", label="l"
    )
    principal = auth_svc.resolve_token(conn, plaintext)
    assert principal is not None
    assert principal.principal_type == "agent"
    assert principal.principal_id == agent.id
    assert principal.user_id == "usr_alice"
    assert principal.is_admin is False


def test_resolve_agent_token_for_service_agent_has_none_user_id(conn):
    sa = agents_svc.create_service_agent(conn, "svc_openclaw", "Claw")
    _, plaintext = auth_svc._create_token_for_agent(
        conn, agent_id=sa.id, label="ops"
    )
    principal = auth_svc.resolve_token(conn, plaintext)
    assert principal is not None
    assert principal.principal_type == "agent"
    assert principal.user_id is None
    assert principal.is_admin is False


def test_resolve_token_rejects_revoked_agent(conn):
    agent = agents_svc.create_agent(conn, "usr_alice", "scribe")
    _, plaintext = auth_svc.create_agent_token(
        conn, agent_id=agent.id, owner_user_id="usr_alice", label="l"
    )
    agents_svc.revoke_agent(conn, agent.id, owner_user_id="usr_alice")
    assert auth_svc.resolve_token(conn, plaintext) is None
