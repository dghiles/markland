"""Plan 7: grant() uses the dispatcher to enqueue templated emails.

Covers user_grant (new), user_grant_level_changed (re-grant with different level),
agent_grant (user-owned agent), and no-email for service-owned agents.
"""

from __future__ import annotations

import pytest

from markland.db import init_db
from markland.service import agents as agents_svc
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.auth import Principal


BASE = "https://markland.test"


class _FakeDispatcher:
    def __init__(self):
        self.enqueued: list[dict] = []

    def enqueue(self, to, subject, html, text=None, metadata=None):
        self.enqueued.append({
            "to": to, "subject": subject, "html": html,
            "text": text, "metadata": metadata,
        })


def _user(uid: str, *, display_name: str | None = None, email: str | None = None) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=display_name,
        is_admin=False,
        user_id=uid,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", BASE)
    from markland.config import reset_config
    reset_config()
    yield tmp_path
    reset_config()


def _seed(conn, owner: Principal, *, email_by_uid: dict[str, str]) -> str:
    for uid, email in email_by_uid.items():
        conn.execute(
            "INSERT OR IGNORE INTO users (id, email, display_name, created_at) "
            "VALUES (?, ?, ?, '2026-01-01')",
            (uid, email, "Name_" + uid),
        )
    conn.commit()
    return docs_svc.publish(conn, BASE, owner, "body", title="Quarterly plan")["id"]


def test_grant_enqueues_user_grant_email(env):
    conn = init_db(env / "t.db")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, bob,
        email_by_uid={"usr_bob": "bob@example.com", "usr_alice": "alice@example.com"},
    )
    disp = _FakeDispatcher()
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=bob,
        doc_id=doc_id,
        target="alice@example.com",
        level="view",
        dispatcher=disp,
    )
    assert len(disp.enqueued) == 1
    item = disp.enqueued[0]
    assert item["to"] == "alice@example.com"
    assert "view access" in item["subject"]
    assert item["metadata"]["template"] == "user_grant"
    assert item["metadata"]["doc_id"] == doc_id
    # Plaintext must exist.
    assert item["text"] and "Quarterly plan" in item["text"]


def test_grant_survives_dispatcher_enqueue_raising(env):
    conn = init_db(env / "t.db")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, bob,
        email_by_uid={"usr_bob": "bob@example.com", "usr_alice": "alice@example.com"},
    )

    class _Bad:
        def enqueue(self, *a, **kw):
            raise RuntimeError("queue broken")

    # Should NOT propagate.
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=bob,
        doc_id=doc_id,
        target="alice@example.com",
        level="view",
        dispatcher=_Bad(),
    )
    row = conn.execute(
        "SELECT level FROM grants WHERE doc_id=? AND principal_id='usr_alice'",
        (doc_id,),
    ).fetchone()
    assert row is not None and row[0] == "view"


def test_regrant_with_different_level_enqueues_level_changed(env):
    conn = init_db(env / "t.db")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, bob,
        email_by_uid={"usr_bob": "bob@example.com", "usr_alice": "alice@example.com"},
    )
    disp = _FakeDispatcher()
    grants_svc.grant(
        conn, base_url=BASE, principal=bob, doc_id=doc_id,
        target="alice@example.com", level="view", dispatcher=disp,
    )
    grants_svc.grant(
        conn, base_url=BASE, principal=bob, doc_id=doc_id,
        target="alice@example.com", level="edit", dispatcher=disp,
    )
    assert len(disp.enqueued) == 2
    assert disp.enqueued[0]["metadata"]["template"] == "user_grant"
    assert disp.enqueued[1]["metadata"]["template"] == "user_grant_level_changed"
    assert disp.enqueued[1]["subject"].endswith('to edit.')


def test_regrant_with_same_level_does_not_reemit(env):
    conn = init_db(env / "t.db")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, bob,
        email_by_uid={"usr_bob": "bob@example.com", "usr_alice": "alice@example.com"},
    )
    disp = _FakeDispatcher()
    grants_svc.grant(
        conn, base_url=BASE, principal=bob, doc_id=doc_id,
        target="alice@example.com", level="view", dispatcher=disp,
    )
    grants_svc.grant(
        conn, base_url=BASE, principal=bob, doc_id=doc_id,
        target="alice@example.com", level="view", dispatcher=disp,
    )
    assert len(disp.enqueued) == 1


def test_grant_to_user_owned_agent_emails_owning_user(env):
    conn = init_db(env / "t.db")
    bob = _user("usr_bob")
    doc_id = _seed(
        conn, bob,
        email_by_uid={"usr_bob": "bob@example.com", "usr_alice": "alice@example.com"},
    )
    # Alice owns an agent.
    agent = agents_svc.create_agent(
        conn, owner_user_id="usr_alice", display_name="alice-bot",
    )
    disp = _FakeDispatcher()
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=bob,
        doc_id=doc_id,
        target=agent.id,
        level="edit",
        dispatcher=disp,
    )
    assert len(disp.enqueued) == 1
    item = disp.enqueued[0]
    assert item["to"] == "alice@example.com"
    assert item["metadata"]["template"] == "agent_grant"
    assert agent.id in item["html"]
    assert "alice-bot" in item["html"]


def test_grant_to_service_owned_agent_sends_no_email(env):
    conn = init_db(env / "t.db")
    bob = _user("usr_bob")
    doc_id = _seed(conn, bob, email_by_uid={"usr_bob": "bob@example.com"})
    agent = agents_svc.create_service_agent(conn, "svc_test", "svc")
    disp = _FakeDispatcher()
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=bob,
        doc_id=doc_id,
        target=agent.id,
        level="view",
        dispatcher=disp,
    )
    assert disp.enqueued == []
