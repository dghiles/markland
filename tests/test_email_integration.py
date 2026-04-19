"""End-to-end: service call → dispatcher → EmailClient.send."""

import asyncio
from unittest.mock import MagicMock

import pytest

from markland.config import reset_config
from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.auth import Principal
from markland.service.email import EmailClient, EmailSendError
from markland.service.email_dispatcher import EmailDispatcher


BASE = "https://markland.dev"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", BASE)
    reset_config()
    yield tmp_path
    reset_config()


def _seed(conn):
    conn.execute(
        "INSERT INTO users (id, email, display_name, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', '2026-01-01')"
    )
    conn.commit()
    bob = _user("usr_bob")
    doc_id = docs_svc.publish(conn, BASE, bob, "body", title="Quarterly plan")["id"]
    return bob, doc_id


@pytest.mark.asyncio
async def test_grant_triggers_one_client_send_with_correct_subject(env):
    conn = init_db(env / "t.db")
    bob, doc_id = _seed(conn)

    client = MagicMock(spec=EmailClient)
    client.send = MagicMock(return_value="email_1")
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=bob,
            doc_id=doc_id,
            target="alice@example.com",
            level="view",
            dispatcher=disp,
        )
        await disp.drain()
    finally:
        await disp.stop()

    assert client.send.call_count == 1
    kwargs = client.send.call_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert 'shared "Quarterly plan"' in kwargs["subject"]
    assert "view access" in kwargs["subject"]
    assert kwargs["text"]  # plaintext was sent alongside html
    assert kwargs["html"].startswith("<!DOCTYPE")
    assert kwargs["metadata"]["template"] == "user_grant"


@pytest.mark.asyncio
async def test_grant_succeeds_even_when_client_always_fails(env, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="markland.email_dispatcher")

    conn = init_db(env / "t.db")
    bob, doc_id = _seed(conn)

    client = MagicMock(spec=EmailClient)
    client.send = MagicMock(side_effect=EmailSendError("resend down"))
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        grants_svc.grant(
            conn,
            base_url=BASE,
            principal=bob,
            doc_id=doc_id,
            target="alice@example.com",
            level="edit",
            dispatcher=disp,
        )
        # Wait for retries to complete.
        for _ in range(80):
            await asyncio.sleep(0.02)
            if client.send.call_count >= 4:
                await asyncio.sleep(0.05)
                break
        await disp.drain()
    finally:
        await disp.stop()

    # Grant row persisted regardless of email outcome.
    row = conn.execute(
        "SELECT g.level FROM grants g WHERE g.doc_id=? AND g.principal_id='usr_alice'",
        (doc_id,),
    ).fetchone()
    assert row is not None and row[0] == "edit"

    # 1 initial + 3 retries = 4 attempts, then drop.
    assert client.send.call_count == 4
    assert any("dropping email" in r.message.lower() for r in caplog.records)
