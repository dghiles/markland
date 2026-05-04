"""P3 / markland-vw2: silent-invite path dedupes by (doc_id, target_email).

When a doc owner re-grants the same unknown email, `_grant_via_invite`
must reuse the existing active invite instead of creating an orphan
row. The response shape and values stay identical so the caller can't
distinguish first-grant from re-grant (which is itself a leak the
indistinguishability fix tries to prevent).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service import grants as grants_svc
from markland.service.auth import Principal


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def _fresh_db(tmp_path):
    return init_db(tmp_path / "t.db")


def _seed_doc(conn, owner: Principal) -> str:
    conn.execute(
        "INSERT OR IGNORE INTO users (id, email, created_at) "
        "VALUES (?, ?, '2026-01-01')",
        (owner.principal_id, "a@x"),
    )
    conn.commit()
    return docs_svc.publish(conn, BASE, owner, "body", title="T")["id"]


def _count_invites(conn, doc_id: str) -> int:
    return conn.execute(
        "SELECT COUNT(*) FROM invites WHERE doc_id = ?", (doc_id,)
    ).fetchone()[0]


def test_regrant_unknown_email_dedupes_invite(tmp_path):
    """Two grants for the same unknown email -> one invite row, identical
    responses. Idempotent like a real grant upsert."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed_doc(conn, alice)

    r1 = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )
    r2 = grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )

    assert _count_invites(conn, doc_id) == 1, (
        "second grant must reuse the existing invite, not create an orphan"
    )
    # Caller-visible response is identical between calls (same shape and
    # same synthetic principal_id; granted_at is "now" in both).
    assert r1["principal_id"] == r2["principal_id"]
    assert r1["doc_id"] == r2["doc_id"]
    assert r1["level"] == r2["level"]


def test_grants_to_different_emails_create_separate_invites(tmp_path):
    """Different emails -> different invite rows. Dedup must be scoped to
    the (doc_id, target_email) pair, not just doc_id."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed_doc(conn, alice)

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="a-stranger@x",
        level="view",
        email_client=MagicMock(),
    )
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="b-stranger@x",
        level="view",
        email_client=MagicMock(),
    )

    assert _count_invites(conn, doc_id) == 2


def test_regrant_after_revoke_creates_fresh_invite(tmp_path):
    """If the existing invite is revoked, a re-grant must create a new
    one — revoked invites must not satisfy the dedup lookup."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed_doc(conn, alice)

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )
    # Revoke the only invite row directly (mirrors the invite-revoke path).
    conn.execute(
        "UPDATE invites SET revoked_at = ? WHERE doc_id = ?",
        ("2026-05-04T00:00:00+00:00", doc_id),
    )
    conn.commit()

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )

    # Two rows now: one revoked, one active.
    assert _count_invites(conn, doc_id) == 2
    active = conn.execute(
        "SELECT COUNT(*) FROM invites WHERE doc_id = ? AND revoked_at IS NULL",
        (doc_id,),
    ).fetchone()[0]
    assert active == 1


def test_regrant_after_expiry_creates_fresh_invite(tmp_path):
    """An expired invite must not satisfy the dedup lookup either."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed_doc(conn, alice)

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )
    # Force the existing invite into the past.
    conn.execute(
        "UPDATE invites SET expires_at = ? WHERE doc_id = ?",
        ("2020-01-01T00:00:00+00:00", doc_id),
    )
    conn.commit()

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )

    assert _count_invites(conn, doc_id) == 2


def test_dedup_lookup_is_case_insensitive_on_email(tmp_path):
    """Emails are case-insensitive; granting `Nobody@X` after `nobody@x`
    must dedupe — otherwise an attacker could probe for the exact case
    by counting rows."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed_doc(conn, alice)

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=MagicMock(),
    )
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="Nobody@X",
        level="view",
        email_client=MagicMock(),
    )

    assert _count_invites(conn, doc_id) == 1


def test_dedup_skips_email_resend(tmp_path):
    """Reusing an existing invite must NOT re-enqueue the invitation
    email — the recipient should not be spammed on every retry, and
    we no longer hold the plaintext token to regenerate the URL anyway."""
    conn = _fresh_db(tmp_path)
    alice = _user("usr_alice")
    doc_id = _seed_doc(conn, alice)

    client = MagicMock()
    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=client,
    )
    assert client.send.call_count == 1

    grants_svc.grant(
        conn,
        base_url=BASE,
        principal=alice,
        doc_id=doc_id,
        target="nobody@x",
        level="view",
        email_client=client,
    )
    # Still 1 — second call deduped.
    assert client.send.call_count == 1
