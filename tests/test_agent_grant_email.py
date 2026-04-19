"""Tests for the agent-grant email trigger."""

from unittest.mock import MagicMock

import pytest

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc


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
    for uid, email, name in [
        ("usr_alice", "alice@x", "Alice"),
        ("usr_bob", "bob@x", "Bob"),
    ]:
        conn.execute(
            "INSERT INTO users(id, email, display_name, is_admin, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (uid, email, name, "2026-04-19T00:00:00+00:00"),
        )
    conn.commit()
    doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        content="c",
        title="Alice Doc",
    )
    yield conn, doc
    conn.close()


def test_agent_grant_emails_owner(env):
    conn, doc = env
    agent = agents_svc.create_agent(conn, "usr_bob", "scribe")
    email = MagicMock()

    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target=agent.id,
        level="view",
        email_client=email,
    )

    email.send.assert_called_once()
    kwargs = email.send.call_args.kwargs
    assert kwargs["to"] == "bob@x"
    assert "your agent" in kwargs["subject"].lower() or "your agent" in kwargs["html"].lower()
    assert "scribe" in kwargs["html"]
    assert "Alice Doc" in kwargs["html"]
    assert "view" in kwargs["html"].lower()


def test_service_agent_grant_sends_no_email(env):
    conn, doc = env
    sa = agents_svc.create_service_agent(conn, "svc_openclaw", "Claw")
    email = MagicMock()

    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target=sa.id,
        level="view",
        email_client=email,
    )

    email.send.assert_not_called()


def test_email_failure_does_not_fail_grant(env):
    conn, doc = env
    agent = agents_svc.create_agent(conn, "usr_bob", "scribe")
    email = MagicMock()
    email.send.side_effect = RuntimeError("resend down")

    result = grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target=agent.id,
        level="view",
        email_client=email,
    )
    assert result["principal_id"] == agent.id
    row = conn.execute(
        "SELECT 1 FROM grants WHERE doc_id=? AND principal_id=?",
        (doc["id"], agent.id),
    ).fetchone()
    assert row is not None
