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
