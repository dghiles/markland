"""Unit tests for the whoami tool function and the is_admin gate on feature."""

import pytest

from markland.db import init_db
from markland.server import _feature_requires_admin, _whoami_for_principal
from markland.service.auth import Principal


def test_whoami_returns_principal_fields():
    p = Principal(
        principal_id="usr_abc",
        principal_type="user",
        display_name="Alice",
        is_admin=False,
    )
    assert _whoami_for_principal(p) == {
        "principal_id": "usr_abc",
        "principal_type": "user",
        "display_name": "Alice",
    }


def test_feature_requires_admin_allows_admin(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Principal(
        principal_id="usr_x",
        principal_type="user",
        display_name="X",
        is_admin=True,
    )
    # Should not raise
    _feature_requires_admin(p)


def test_feature_requires_admin_rejects_non_admin(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Principal(
        principal_id="usr_x",
        principal_type="user",
        display_name="X",
        is_admin=False,
    )
    with pytest.raises(PermissionError):
        _feature_requires_admin(p)
