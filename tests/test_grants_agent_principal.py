"""Tests for grant() accepting agent ids alongside emails."""

import pytest

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.permissions import NotFound


class _UserPrincipal:
    def __init__(self, uid):
        self.principal_type = "user"
        self.principal_id = uid
        self.user_id = uid
        self.display_name = uid
        self.is_admin = False


@pytest.fixture
def env(tmp_path):
    conn = init_db(tmp_path / "t.db")
    for uid, email in [("usr_alice", "alice@x"), ("usr_bob", "bob@x")]:
        conn.execute(
            "INSERT INTO users(id, email, display_name, is_admin, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (uid, email, uid, "2026-04-19T00:00:00+00:00"),
        )
    conn.commit()
    doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        content="c",
        title="d",
    )
    yield conn, doc
    conn.close()


def test_grant_by_email_creates_user_grant(env):
    conn, doc = env
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target="bob@x",
        level="view",
        email_client=None,
    )
    row = conn.execute(
        "SELECT principal_type, principal_id, level FROM grants WHERE doc_id=?",
        (doc["id"],),
    ).fetchone()
    assert row[0] == "user"
    assert row[1] == "usr_bob"
    assert row[2] == "view"


def test_grant_by_agent_id_creates_agent_grant(env):
    conn, doc = env
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target=agent.id,
        level="edit",
        email_client=None,
    )
    row = conn.execute(
        "SELECT principal_type, principal_id, level FROM grants WHERE doc_id=?",
        (doc["id"],),
    ).fetchone()
    assert row[0] == "agent"
    assert row[1] == agent.id
    assert row[2] == "edit"


def test_grant_unknown_agent_raises_not_found(env):
    conn, doc = env
    with pytest.raises(NotFound, match="agent_not_found"):
        grants_svc.grant(
            conn,
            base_url="http://t",
            principal=_UserPrincipal("usr_alice"),
            doc_id=doc["id"],
            target="agt_nope",
            level="view",
            email_client=None,
        )


def test_grant_revoked_agent_raises(env):
    conn, doc = env
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    agents_svc.revoke_agent(conn, agent.id, owner_user_id="usr_bob")
    with pytest.raises(NotFound, match="agent_revoked"):
        grants_svc.grant(
            conn,
            base_url="http://t",
            principal=_UserPrincipal("usr_alice"),
            doc_id=doc["id"],
            target=agent.id,
            level="view",
            email_client=None,
        )
