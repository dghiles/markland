"""Layer A — tests of the MCP test harness itself."""

from __future__ import annotations

import pytest

from tests._mcp_harness import MCPHarness


def test_harness_create_direct_mode(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    assert h.mode == "direct"
    assert h.db is not None


def test_as_user_seeds_user_and_mints_token(mcp):
    caller = mcp.as_user(email="alice@example.com")
    assert caller.principal_id.startswith("usr_")
    assert caller.token.startswith("mk_usr_")
    assert caller.principal.principal_type == "user"
    assert caller.principal.is_admin is False


def test_as_user_caches_by_email(mcp):
    a = mcp.as_user(email="alice@example.com")
    b = mcp.as_user(email="alice@example.com")
    assert a is b


def test_as_user_fresh_mints_new_token(mcp):
    a = mcp.as_user(email="alice@example.com")
    b = mcp.as_user(email="alice@example.com", fresh=True)
    assert a.principal_id == b.principal_id  # same user
    assert a.token != b.token  # different token


def test_as_user_admin(mcp):
    caller = mcp.as_user(email="boss@example.com", is_admin=True)
    assert caller.principal.is_admin is True


def test_as_admin_convenience(mcp):
    caller = mcp.as_admin()
    assert caller.principal.is_admin is True
    assert caller.principal_id.startswith("usr_")


def test_as_agent_seeds_owning_user_and_agent(mcp):
    caller = mcp.as_agent(owner_email="owner@example.com", display_name="bot")
    assert caller.principal_id.startswith("agt_")
    assert caller.token.startswith("mk_agt_")
    assert caller.principal.principal_type == "agent"
    # Owner exists too.
    row = mcp.db.execute(
        "SELECT id FROM users WHERE lower(email) = 'owner@example.com'"
    ).fetchone()
    assert row is not None
    assert caller.principal.user_id == row[0]


def test_anon_returns_caller_with_no_principal(mcp):
    caller = mcp.anon()
    assert caller.principal is None
    assert caller.principal_id is None
    assert caller.token is None


from tests._mcp_harness import Response


def test_response_ok():
    r = Response(ok=True, value={"id": "doc_x"}, error_code=None, error_data={}, raw=None)
    r.assert_ok()
    assert r.value == {"id": "doc_x"}


def test_response_error():
    r = Response(
        ok=False, value=None, error_code="not_found", error_data={}, raw=None
    )
    with pytest.raises(AssertionError):
        r.assert_ok()
    r.assert_error("not_found")
    with pytest.raises(AssertionError):
        r.assert_error("forbidden")


def test_response_assert_error_with_data():
    r = Response(
        ok=False,
        value=None,
        error_code="conflict",
        error_data={"current_version": 3},
        raw=None,
    )
    r.assert_error("conflict", current_version=3)
    with pytest.raises(AssertionError):
        r.assert_error("conflict", current_version=99)
