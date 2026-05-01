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


def test_explore_returns_only_public_docs(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    public_doc = alice.call("markland_publish", content="# Public", public=True)
    alice.call("markland_publish", content="# Private", public=False)

    res = h.anon().call("markland_explore")
    items = res["items"]
    ids = {item["id"] for item in items}
    assert public_doc["id"] in ids
    # Private doc not in the list.
    private_titles = [i["title"] for i in items if "Private" in (i["title"] or "")]
    assert private_titles == []


def test_explore_paginates(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    for i in range(5):
        alice.call("markland_publish", content=f"# Doc {i}", public=True)

    page1 = h.anon().call("markland_explore", limit=2)
    assert len(page1["items"]) == 2
    assert page1["next_cursor"] is not None


def test_fork_creates_owned_copy(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    src = alice.call("markland_publish", content="# Original", public=True)

    forked = bob.call("markland_fork", doc_id=src["id"], title="Bob's fork")
    assert forked["owner_id"] == bob.principal_id
    assert forked["id"] != src["id"]
    assert forked["title"] == "Bob's fork"
    assert forked["content"] == src["content"]


def test_fork_inherits_title_when_not_provided(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    src = alice.call("markland_publish", content="# Source", public=True)
    forked = bob.call("markland_fork", doc_id=src["id"])
    assert "Source" in forked["title"]


def test_fork_private_doc_not_found_for_stranger(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    src = alice.call("markland_publish", content="# Private", public=False)
    r = bob.call_raw("markland_fork", doc_id=src["id"])
    r.assert_error("not_found")


def test_revisions_returns_pre_update_snapshots(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# v1")
    upd1 = alice.call(
        "markland_update", doc_id=pub["id"],
        if_version=pub["version"], content="# v2",
    )
    alice.call(
        "markland_update", doc_id=pub["id"],
        if_version=upd1["version"], content="# v3",
    )

    res = alice.call("markland_revisions", doc_id=pub["id"])
    items = res["items"]
    # Two updates -> two pre-update snapshots.
    assert len(items) == 2
    versions = sorted(item["version"] for item in items)
    assert versions == [1, 2]


def test_revisions_forbidden_for_non_viewer(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    bob = h.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# v1")
    r = bob.call_raw("markland_revisions", doc_id=pub["id"])
    r.assert_error("not_found")


def test_fork_self_returns_invalid_argument(tmp_path):
    """Self-fork (alice forks her own doc) should surface as invalid_argument
    with a debuggable reason — not as not_found, which would mask the bug."""
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# mine", public=True)
    r = alice.call_raw("markland_fork", doc_id=pub["id"])
    r.assert_error("invalid_argument")
    assert "cannot_fork_own_doc" in r.error_data.get("reason", "")
