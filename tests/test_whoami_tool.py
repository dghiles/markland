"""Unit tests for the whoami tool function."""

from markland.server import _whoami_for_principal
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
