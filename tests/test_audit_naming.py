"""Layer C — axis 1: parameter-naming invariants."""

import pytest
from markland.server import build_mcp
from tests._mcp_harness import MCPHarness


@pytest.fixture
def mcp(tmp_path):
    from markland.db import init_db
    db = init_db(tmp_path / "t.db")
    return build_mcp(db, base_url="http://x", email_client=None)


def test_grant_uses_target_param(mcp):
    tool = mcp._tool_manager.get_tool("markland_grant")
    sig_params = list(tool.parameters.get("properties", {}).keys())
    assert "target" in sig_params, sig_params


def test_boolean_inputs_drop_is_prefix(mcp):
    """Per §8.1: boolean inputs use bare names (public, featured, single_use);
    boolean outputs keep is_ prefix (is_public, is_featured)."""
    forbidden_input_names = {"is_public", "is_featured", "is_single_use"}

    for name in mcp.markland_handlers:
        tool = mcp._tool_manager.get_tool(name)
        params = tool.parameters.get("properties", {})
        for pname in params:
            assert pname not in forbidden_input_names, (
                f"{name} uses {pname} as input; per §8.1 use bare name."
            )


def test_deprecated_shims_removed_in_phase_b(mcp):
    """Phase B: the four folded predecessors no longer exist."""
    assert "markland_set_visibility" not in mcp.markland_handlers
    assert "markland_feature" not in mcp.markland_handlers
    assert "markland_set_status" not in mcp.markland_handlers
    assert "markland_clear_status" not in mcp.markland_handlers


def test_grant_no_longer_accepts_principal_kwarg(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")

    # `target` works (canonical).
    alice.call("markland_grant", doc_id=pub["id"],
               target="bob@example.com", level="view")

    # `principal` no longer works — should produce a TypeError or invalid_argument.
    with pytest.raises((TypeError, Exception)):
        alice.call("markland_grant", doc_id=pub["id"],
                   principal="bob@example.com", level="view")
