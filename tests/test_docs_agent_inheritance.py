"""Tests for user-owned-agent grant inheritance (spec §5 step 3)."""

import pytest

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.permissions import NotFound, PermissionDenied, check_permission


def _mk_user(conn, uid, email):
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (uid, email, uid, "2026-04-19T00:00:00+00:00"),
    )
    conn.commit()


class _UserPrincipal:
    def __init__(self, user_id, is_admin=False):
        self.principal_type = "user"
        self.principal_id = user_id
        self.display_name = user_id
        self.user_id = user_id
        self.is_admin = is_admin


class _AgentPrincipal:
    def __init__(self, agent_id, owner_user_id):
        self.principal_type = "agent"
        self.principal_id = agent_id
        self.display_name = agent_id
        self.user_id = owner_user_id  # None for service-owned
        self.is_admin = False


@pytest.fixture
def env(tmp_path):
    conn = init_db(tmp_path / "t.db")
    _mk_user(conn, "usr_alice", "alice@x")
    _mk_user(conn, "usr_bob", "bob@x")
    doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        content="# hi",
        title="Alice doc",
    )
    yield conn, doc
    conn.close()


def test_agent_inherits_owner_view_grant(env):
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
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    tag = check_permission(
        conn, _AgentPrincipal(agent.id, "usr_bob"), doc["id"], "view"
    )
    assert tag == "view"


def test_agent_inherits_owner_edit_grant(env):
    conn, doc = env
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target="bob@x",
        level="edit",
        email_client=None,
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    tag = check_permission(
        conn, _AgentPrincipal(agent.id, "usr_bob"), doc["id"], "edit"
    )
    assert tag == "edit"


def test_agent_without_owner_grant_denied(env):
    conn, doc = env
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    with pytest.raises(NotFound):
        check_permission(
            conn, _AgentPrincipal(agent.id, "usr_bob"), doc["id"], "view"
        )


def test_direct_agent_grant_takes_precedence(env):
    conn, doc = env
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    # Direct grant to the agent — view only.
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target=agent.id,
        level="view",
        email_client=None,
    )
    # Owner Bob has edit (separate grant).
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target="bob@x",
        level="edit",
        email_client=None,
    )
    # Step 2 matches first — direct grant level wins (view, not edit).
    tag = check_permission(
        conn, _AgentPrincipal(agent.id, "usr_bob"), doc["id"], "view"
    )
    assert tag == "view"
    with pytest.raises(PermissionDenied):
        check_permission(
            conn, _AgentPrincipal(agent.id, "usr_bob"), doc["id"], "edit"
        )


def test_service_agent_does_not_inherit(env):
    conn, doc = env
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target="bob@x",
        level="edit",
        email_client=None,
    )
    sa = agents_svc.create_service_agent(conn, "svc_openclaw", "Claw")
    with pytest.raises(NotFound):
        check_permission(
            conn, _AgentPrincipal(sa.id, owner_user_id=None), doc["id"], "view"
        )


def test_service_agent_cannot_publish(env):
    conn, _ = env
    sa = agents_svc.create_service_agent(conn, "svc_openclaw", "Claw")
    with pytest.raises(PermissionError, match="service_agent_cannot_publish"):
        docs_svc.publish(
            conn,
            base_url="http://t",
            principal=_AgentPrincipal(sa.id, owner_user_id=None),
            content="y",
            title="x",
        )


def test_agent_with_owning_user_as_doc_owner_can_view(env):
    """P1-B: when the agent's owning user IS the doc owner, the agent
    inherits view access on the doc (no explicit grant needed)."""
    conn, _ = env
    # Bob owns the agent + a doc.
    bob_doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_bob"),
        content="bob's doc",
        title="bob",
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    tag = check_permission(
        conn, _AgentPrincipal(agent.id, "usr_bob"), bob_doc["id"], "view"
    )
    assert tag in ("owner", "view", "edit")


def test_agent_with_owning_user_as_doc_owner_can_edit(env):
    """P1-B: agent inherits edit access on its owning user's docs."""
    conn, _ = env
    bob_doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_bob"),
        content="bob's doc",
        title="bob",
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    tag = check_permission(
        conn, _AgentPrincipal(agent.id, "usr_bob"), bob_doc["id"], "edit"
    )
    assert tag in ("owner", "edit")


def test_agent_cannot_get_owner_action_on_owning_user_doc(env):
    """P1-B / markland-b42: an agent token MUST NOT inherit owner-action
    rights on its owning user's docs. A leaked agent token must not be
    able to delete/flip-visibility on the user's docs."""
    conn, _ = env
    bob_doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_bob"),
        content="bob's doc",
        title="bob",
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    with pytest.raises(PermissionDenied):
        check_permission(
            conn, _AgentPrincipal(agent.id, "usr_bob"), bob_doc["id"], "owner"
        )


def test_agent_cannot_get_owner_action_via_inherited_edit_grant(env):
    """P1-B: even when the owning user has an explicit edit grant, the
    agent cannot perform owner actions on that doc."""
    conn, doc = env
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_alice"),
        doc_id=doc["id"],
        target="bob@x",
        level="edit",
        email_client=None,
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    with pytest.raises(PermissionDenied):
        check_permission(
            conn, _AgentPrincipal(agent.id, "usr_bob"), doc["id"], "owner"
        )


def test_agent_cannot_delete_owning_user_doc(env):
    """P1-B integration: agent calling delete on owning user's doc must
    fail with PermissionDenied (not silently succeed)."""
    conn, _ = env
    bob_doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_bob"),
        content="bob's doc",
        title="bob",
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    with pytest.raises(PermissionDenied):
        docs_svc.delete(
            conn, _AgentPrincipal(agent.id, "usr_bob"), bob_doc["id"]
        )


def test_agent_cannot_set_visibility_on_owning_user_doc(env):
    """P1-B integration: agent calling set_visibility on owning user's doc
    must fail."""
    conn, _ = env
    bob_doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_UserPrincipal("usr_bob"),
        content="bob's doc",
        title="bob",
    )
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    with pytest.raises(PermissionDenied):
        docs_svc.set_visibility(
            conn,
            "http://t",
            _AgentPrincipal(agent.id, "usr_bob"),
            bob_doc["id"],
            True,
        )


def test_user_owned_agent_publishes_with_owner_id(env):
    conn, _ = env
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-agent")
    doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=_AgentPrincipal(agent.id, owner_user_id="usr_bob"),
        content="y",
        title="x",
    )
    row = conn.execute(
        "SELECT owner_id FROM documents WHERE id = ?", (doc["id"],)
    ).fetchone()
    assert row[0] == "usr_bob"
