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
