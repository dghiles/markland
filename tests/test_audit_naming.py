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
    # `principal` is also accepted as deprecated alias — but not advertised in the schema.
