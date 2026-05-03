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


from tests._mcp_harness import MCPHarness


def test_anon_publish_is_unauthenticated(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    r = h.anon().call_raw("markland_publish", content="x")
    r.assert_error("unauthenticated")


def test_get_not_found_error_shape(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    r = alice.call_raw("markland_get", doc_id="doc_does_not_exist")
    r.assert_error("not_found")
    # The wrapper extracts data from ToolError.data, with code stripped.
    assert "code" not in r.error_data


def test_grant_invalid_argument_carries_reason(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw(
        "markland_grant", doc_id=pub["id"],
        target="not-an-email-or-agent", level="view",
    )
    r.assert_error("invalid_argument")
    assert "reason" in r.error_data


def test_feature_non_admin_is_forbidden(tmp_path):
    h = MCPHarness.create(tmp_path, mode="direct")
    alice = h.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# t")
    r = alice.call_raw("markland_feature", doc_id=pub["id"], featured=True)
    r.assert_error("forbidden")


def test_publish_service_agent_is_invalid_argument(tmp_path):
    """Plan-B.1: service-owned agents cannot publish; the tool surfaces
    invalid_argument with reason=service_agent_cannot_publish, not the
    raw PermissionError."""
    h = MCPHarness.create(tmp_path, mode="direct")

    # Build a service-owned agent (owner_user_id is None).
    from markland.service.agents import create_service_agent
    from markland.service.auth import Principal

    agent = create_service_agent(
        h.db, service_id="svc_test", display_name="probe-bot"
    )
    principal = Principal(
        principal_id=agent.id,
        principal_type="agent",
        display_name=agent.display_name,
        is_admin=False,
        user_id=None,  # service agent has no human owner
    )

    # Wire a Caller manually since the harness as_agent only seeds
    # user-owned agents. Direct mode only consults principal; no token
    # validation runs, so we don't need to mint one (and the public
    # create_agent_token API rejects service-owned agents by design).
    from tests._mcp_harness import Caller
    caller = Caller(principal=principal, token=None, _harness=h)

    r = caller.call_raw("markland_publish", content="# probe")
    r.assert_error("invalid_argument")
    assert "service_agent_cannot_publish" in r.error_data.get("reason", "")
