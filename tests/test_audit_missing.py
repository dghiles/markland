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


def test_list_invites_owner_view(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    inv1 = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="view",
    )
    inv2 = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="edit",
        single_use=False, expires_in_days=7,
    )

    res = alice.call("markland_list_invites", doc_id=pub["id"])
    assert "items" in res
    assert "next_cursor" in res
    assert len(res["items"]) == 2
    ids = {item["invite_id"] for item in res["items"]}
    assert ids == {inv1["invite_id"], inv2["invite_id"]}
    # Must NOT include plaintext token.
    for item in res["items"]:
        assert "url" not in item or "mk_inv_" not in item.get("url", "")


def test_list_invites_non_owner_forbidden(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")
    alice.call("markland_create_invite", doc_id=pub["id"], level="view")

    r = bob.call_raw("markland_list_invites", doc_id=pub["id"])
    r.assert_error("not_found")  # deny-as-not-found
