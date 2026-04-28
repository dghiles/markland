"""Layer A — tests of the MCP test harness itself."""

from __future__ import annotations

import pytest

from tests._mcp_harness import MCPHarness


@pytest.fixture
def mcp(tmp_path):
    h = MCPHarness.create(tmp_path)
    yield h
    h.close()


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
