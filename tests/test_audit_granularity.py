"""Layer C — axis 4: tool folding (granularity)."""

import pytest
from tests._mcp_harness import MCPHarness


def test_doc_meta_set_public(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    res = alice.call("markland_doc_meta", doc_id=pub["id"], public=True)
    assert res["is_public"] is True
    assert res["id"] == pub["id"]


def test_doc_meta_set_featured_admin_only(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    # Non-admin trying to set featured.
    r = alice.call_raw("markland_doc_meta", doc_id=pub["id"], featured=True)
    r.assert_error("forbidden")

    # Admin can.
    admin = h.as_admin()
    res = admin.call(
        "markland_doc_meta", doc_id=pub["id"], featured=True, public=False,
    )
    assert res["is_featured"] is True


def test_doc_meta_none_leaves_unchanged(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t", public=True)

    # Pass nothing — should be a no-op (idempotent).
    res = alice.call("markland_doc_meta", doc_id=pub["id"])
    assert res["is_public"] is True  # unchanged


def test_status_set_then_clear(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    set_res = alice.call(
        "markland_status", doc_id=pub["id"], status="editing", note="wip",
    )
    assert set_res["status"] == "editing"

    cleared = alice.call("markland_status", doc_id=pub["id"], status=None)
    assert cleared["cleared"] is True


def test_status_invalid_value(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")

    r = alice.call_raw(
        "markland_status", doc_id=pub["id"], status="grilling",
    )
    r.assert_error("invalid_argument")
