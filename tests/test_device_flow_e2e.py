"""End-to-end device flow: Claude Code + browser working against a live app.

A single TestClient plays both roles. Verifies that after the flow the issued
access_token actually authenticates against /mcp, and that `?invite=<token>`
piggybacks invite acceptance.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import sessions as sessions_mod
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "e2e-session-secret"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    db_path: Path = tmp_path / "e2e.db"
    conn = init_db(db_path)
    # Seed Alice.
    alice = create_user(conn, email="alice@example.com", display_name="Alice")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        yield {"client": c, "db_path": db_path, "alice_id": alice.id, "conn": conn}


def _extract_csrf(html: str) -> str:
    import re
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m
    return m.group(1)


def test_full_happy_path(ctx):
    client = ctx["client"]
    alice_id = ctx["alice_id"]

    # --- Claude Code: start
    start = client.post("/api/auth/device-start").json()
    assert start["user_code"].count("-") == 1
    device_code = start["device_code"]

    # --- Claude Code: first poll -> pending
    first = client.post("/api/auth/device-poll", json={"device_code": device_code}).json()
    assert first == {"status": "pending"}

    # --- Browser: user logs in, hits /device, confirms.
    client.cookies.set(
        sessions_mod.SESSION_COOKIE_NAME,
        sessions_mod.make_session_cookie_value(alice_id, secret=SECRET),
    )
    page = client.get(f"/device?code={start['user_code']}")
    csrf = _extract_csrf(page.text)
    confirm = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert confirm.status_code == 303

    # --- Claude Code: drop the browser cookie, poll again (after slow_down window).
    client.cookies.clear()
    time.sleep(6)
    authorized = client.post(
        "/api/auth/device-poll", json={"device_code": device_code}
    ).json()
    assert authorized["status"] == "authorized"
    token = authorized["access_token"]
    assert token.startswith("mk_usr_")

    # --- Claude Code: use the token against the MCP surface.
    r = client.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "e2e", "version": "0"},
            },
        },
    )
    assert r.status_code == 200

    # --- Second poll with the same device_code now returns expired (single-use).
    time.sleep(6)
    repeat = client.post(
        "/api/auth/device-poll", json={"device_code": device_code}
    ).json()
    assert repeat["status"] == "expired"


def test_invite_piggyback(ctx):
    """Happy path for `?invite=<token>` → grant on the invited doc."""
    client = ctx["client"]
    db_path: Path = ctx["db_path"]
    alice_id = ctx["alice_id"]

    # Seed Bob + a doc Bob owns + an invite he creates for Alice.
    conn = sqlite3.connect(str(db_path))
    try:
        from markland.models import Document
        from markland.service.invites import create_invite
        from markland.service.users import create_user as _create_user

        bob = _create_user(conn, email="bob@example.com", display_name="Bob")
        doc_id = Document.generate_id()
        share_token = Document.generate_share_token()
        from markland.db import insert_document
        insert_document(
            conn, doc_id, "Bob's doc", "# hello", share_token,
            is_public=False, owner_id=bob.id,
        )
        created = create_invite(
            conn,
            doc_id=doc_id,
            created_by_user_id=bob.id,
            level="edit",
            base_url="https://markland.dev",
            single_use=True,
            expires_in_days=7,
        )
        conn.commit()
    finally:
        conn.close()

    # Extract the plaintext token from the invite URL.
    invite_token = created.url.rsplit("/", 1)[-1]

    # --- Claude Code: start with invite_token
    start = client.post(
        "/api/auth/device-start", json={"invite_token": invite_token}
    ).json()

    # --- Browser: Alice logs in, authorizes the code
    client.cookies.set(
        sessions_mod.SESSION_COOKIE_NAME,
        sessions_mod.make_session_cookie_value(alice_id, secret=SECRET),
    )
    page = client.get(f"/device?code={start['user_code']}")
    assert "invite" in page.text.lower()
    csrf = _extract_csrf(page.text)
    confirm = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert confirm.status_code == 303

    # --- Claude Code: poll -> authorized with token
    client.cookies.clear()
    time.sleep(6)
    out = client.post(
        "/api/auth/device-poll", json={"device_code": start["device_code"]}
    ).json()
    assert out["status"] == "authorized"
    assert out["access_token"].startswith("mk_usr_")

    # --- Grant now exists for Alice on Bob's doc.
    conn2 = sqlite3.connect(str(db_path))
    try:
        row = conn2.execute(
            "SELECT level FROM grants WHERE doc_id = ? AND principal_id = ?",
            (doc_id, alice_id),
        ).fetchone()
    finally:
        conn2.close()
    assert row is not None
    assert row[0] == "edit"


def test_invite_piggyback_degrades_gracefully_when_invite_expired(ctx):
    """If the invite cannot be accepted, authorization still completes."""
    client = ctx["client"]
    db_path: Path = ctx["db_path"]
    alice_id = ctx["alice_id"]

    conn = sqlite3.connect(str(db_path))
    try:
        from markland.models import Document
        from markland.service.invites import create_invite
        from markland.service.users import create_user as _create_user
        from markland.db import insert_document

        bob = _create_user(conn, email="bob@example.com", display_name="Bob")
        doc_id = Document.generate_id()
        share_token = Document.generate_share_token()
        insert_document(
            conn, doc_id, "Bob's doc", "# hello", share_token,
            is_public=False, owner_id=bob.id,
        )
        created = create_invite(
            conn,
            doc_id=doc_id,
            created_by_user_id=bob.id,
            level="edit",
            base_url="https://markland.dev",
            single_use=True,
            expires_in_days=7,
        )
        invite_token = created.url.rsplit("/", 1)[-1]
        # Force-revoke the invite so accept_invite returns None.
        conn.execute(
            "UPDATE invites SET revoked_at = ? WHERE id = ?",
            ("2020-01-01T00:00:00+00:00", created.id),
        )
        conn.commit()
    finally:
        conn.close()

    start = client.post(
        "/api/auth/device-start", json={"invite_token": invite_token}
    ).json()

    client.cookies.set(
        sessions_mod.SESSION_COOKIE_NAME,
        sessions_mod.make_session_cookie_value(alice_id, secret=SECRET),
    )
    page = client.get(f"/device?code={start['user_code']}")
    csrf = _extract_csrf(page.text)
    confirm = client.post(
        "/device/confirm",
        data={"user_code": start["user_code"], "csrf": csrf},
        follow_redirects=False,
    )
    assert confirm.status_code == 303
    # The redirect URL carries the invite_error — surfaced on /device/done.
    assert "invite_error" in confirm.headers["location"]

    client.cookies.clear()
    time.sleep(6)
    out = client.post(
        "/api/auth/device-poll", json={"device_code": start["device_code"]}
    ).json()
    assert out["status"] == "authorized"
    assert out["access_token"].startswith("mk_usr_")
