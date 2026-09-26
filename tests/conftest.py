"""Pytest config — MCP harness fixtures and CLI flags."""

from __future__ import annotations

import pytest

from markland.service.auth import invalidate_token_cache
from tests._mcp_harness import MCPHarness


@pytest.fixture(autouse=True)
def _fresh_token_cache():
    """The resolved-token cache is process-global; start every test empty."""
    invalidate_token_cache()
    yield
    invalidate_token_cache()


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
