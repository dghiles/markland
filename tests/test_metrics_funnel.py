"""End-to-end funnel emission — six events should fire across a user's first session."""

import json

import pytest

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service import metrics
from markland.service.auth import Principal, create_user_token
from markland.service.email import EmailClient
from markland.service.users import create_user


class _NoopEmail(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="t@t.dev")


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics._reset_for_tests()
    yield
    metrics._reset_for_tests()


def _events(capsys) -> list[dict]:
    out = capsys.readouterr().out
    return [json.loads(line) for line in out.splitlines() if line.strip().startswith("{")]


def test_full_funnel_emits_six_events(tmp_path, capsys):
    conn = init_db(tmp_path / "f.db")

    # 1. signup
    alice = create_user(conn, email="alice@ex.com", display_name="Alice")
    # 2. token_create
    create_user_token(conn, user_id=alice.id, label="laptop")

    alice_p = Principal(
        principal_id=alice.id,
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id=alice.id,
    )

    # 3. first_mcp_call — middleware emits this in the live path; simulate here.
    metrics.emit_first_time("first_mcp_call", principal_id=alice.id)

    # 4. first_publish
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice_p, title="t", content="c"
    )
    # 5. first_grant
    bob = create_user(conn, email="bob@ex.com", display_name="Bob")
    grants_svc.grant(
        conn,
        base_url="x",
        principal=alice_p,
        doc_id=doc["id"],
        target="bob@ex.com",
        level="view",
        email_client=_NoopEmail(),
    )
    # 6. first_invite_accept
    created = invites_svc.create_invite(
        conn,
        doc_id=doc["id"],
        created_by_user_id=alice.id,
        level="view",
        base_url="http://m",
    )
    token = created.url.rsplit("/", 1)[-1]
    invites_svc.accept_invite(conn, invite_token=token, user_id=bob.id)

    events = _events(capsys)
    names = {e["event"] for e in events}
    assert "signup" in names
    assert "token_create" in names
    assert "first_mcp_call" in names
    assert "first_publish" in names
    assert "first_grant" in names
    assert "first_invite_accept" in names
