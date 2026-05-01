"""Layer C — axis 5: new tools."""

import pytest
from tests._mcp_harness import MCPHarness


def test_get_by_share_token_public(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Public", public=True)

    # Fetch share_token from the share_url (last segment).
    share_token = pub["share_url"].rsplit("/", 1)[-1]

    # Anonymous read of public doc by share_token works.
    res = h.anon().call("markland_get_by_share_token", share_token=share_token)
    assert res["id"] == pub["id"]
    assert res["title"] == pub["title"]


def test_get_by_share_token_private_not_found(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Private", public=False)
    share_token = pub["share_url"].rsplit("/", 1)[-1]

    # Anonymous read of a non-public doc → not_found (deny-as-not-found).
    r = h.anon().call_raw("markland_get_by_share_token", share_token=share_token)
    r.assert_error("not_found")


def test_get_by_share_token_unknown(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    r = h.anon().call_raw(
        "markland_get_by_share_token", share_token="not_a_real_token",
    )
    r.assert_error("not_found")
