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
