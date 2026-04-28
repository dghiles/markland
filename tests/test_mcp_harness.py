"""Layer A — tests of the MCP test harness itself."""

from __future__ import annotations

from tests._mcp_harness import MCPHarness


def test_harness_create_direct_mode(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    assert h.mode == "direct"
    assert h.db is not None
