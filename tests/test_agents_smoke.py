"""End-to-end smoke: agent tokens, grants, inheritance."""

import pytest

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import auth as auth_svc
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.permissions import (
    NotFound,
    PermissionDenied,
    check_permission,
)


class _UserPrincipal:
    def __init__(self, uid, name="U"):
        self.principal_type = "user"
        self.principal_id = uid
        self.user_id = uid
        self.display_name = name
        self.is_admin = False


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "smoke.db")
    for uid, email, name in [
        ("usr_alice", "alice@x", "Alice"),
        ("usr_bob", "bob@x", "Bob"),
    ]:
        c.execute(
            "INSERT INTO users(id, email, display_name, is_admin, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (uid, email, name, "2026-04-19T00:00:00+00:00"),
        )
    c.commit()
    yield c
    c.close()


def test_full_agent_inheritance_flow(conn):
    # 1. Alice publishes a doc.
    alice = _UserPrincipal("usr_alice", "Alice")
    doc = docs_svc.publish(
        conn,
        base_url="http://t",
        principal=alice,
        content="# Hello",
        title="Alice's Notes",
    )

    # 2. Bob creates an agent and mints an agent token.
    agent = agents_svc.create_agent(conn, "usr_bob", "bob-scribe")
    _, plaintext = auth_svc.create_agent_token(
        conn, agent_id=agent.id, owner_user_id="usr_bob", label="laptop",
    )
    assert plaintext.startswith("mk_agt_")

    # 3. Resolving the agent token yields a Principal tied to Bob.
    principal = auth_svc.resolve_token(conn, plaintext)
    assert principal is not None
    assert principal.principal_type == "agent"
    assert principal.user_id == "usr_bob"

    # 4. Without a grant, the agent cannot see Alice's doc.
    with pytest.raises(NotFound):
        check_permission(conn, principal, doc["id"], "view")

    # 5. Alice grants Bob view access.
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=alice,
        doc_id=doc["id"],
        target="bob@x",
        level="view",
        email_client=None,
    )

    # 6. Bob's agent now inherits the grant.
    tag = check_permission(conn, principal, doc["id"], "view")
    assert tag == "view"
    # 7. View-only inheritance: edit is still denied.
    with pytest.raises(PermissionDenied):
        check_permission(conn, principal, doc["id"], "edit")

    # 8. Alice upgrades Bob to edit; the agent inherits edit.
    grants_svc.grant(
        conn,
        base_url="http://t",
        principal=alice,
        doc_id=doc["id"],
        target="bob@x",
        level="edit",
        email_client=None,
    )
    tag = check_permission(conn, principal, doc["id"], "edit")
    assert tag == "edit"

    # 9. Revoking the agent invalidates its token.
    agents_svc.revoke_agent(conn, agent.id, owner_user_id="usr_bob")
    assert auth_svc.resolve_token(conn, plaintext) is None
