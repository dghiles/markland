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
