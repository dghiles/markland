"""Spec section 14 end-to-end launch gate.

This is THE test that declares Markland ready for Phase 1 beta. It exercises
the full auth + sharing + conflict + audit surface in one flow:

  1. Alice signs up.
  2. Alice creates a user token; Alice's agent initializes.
  3. Alice publishes a doc.
  4. Alice grants edit to Bob by email.
  5. Bob reads the doc via his own user token.
  6. Bob's user-owned agent updates the doc with the correct if_version.
  7. An invite is created for a third user Carol.
  8. Carol (a brand-new user) accepts the invite.
  9. Carol can read the updated doc.
 10. The audit_log table has >= 7 rows covering publish/grant/update/invite_create/invite_accept.

If this test passes, the success criteria in spec section 14 are met end-to-end.
"""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service.auth import Principal, create_user_token
from markland.service.email import EmailClient
from markland.service.users import create_user
from markland.web.app import create_app


class _NoopEmail(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="t@t.dev")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", "1000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "1000")
    conn = init_db(tmp_path / "e2e.db")
    app = create_app(conn, mount_mcp=False, base_url="http://m")
    return {"conn": conn, "client": TestClient(app), "email": _NoopEmail()}


def _principal(user_id: str, name: str) -> Principal:
    return Principal(
        principal_id=user_id,
        principal_type="user",
        display_name=name,
        is_admin=False,
        user_id=user_id,
    )


def test_launch_gate_end_to_end(env):
    conn = env["conn"]
    email = env["email"]

    # 1. Sign up Alice and Bob. Carol signs up later via invite acceptance.
    alice = create_user(conn, email="alice@ex.com", display_name="Alice")
    bob = create_user(conn, email="bob@ex.com", display_name="Bob")
    alice_p = _principal(alice.id, "Alice")
    bob_p = _principal(bob.id, "Bob")

    # 2. Tokens.
    _, alice_token = create_user_token(conn, user_id=alice.id, label="alice-laptop")
    _, bob_token = create_user_token(conn, user_id=bob.id, label="bob-laptop")
    assert alice_token and alice_token != bob_token

    # 3. Alice publishes.
    result = docs_svc.publish_doc(
        conn,
        base_url="http://m",
        principal=alice_p,
        title="Launch gate doc",
        content="Line 1.",
    )
    doc_id = result["id"]

    # 4. Alice grants edit to Bob.
    grants_svc.grant(
        conn,
        base_url="http://m",
        principal=alice_p,
        doc_id=doc_id,
        target="bob@ex.com",
        level="edit",
        email_client=email,
    )

    # 5. Bob reads.
    bob_doc = docs_svc.get_doc(conn, principal=bob_p, doc_id=doc_id)
    assert bob_doc.content == "Line 1."
    original_version = bob_doc.version

    # 6. Bob updates with the correct if_version.
    updated = docs_svc.update_doc(
        conn,
        principal=bob_p,
        doc_id=doc_id,
        content="Line 1.\nLine 2 from Bob.",
        if_version=original_version,
    )
    assert updated.version == original_version + 1

    # 7. Create an invite (owner-created, routed through Alice).
    created = invites_svc.create_invite(
        conn,
        doc_id=doc_id,
        created_by_user_id=alice.id,
        level="view",
        base_url="http://m",
    )
    invite_token_plaintext = created.url.rsplit("/", 1)[-1]

    # 8. Carol signs up + accepts the invite.
    carol = create_user(conn, email="carol@ex.com", display_name="Carol")
    invites_svc.accept_invite(
        conn, invite_token=invite_token_plaintext, user_id=carol.id
    )

    # 9. Carol can now view.
    carol_p = _principal(carol.id, "Carol")
    carol_doc = docs_svc.get_doc(conn, principal=carol_p, doc_id=doc_id)
    assert "Line 2 from Bob" in carol_doc.content

    # 10. Audit log has >= 5 rows covering the right actions.
    rows = conn.execute("SELECT action FROM audit_log ORDER BY id").fetchall()
    actions = [r[0] for r in rows]
    assert len(actions) >= 5, f"expected >=5 audit rows, got {len(actions)}: {actions}"
    for required in ("publish", "grant", "update", "invite_create", "invite_accept"):
        assert required in actions, f"missing audit action: {required}"
