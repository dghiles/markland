"""Test the Invite dataclass."""

from markland.models import Invite


def test_invite_generate_id_has_inv_prefix():
    iid = Invite.generate_id()
    assert iid.startswith("inv_")
    # 16 hex chars after the prefix
    assert len(iid) == 4 + 16


def test_invite_generate_token_is_urlsafe_and_long():
    t = Invite.generate_token()
    # Format: mk_inv_<urlsafe32> — urlsafe32 is ~43 chars
    assert t.startswith("mk_inv_")
    assert len(t) >= len("mk_inv_") + 40


def test_invite_dataclass_roundtrip():
    inv = Invite(
        id="inv_deadbeefdeadbeef",
        token_hash="hash",
        doc_id="doc_1",
        level="view",
        single_use=True,
        uses_remaining=1,
        created_by="usr_a",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at=None,
        revoked_at=None,
    )
    assert inv.id == "inv_deadbeefdeadbeef"
    assert inv.level == "view"
    assert inv.single_use is True
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is True


def test_invite_is_active_expired():
    inv = Invite(
        id="inv_x",
        token_hash="h",
        doc_id="d",
        level="view",
        single_use=True,
        uses_remaining=1,
        created_by="u",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at="2026-04-19T00:30:00+00:00",
        revoked_at=None,
    )
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is False


def test_invite_is_active_used_up():
    inv = Invite(
        id="inv_x",
        token_hash="h",
        doc_id="d",
        level="view",
        single_use=True,
        uses_remaining=0,
        created_by="u",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at=None,
        revoked_at=None,
    )
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is False


def test_invite_is_active_revoked():
    inv = Invite(
        id="inv_x",
        token_hash="h",
        doc_id="d",
        level="view",
        single_use=True,
        uses_remaining=1,
        created_by="u",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at=None,
        revoked_at="2026-04-19T00:10:00+00:00",
    )
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is False
