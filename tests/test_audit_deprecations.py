"""Layer C — deprecation parity tests.

For every renamed/folded tool, both old and new shapes must produce the same
result for the same args. Tests are deleted in Phase B when the deprecation
window closes.
"""

import pytest
from tests._mcp_harness import MCPHarness


def test_grant_principal_kw_still_works_as_target_alias(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# share")

    new_call = alice.call(
        "markland_grant", doc_id=pub["id"], target="bob@example.com", level="view"
    )

    pub2 = alice.call("markland_publish", content="# share-2")
    old_call = alice.call(
        "markland_grant", doc_id=pub2["id"], principal="bob@example.com", level="view"
    )

    assert new_call["doc_id"] == pub["id"]
    assert old_call["doc_id"] == pub2["id"]
    assert set(new_call) == set(old_call)


def test_set_visibility_shim_delegates_to_doc_meta(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    new = alice.call("markland_doc_meta", doc_id=pub["id"], public=True)
    old = alice.call("markland_set_visibility", doc_id=pub["id"], public=False)

    assert new["is_public"] is True
    assert old["is_public"] is False
    # Both return doc_envelope shape.
    assert set(new) == set(old)


def test_feature_shim_delegates_to_doc_meta(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    admin = h.as_admin()
    pub = admin.call("markland_publish", content="# t")

    old = admin.call("markland_feature", doc_id=pub["id"], featured=True)
    assert old["is_featured"] is True


def test_set_visibility_shim_marked_deprecated_in_docstring(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    desc = mcp._tool_manager.get_tool("markland_set_visibility").description
    assert "Deprecated" in desc
    assert "markland_doc_meta" in desc


def test_feature_shim_marked_deprecated(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    desc = mcp._tool_manager.get_tool("markland_feature").description
    assert "Deprecated" in desc


def test_set_status_shim_delegates(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    res = alice.call("markland_set_status", doc_id=pub["id"], status="reading")
    assert res["status"] == "reading"


def test_clear_status_shim_delegates(tmp_path):
    # Plan-C.5 restored the legacy {ok: true} shape; the shim still
    # delegates to _status under the hood, just with a translated
    # response so existing callers don't break before the 30-day
    # removal deadline.
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_set_status", doc_id=pub["id"], status="reading")
    res = alice.call("markland_clear_status", doc_id=pub["id"])
    assert res == {"ok": True}


def test_set_status_marked_deprecated(tmp_path):
    from markland.db import init_db
    from markland.server import build_mcp
    db = init_db(tmp_path / "t.db")
    mcp = build_mcp(db, base_url="http://x", email_client=None)
    desc = mcp._tool_manager.get_tool("markland_set_status").description
    assert "Deprecated" in desc
    assert "markland_status" in desc


def test_set_status_shim_rejects_none(tmp_path):
    """Plan-C.4: the deprecated set_status shim's signature says
    status: str (not str | None). Passing None should surface as
    invalid_argument matching the docstring contract — not silently
    clear the presence."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    r = alice.call_raw("markland_set_status", doc_id=pub["id"], status=None)
    r.assert_error("invalid_argument")


def test_clear_status_shim_returns_legacy_ok_true_shape(tmp_path):
    """Plan-C.5: the deprecated clear_status shim must preserve its
    pre-deprecation response shape {ok: true} so existing callers
    don't break before the 30-day removal deadline."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_set_status", doc_id=pub["id"], status="reading")

    res = alice.call("markland_clear_status", doc_id=pub["id"])
    assert res == {"ok": True}, (
        f"shim returned {res!r}; expected legacy {{'ok': True}} until "
        "the deprecation window closes"
    )
