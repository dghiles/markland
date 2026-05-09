"""Service-layer tests for device_flow helpers used by Phase 2 dashboard panel."""

from __future__ import annotations

import pytest

from markland.db import init_db
from markland.service import device_flow
from markland.service.users import create_user


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_has_authorized_device_false_when_no_device_authorizations(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    assert device_flow.has_authorized_device(conn, user.id) is False


def test_has_authorized_device_true_after_authorize(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    start = device_flow.start(conn, base_url="https://markland.dev")
    result = device_flow.authorize(conn, start.user_code, user_id=user.id)
    assert result.ok is True
    assert device_flow.has_authorized_device(conn, user.id) is True


def test_has_authorized_device_false_for_pending_only(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    device_flow.start(conn, base_url="https://markland.dev")
    # No authorize() call — row is pending, not authorized.
    assert device_flow.has_authorized_device(conn, user.id) is False
