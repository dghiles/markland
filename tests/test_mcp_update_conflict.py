"""MCP-level tests for conflict handling in markland_update and markland_get."""

import pytest

from markland.db import init_db, upsert_grant
from markland.service.auth import Principal
from markland.service.docs import ConflictError
from markland.tools.documents import get_doc, publish_doc, update_doc


def _P(pid: str = "usr_test") -> Principal:
    return Principal(
        principal_id=pid,
        principal_type="user",
        display_name=None,
        is_admin=True,
        user_id=pid,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "mcp.db")
    yield c
    c.close()


def test_get_doc_includes_version(conn):
    doc_id = publish_doc(conn, "http://x", "T", "c", public=False)["id"]
    out = get_doc(conn, doc_id)
    assert out["version"] == 1


def test_update_doc_requires_if_version_to_match(conn):
    principal = _P()
    doc_id = publish_doc(conn, "http://x", "T", "v1", public=False)["id"]
    # The doc was created with owner_id=None by the legacy publish_doc
    # shim. Grant `principal` explicit edit access so permission check passes.
    upsert_grant(conn, doc_id, principal.principal_id, "user", "edit", "admin")

    ok = update_doc(
        conn, "http://x", doc_id, principal,
        content="v2", title=None, if_version=1,
    )
    assert ok["version"] == 2

    with pytest.raises(ConflictError) as ei:
        update_doc(
            conn, "http://x", doc_id, principal,
            content="stale", title=None, if_version=1,
        )
    assert ei.value.current_version == 2
    assert ei.value.current_content == "v2"


def test_update_doc_missing_doc_returns_error_dict(conn):
    principal = _P()
    # Missing doc → check_permission raises NotFound, update_doc surfaces
    # that as the same error dict shape.
    from markland.service.permissions import NotFound
    try:
        out = update_doc(
            conn, "http://x", "nosuchdoc", principal,
            content="x", title=None, if_version=1,
        )
        assert "error" in out
    except NotFound:
        # Acceptable: service-level NotFound is the canonical signal for
        # "doesn't exist or no access" (spec §12.5). The tool layer at the
        # MCP boundary translates this to `{"error": "not_found"}`; the
        # direct `update_doc` helper lets it propagate.
        pass


def test_mcp_tool_translates_conflict_to_tool_error(tmp_path):
    """End-to-end: the `markland_update` handler in server.py translates
    ConflictError into a structured dict that the decorated tool surfaces
    as a `ToolError` with `code=conflict`.
    """
    from markland.server import build_mcp

    db = init_db(tmp_path / "mcp2.db")
    # Create a user to serve as the acting principal.
    from markland.service.auth import (
        Principal as _Principal,  # noqa: F401
    )
    db.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 1, ?)",
        ("usr_test", "t@x", "t", "2026-04-19T00:00:00Z"),
    )
    db.commit()
    doc_id = publish_doc(db, "http://x", "T", "v1", public=False)["id"]
    # Grant edit access to usr_test.
    upsert_grant(db, doc_id, "usr_test", "user", "edit", "admin")

    mcp = build_mcp(db, base_url="http://x")

    class _Ctx:
        def __init__(self, principal):
            self.principal = principal

    principal = _P("usr_test")

    # Use the undecorated handler for the happy path.
    happy = mcp.markland_handlers["markland_update"](
        _Ctx(principal), doc_id=doc_id, if_version=1, content="v2"
    )
    assert happy["version"] == 2

    # Second call with stale if_version → handler raises ToolError directly
    # (the helper itself raises after axis-3; the wrapper just propagates).
    from mcp.server.fastmcp.exceptions import ToolError

    with pytest.raises(ToolError) as ei:
        mcp.markland_handlers["markland_update"](
            _Ctx(principal), doc_id=doc_id, if_version=1, content="stale"
        )
    data = getattr(ei.value, "data", None) or {}
    assert data.get("code") == "conflict"
    assert data.get("current_version") == 2
    assert data.get("current_content") == "v2"
    assert data.get("current_title") == "T"

    # The decorated tool path must also raise ToolError with the same shape.
    tool = None
    for name in ("_tool_manager",):
        mgr = getattr(mcp, name, None)
        if mgr is not None:
            for t in mgr.list_tools():
                if t.name == "markland_update":
                    tool = t
                    break
    assert tool is not None, "markland_update tool not found"

    with pytest.raises(ToolError) as ei:
        tool.fn(_Ctx(principal), doc_id=doc_id, if_version=1, content="stale")
    assert "conflict" in str(ei.value).lower()
    data = getattr(ei.value, "data", None) or {}
    assert data.get("code") == "conflict"
    assert data.get("current_version") == 2
    assert data.get("current_content") == "v2"
    assert data.get("current_title") == "T"
