"""Pytest config — MCP harness fixtures and CLI flags."""

from __future__ import annotations

import pytest

from tests._mcp_harness import MCPHarness


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
def mcp(tmp_path) -> MCPHarness:
    h = MCPHarness.create(tmp_path, mode="direct")
    yield h
    h.close()


@pytest.fixture
def mcp_http(tmp_path) -> MCPHarness:
    h = MCPHarness.create(tmp_path, mode="http")
    yield h
    h.close()
