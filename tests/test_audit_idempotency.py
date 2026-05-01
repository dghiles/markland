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


IDEMPOTENT_TOOLS = {
    "markland_doc_meta",
    "markland_grant",
    "markland_revoke",
    "markland_status",
    "markland_revoke_invite",
    # Deprecated shims still idempotent because they delegate.
    "markland_set_visibility",
    "markland_feature",
    "markland_set_status",
    "markland_clear_status",
}

NOT_IDEMPOTENT_TOOLS = {
    "markland_publish",
    "markland_update",
    "markland_delete",
    "markland_create_invite",
}

READ_ONLY_TOOLS = {
    "markland_whoami",
    "markland_list",
    "markland_get",
    "markland_search",
    "markland_share",
    "markland_list_grants",
    "markland_list_my_agents",
    "markland_audit",
    "markland_admin_metrics",
}


def test_every_tool_has_idempotency_section_in_docstring(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    for name in IDEMPOTENT_TOOLS | NOT_IDEMPOTENT_TOOLS | READ_ONLY_TOOLS:
        desc = mcp._tool_manager.get_tool(name).description or ""
        assert "Idempotency:" in desc, f"{name} missing Idempotency: line"


def test_idempotency_catalog_covers_all_current_tools(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    all_known = IDEMPOTENT_TOOLS | NOT_IDEMPOTENT_TOOLS | READ_ONLY_TOOLS
    extras = set(mcp.markland_handlers) - all_known
    # Plan 6 will add 5 new tools; this test should be updated then.
    assert not extras, f"unclassified tools: {extras}"
