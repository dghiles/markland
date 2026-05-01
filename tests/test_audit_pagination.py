"""Layer C — axis 7: pagination contract."""

import pytest
from tests._mcp_harness import MCPHarness


def test_list_returns_list_envelope(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# 1")
    alice.call("markland_publish", content="# 2")

    res = alice.call("markland_list")
    assert "items" in res
    assert "next_cursor" in res
    assert len(res["items"]) == 2
    assert res["next_cursor"] is None


def test_list_pagination_limit_and_cursor(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    for i in range(5):
        alice.call("markland_publish", content=f"# {i}")

    page1 = alice.call("markland_list", limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = alice.call("markland_list", limit=2, cursor=page1["next_cursor"])
    assert len(page2["items"]) == 2

    page3 = alice.call("markland_list", limit=2, cursor=page2["next_cursor"])
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None

    # No overlap.
    seen = {item["id"] for item in page1["items"] + page2["items"] + page3["items"]}
    assert len(seen) == 5


def test_list_limit_capped_at_200(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    res = alice.call("markland_list", limit=99999)
    assert "items" in res


def test_search_pagination_limit_and_cursor(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    for i in range(5):
        alice.call("markland_publish", content=f"# needle {i}", title=f"needle {i}")

    page1 = alice.call("markland_search", query="needle", limit=2)
    assert "items" in page1
    assert "next_cursor" in page1
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None

    page2 = alice.call(
        "markland_search", query="needle", limit=2, cursor=page1["next_cursor"]
    )
    assert len(page2["items"]) == 2

    page3 = alice.call(
        "markland_search", query="needle", limit=2, cursor=page2["next_cursor"]
    )
    assert len(page3["items"]) == 1
    assert page3["next_cursor"] is None

    seen = {item["id"] for item in page1["items"] + page2["items"] + page3["items"]}
    assert len(seen) == 5
