"""Pytest config — MCP harness fixtures and CLI flags."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from argon2 import PasswordHasher

from markland.service.auth import hash_token, invalidate_token_cache, verify_token
from tests._mcp_harness import MCPHarness


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    """The resolved-token cache is process-global; start every test empty."""
    invalidate_token_cache()
    yield
    invalidate_token_cache()


_SPY_CHECK_HASH: str | None = None


@pytest.fixture
def argon2_verifies():
    """Count every Argon2 verify, however the code under test reaches it.

    Patched on the class: argon2's PasswordHasher uses __slots__, so the
    instance (auth._hasher) can't be patched. Before yielding, one verify
    through markland.service.auth must register, so an `== 0` assertion
    can never pass just because the patch missed.
    """
    global _SPY_CHECK_HASH
    if _SPY_CHECK_HASH is None:
        _SPY_CHECK_HASH = hash_token("spy-check")
    with patch.object(
        PasswordHasher, "verify", autospec=True, side_effect=PasswordHasher.verify
    ) as spy:
        assert verify_token("spy-check", _SPY_CHECK_HASH)
        assert spy.call_count == 1, "Argon2 spy is not wired"
        spy.reset_mock()
        yield spy


def pytest_addoption(parser):
    parser.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        help="Rewrite MCP snapshot baseline files instead of asserting.",
    )
    parser.addoption(
        "--mcp-http-full",
        action="store_true",
        default=False,
        help="Run every baseline scenario in HTTP mode (default: sampled).",
    )


@pytest.fixture
def mcp(tmp_path, request) -> MCPHarness:
    h = MCPHarness.create(tmp_path, mode="direct")
    h._snapshot_update = request.config.getoption("--snapshot-update")
    yield h
    h.close()


@pytest.fixture
def mcp_http(tmp_path, monkeypatch, request) -> MCPHarness:
    h = MCPHarness.create(tmp_path, mode="http", monkeypatch=monkeypatch)
    h._snapshot_update = request.config.getoption("--snapshot-update")
    yield h
    h.close()
