"""Layer C — axis 1: parameter-naming invariants."""

import pytest
from markland.server import build_mcp


@pytest.fixture
def mcp(tmp_path):
    from markland.db import init_db
    db = init_db(tmp_path / "t.db")
    return build_mcp(db, base_url="http://x", email_client=None)


def test_grant_uses_target_param(mcp):
    tool = mcp._tool_manager.get_tool("markland_grant")
    sig_params = list(tool.parameters.get("properties", {}).keys())
    assert "target" in sig_params, sig_params
    # `principal` is also accepted as a deprecated alias. FastMCP's pydantic
    # schema generator treats keyword-only params identically to positional
    # ones, so `principal` still appears in `properties`. Clients should
    # prefer `target`; the alias is removed in Phase B (plan 7).


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
