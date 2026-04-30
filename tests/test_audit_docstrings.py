"""Layer C — axis 6: docstring template adherence."""

import pytest
from markland.server import build_mcp


@pytest.fixture
def tools(tmp_path):
    from markland.db import init_db
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    return mcp.markland_handlers, mcp


def test_every_tool_has_args_and_returns_sections(tools):
    handlers, mcp = tools
    for name in handlers:
        tool_obj = mcp._tool_manager.get_tool(name)
        doc = tool_obj.description or ""
        assert "Args:" in doc, f"{name} missing Args: section"
        assert "Returns:" in doc, f"{name} missing Returns: section"
        assert "Idempotency:" in doc, f"{name} missing Idempotency: section"


def test_every_tool_has_one_line_summary(tools):
    handlers, mcp = tools
    for name in handlers:
        tool_obj = mcp._tool_manager.get_tool(name)
        doc = (tool_obj.description or "").strip()
        first_line = doc.split("\n", 1)[0]
        assert len(first_line) <= 100, f"{name} summary too long: {first_line}"
        assert first_line.endswith("."), f"{name} summary not a sentence: {first_line}"
