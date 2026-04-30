"""Layer C — axis 3: error-model contract."""

import pytest
from markland._mcp_errors import tool_error, ERROR_CODES


def test_error_codes_are_a_closed_set():
    assert ERROR_CODES == {
        "unauthenticated",
        "forbidden",
        "not_found",
        "conflict",
        "invalid_argument",
        "rate_limited",
        "internal_error",
    }


def test_tool_error_carries_code_and_data():
    err = tool_error("conflict", current_version=3)
    assert err.data == {"code": "conflict", "current_version": 3}


def test_tool_error_rejects_unknown_code():
    with pytest.raises(ValueError, match="not in ERROR_CODES"):
        tool_error("teapot")
