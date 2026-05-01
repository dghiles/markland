"""Layer C — axis 8: idempotency contract."""

import pytest
from tests._mcp_harness import MCPHarness


def test_revoke_nonexistent_grant_succeeds(tmp_path):
    """Per spec §8.8: revoke is idempotent — calling on a non-existent grant
    is a no-op success, not not_found."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")

    # Revoke a grant that was never made — should succeed.
    res = alice.call("markland_revoke", doc_id=pub["id"], target="bob@example.com")
    assert res is not None


def test_revoke_invite_nonexistent_succeeds(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    res = alice.call(
        "markland_revoke_invite", invite_id="inv_does_not_exist",
    )
    assert res["revoked"] is True
    assert res["invite_id"] == "inv_does_not_exist"


def test_grant_called_twice_with_same_args_is_noop(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")

    a = alice.call("markland_grant", doc_id=pub["id"],
                   target="bob@example.com", level="view")
    b = alice.call("markland_grant", doc_id=pub["id"],
                   target="bob@example.com", level="view")
    # Both succeed; final state same.
    assert a["doc_id"] == b["doc_id"]


def test_delete_nonexistent_remains_not_found(tmp_path):
    """Per spec §8.8 exception: delete is NOT idempotent."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    r = alice.call_raw("markland_delete", doc_id="doc_does_not_exist")
    r.assert_error("not_found")
