"""Integration: service-layer calls must write audit rows."""

from __future__ import annotations

import sqlite3

import pytest

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service import invites as invites_svc
from markland.service.auth import Principal
from markland.service.email import EmailClient


class _NoopEmail(EmailClient):
    def __init__(self) -> None:
        super().__init__(api_key="", from_email="test@m.dev")


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


@pytest.fixture
def alice(conn: sqlite3.Connection) -> Principal:
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-04-19T00:00:00Z')"
    )
    conn.commit()
    return Principal(
        principal_id="usr_alice",
        principal_type="user",
        display_name="Alice",
        is_admin=False,
        user_id="usr_alice",
    )


@pytest.fixture
def bob(conn: sqlite3.Connection) -> Principal:
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', 0, '2026-04-19T00:00:00Z')"
    )
    conn.commit()
    return Principal(
        principal_id="usr_bob",
        principal_type="user",
        display_name="Bob",
        is_admin=False,
        user_id="usr_bob",
    )


def _audit_rows(conn: sqlite3.Connection) -> list[tuple]:
    return conn.execute(
        "SELECT action, doc_id, principal_id FROM audit_log ORDER BY id"
    ).fetchall()


def test_publish_writes_audit_row(conn, alice):
    result = docs_svc.publish_doc(
        conn,
        base_url="https://markland.dev",
        principal=alice,
        title="Hello",
        content="# Hi",
    )
    rows = _audit_rows(conn)
    assert len(rows) == 1
    assert rows[0][0] == "publish"
    assert rows[0][1] == result["id"]
    assert rows[0][2] == "usr_alice"


def test_update_writes_audit_row(conn, alice):
    result = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    doc = docs_svc.get_doc(conn, principal=alice, doc_id=result["id"])
    docs_svc.update_doc(
        conn,
        principal=alice,
        doc_id=result["id"],
        content="c2",
        if_version=doc.version,
    )
    rows = _audit_rows(conn)
    assert [r[0] for r in rows] == ["publish", "update"]


def test_delete_writes_audit_row(conn, alice):
    result = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    docs_svc.delete_doc(conn, principal=alice, doc_id=result["id"])
    rows = _audit_rows(conn)
    assert [r[0] for r in rows] == ["publish", "delete"]


def test_grant_writes_audit_row(conn, alice, bob):
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    grants_svc.grant(
        conn,
        base_url="x",
        principal=alice,
        doc_id=doc["id"],
        target="bob@example.com",
        level="view",
        email_client=_NoopEmail(),
    )
    actions = [r[0] for r in _audit_rows(conn)]
    assert actions == ["publish", "grant"]


def test_revoke_writes_audit_row(conn, alice, bob):
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    grants_svc.grant(
        conn,
        base_url="x",
        principal=alice,
        doc_id=doc["id"],
        target="bob@example.com",
        level="view",
        email_client=_NoopEmail(),
    )
    grants_svc.revoke(
        conn, principal=alice, doc_id=doc["id"], principal_id="usr_bob"
    )
    actions = [r[0] for r in _audit_rows(conn)]
    assert actions == ["publish", "grant", "revoke"]


def test_invite_create_and_accept_write_audit_rows(conn, alice, bob):
    doc = docs_svc.publish_doc(
        conn, base_url="x", principal=alice, title="t", content="c"
    )
    created = invites_svc.create_invite(
        conn,
        doc_id=doc["id"],
        created_by_user_id="usr_alice",
        level="view",
        base_url="http://m",
    )
    # Extract plaintext token from URL.
    token = created.url.rsplit("/", 1)[-1]
    invites_svc.accept_invite(conn, invite_token=token, user_id="usr_bob")
    actions = [r[0] for r in _audit_rows(conn)]
    assert actions == ["publish", "invite_create", "invite_accept"]
