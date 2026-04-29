"""Layer B — behavior baseline. Snapshot every tool's success and error scenarios.

Update snapshots: `pytest tests/test_mcp_baseline.py --snapshot-update`
"""

from __future__ import annotations

import pytest

from tests._mcp_harness import MCPHarness, as_envelope


def _envelope_of_response(r) -> dict:
    """Wrap a Response in a snapshot-stable envelope."""
    if r.ok:
        return {"kind": "ok", "value": as_envelope(r.value)}
    return {
        "kind": "error",
        "code": r.error_code,
        "data": as_envelope(r.error_data),
    }


def test_baseline_markland_publish_minimal(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_publish", content="# Hello")
    mcp.snapshot("markland_publish", "minimal", _envelope_of_response(r))


def test_baseline_markland_publish_with_title_public(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw(
        "markland_publish",
        content="body",
        title="My Title",
        public=True,
    )
    mcp.snapshot("markland_publish", "with_title_public", _envelope_of_response(r))


def test_baseline_markland_publish_unauthenticated(mcp):
    r = mcp.anon().call_raw("markland_publish", content="x")
    mcp.snapshot("markland_publish", "unauthenticated", _envelope_of_response(r))


def test_baseline_markland_get_owner_view(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Hello")
    r = alice.call_raw("markland_get", doc_id=pub["id"])
    mcp.snapshot("markland_get", "owner_view", _envelope_of_response(r))


def test_baseline_markland_get_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_get", doc_id="doc_does_not_exist")
    mcp.snapshot("markland_get", "not_found", _envelope_of_response(r))


def test_baseline_markland_get_forbidden_hidden_as_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# private")
    r = bob.call_raw("markland_get", doc_id=pub["id"])
    # Per spec §12.5: deny-as-NotFound.
    mcp.snapshot("markland_get", "forbidden_hidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 16: markland_list
# ---------------------------------------------------------------------------

def test_baseline_markland_list_owner_only(mcp):
    alice = mcp.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# Only doc")
    r = alice.call_raw("markland_list")
    mcp.snapshot("markland_list", "owner_only", _envelope_of_response(r))


def test_baseline_markland_list_with_grant(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Shared with Bob")
    alice.call("markland_grant", doc_id=pub["id"], principal="bob@example.com", level="view")
    r = bob.call_raw("markland_list")
    mcp.snapshot("markland_list", "with_grant", _envelope_of_response(r))


def test_baseline_markland_list_unauthenticated(mcp):
    r = mcp.anon().call_raw("markland_list")
    mcp.snapshot("markland_list", "unauthenticated", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 17: markland_search
# ---------------------------------------------------------------------------

def test_baseline_markland_search_match(mcp):
    alice = mcp.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# Unique Findable Content", title="SearchableDoc")
    r = alice.call_raw("markland_search", query="Findable")
    mcp.snapshot("markland_search", "match", _envelope_of_response(r))


def test_baseline_markland_search_no_match(mcp):
    alice = mcp.as_user(email="alice@example.com")
    alice.call("markland_publish", content="# Hello World")
    r = alice.call_raw("markland_search", query="xyzzyquux_no_match_99999")
    mcp.snapshot("markland_search", "no_match", _envelope_of_response(r))


def test_baseline_markland_search_unauthenticated(mcp):
    r = mcp.anon().call_raw("markland_search", query="anything")
    mcp.snapshot("markland_search", "unauthenticated", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 18: markland_share
# ---------------------------------------------------------------------------

def test_baseline_markland_share_owner_share(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Shareable", title="My Share Doc")
    r = alice.call_raw("markland_share", doc_id=pub["id"])
    mcp.snapshot("markland_share", "owner_share", _envelope_of_response(r))


def test_baseline_markland_share_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_share", doc_id="doc_does_not_exist")
    mcp.snapshot("markland_share", "not_found", _envelope_of_response(r))


def test_baseline_markland_share_forbidden_hidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Alice private")
    # Bob has no grant — should get not_found (hidden forbidden)
    r = bob.call_raw("markland_share", doc_id=pub["id"])
    mcp.snapshot("markland_share", "forbidden_hidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 19: markland_update
# ---------------------------------------------------------------------------

def test_baseline_markland_update_success(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# v1", title="Original")
    # Fetch to get the current version number (publish response doesn't include version)
    doc = alice.call("markland_get", doc_id=pub["id"])
    r = alice.call_raw(
        "markland_update",
        doc_id=pub["id"],
        if_version=doc["version"],
        content="# v2 updated",
        title="Updated",
    )
    mcp.snapshot("markland_update", "success", _envelope_of_response(r))


def test_baseline_markland_update_stale_version_conflict(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# v1")
    # Use stale version 99 to trigger conflict
    r = alice.call_raw(
        "markland_update",
        doc_id=pub["id"],
        if_version=99,
        content="# stale",
    )
    mcp.snapshot("markland_update", "stale_version_conflict", _envelope_of_response(r))


def test_baseline_markland_update_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw(
        "markland_update",
        doc_id="doc_does_not_exist",
        if_version=1,
        content="# nope",
    )
    mcp.snapshot("markland_update", "not_found", _envelope_of_response(r))


def test_baseline_markland_update_forbidden_hidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Alice doc")
    # Bob has no access — expect not_found (hidden forbidden); version doesn't matter
    r = bob.call_raw(
        "markland_update",
        doc_id=pub["id"],
        if_version=1,
        content="# Bob tries to update",
    )
    mcp.snapshot("markland_update", "forbidden_hidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 20: markland_delete
# ---------------------------------------------------------------------------

def test_baseline_markland_delete_success(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# To be deleted")
    r = alice.call_raw("markland_delete", doc_id=pub["id"])
    mcp.snapshot("markland_delete", "success", _envelope_of_response(r))


def test_baseline_markland_delete_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_delete", doc_id="doc_does_not_exist")
    mcp.snapshot("markland_delete", "not_found", _envelope_of_response(r))


def test_baseline_markland_delete_non_owner_forbidden_hidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Alice private doc")
    # Per spec §12.5: deny-as-NotFound for non-owners on hidden docs.
    r = bob.call_raw("markland_delete", doc_id=pub["id"])
    mcp.snapshot("markland_delete", "non_owner_forbidden_hidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 21: markland_set_visibility
# ---------------------------------------------------------------------------

def test_baseline_markland_set_visibility_make_public(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Private doc", public=False)
    r = alice.call_raw("markland_set_visibility", doc_id=pub["id"], public=True)
    mcp.snapshot("markland_set_visibility", "make_public", _envelope_of_response(r))


def test_baseline_markland_set_visibility_make_private(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Public doc", public=True)
    r = alice.call_raw("markland_set_visibility", doc_id=pub["id"], public=False)
    mcp.snapshot("markland_set_visibility", "make_private", _envelope_of_response(r))


def test_baseline_markland_set_visibility_non_owner_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Alice doc")
    # Per spec §12.5: deny-as-NotFound for non-owners on hidden docs.
    r = bob.call_raw("markland_set_visibility", doc_id=pub["id"], public=True)
    mcp.snapshot("markland_set_visibility", "non_owner_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 22: markland_feature
# ---------------------------------------------------------------------------

def test_baseline_markland_feature_admin_feature(mcp):
    alice = mcp.as_user(email="alice@example.com")
    admin = mcp.as_admin()
    pub = alice.call("markland_publish", content="# Featured doc", public=True)
    r = admin.call_raw("markland_feature", doc_id=pub["id"], featured=True)
    mcp.snapshot("markland_feature", "admin_feature", _envelope_of_response(r))


def test_baseline_markland_feature_non_admin_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Not featured", public=True)
    # alice is a regular user (not admin) — server returns {"error": "forbidden"}
    r = alice.call_raw("markland_feature", doc_id=pub["id"], featured=True)
    mcp.snapshot("markland_feature", "non_admin_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 23: markland_grant
# ---------------------------------------------------------------------------

def test_baseline_markland_grant_email_target(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")  # seed bob
    pub = alice.call("markland_publish", content="# Grant test")
    r = alice.call_raw("markland_grant", doc_id=pub["id"], principal="bob@example.com", level="view")
    mcp.snapshot("markland_grant", "email_target", _envelope_of_response(r))


def test_baseline_markland_grant_agent_target(mcp):
    alice = mcp.as_user(email="alice@example.com")
    agent = mcp.as_agent(owner_email="alice@example.com")
    pub = alice.call("markland_publish", content="# Agent grant test")
    r = alice.call_raw("markland_grant", doc_id=pub["id"], principal=agent.principal_id, level="edit")
    mcp.snapshot("markland_grant", "agent_target", _envelope_of_response(r))


def test_baseline_markland_grant_invalid_email(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Invalid grant test")
    r = alice.call_raw("markland_grant", doc_id=pub["id"], principal="not-a-real-email", level="view")
    mcp.snapshot("markland_grant", "invalid_email", _envelope_of_response(r))


def test_baseline_markland_grant_non_owner_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    carol = mcp.as_user(email="carol@example.com")
    pub = alice.call("markland_publish", content="# Alice doc")
    # Bob tries to grant on Alice's doc — per §12.5 deny-as-NotFound
    r = bob.call_raw("markland_grant", doc_id=pub["id"], principal="carol@example.com", level="view")
    mcp.snapshot("markland_grant", "non_owner_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 24: markland_revoke
# ---------------------------------------------------------------------------

def test_baseline_markland_revoke_existing_grant(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Revoke test")
    alice.call("markland_grant", doc_id=pub["id"], principal="bob@example.com", level="view")
    r = alice.call_raw("markland_revoke", doc_id=pub["id"], principal="bob@example.com")
    mcp.snapshot("markland_revoke", "existing_grant", _envelope_of_response(r))


def test_baseline_markland_revoke_unknown_target_invalid_argument(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# Revoke no-grant test")
    r = alice.call_raw("markland_revoke", doc_id=pub["id"], principal="nobody@example.com")
    mcp.snapshot("markland_revoke", "unknown_target_invalid_argument", _envelope_of_response(r))


def test_baseline_markland_revoke_non_owner_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    carol = mcp.as_user(email="carol@example.com")
    pub = alice.call("markland_publish", content="# Alice doc for revoke")
    alice.call("markland_grant", doc_id=pub["id"], principal="carol@example.com", level="view")
    # Bob tries to revoke on Alice's doc — per §12.5 deny-as-NotFound
    r = bob.call_raw("markland_revoke", doc_id=pub["id"], principal="carol@example.com")
    mcp.snapshot("markland_revoke", "non_owner_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 25: markland_list_grants
# ---------------------------------------------------------------------------

def test_baseline_markland_list_grants_with_grants(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# List grants test")
    alice.call("markland_grant", doc_id=pub["id"], principal="bob@example.com", level="view")
    r = alice.call_raw("markland_list_grants", doc_id=pub["id"])
    mcp.snapshot("markland_list_grants", "with_grants", _envelope_of_response(r))


def test_baseline_markland_list_grants_no_grants(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# No grants doc")
    r = alice.call_raw("markland_list_grants", doc_id=pub["id"])
    mcp.snapshot("markland_list_grants", "no_grants", _envelope_of_response(r))


def test_baseline_markland_list_grants_non_owner_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# Alice doc for list grants")
    # Bob tries to list grants on Alice's doc — per §12.5 deny-as-NotFound
    r = bob.call_raw("markland_list_grants", doc_id=pub["id"])
    mcp.snapshot("markland_list_grants", "non_owner_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 26: markland_create_invite
# ---------------------------------------------------------------------------

def test_baseline_markland_create_invite_single_use(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw(
        "markland_create_invite",
        doc_id=pub["id"], level="view",
        single_use=True, expires_in_days=None,
    )
    mcp.snapshot("markland_create_invite", "single_use", _envelope_of_response(r))


def test_baseline_markland_create_invite_multi_use_with_expiry(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw(
        "markland_create_invite",
        doc_id=pub["id"], level="edit",
        single_use=False, expires_in_days=7,
    )
    mcp.snapshot("markland_create_invite", "multi_use_with_expiry", _envelope_of_response(r))


def test_baseline_markland_create_invite_non_owner_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = bob.call_raw(
        "markland_create_invite",
        doc_id=pub["id"], level="view",
    )
    mcp.snapshot("markland_create_invite", "non_owner_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 27: markland_revoke_invite
# ---------------------------------------------------------------------------

def test_baseline_markland_revoke_invite_existing(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    inv = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="view",
    )
    r = alice.call_raw("markland_revoke_invite", invite_id=inv["invite_id"])
    mcp.snapshot("markland_revoke_invite", "existing", _envelope_of_response(r))


def test_baseline_markland_revoke_invite_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_revoke_invite", invite_id="inv_does_not_exist")
    mcp.snapshot("markland_revoke_invite", "not_found", _envelope_of_response(r))


def test_baseline_markland_revoke_invite_non_owner_forbidden(mcp):
    alice = mcp.as_user(email="alice@example.com")
    bob = mcp.as_user(email="bob@example.com")
    pub = alice.call("markland_publish", content="# t")
    inv = alice.call(
        "markland_create_invite", doc_id=pub["id"], level="view",
    )
    r = bob.call_raw("markland_revoke_invite", invite_id=inv["invite_id"])
    mcp.snapshot("markland_revoke_invite", "non_owner_forbidden", _envelope_of_response(r))


# ---------------------------------------------------------------------------
# Task 28: markland_whoami
# ---------------------------------------------------------------------------

def test_baseline_markland_whoami_as_user(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_whoami")
    mcp.snapshot("markland_whoami", "as_user", _envelope_of_response(r))


def test_baseline_markland_whoami_as_agent(mcp):
    agent = mcp.as_agent(owner_email="alice@example.com", display_name="bot")
    r = agent.call_raw("markland_whoami")
    mcp.snapshot("markland_whoami", "as_agent", _envelope_of_response(r))


def test_baseline_markland_whoami_anon(mcp):
    r = mcp.anon().call_raw("markland_whoami")
    mcp.snapshot("markland_whoami", "anon", _envelope_of_response(r))
