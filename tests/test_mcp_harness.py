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


def test_direct_call_raw_publish_succeeds(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_publish", content="# hi", title=None, public=False)
    r.assert_ok()
    assert r.value["owner_id"] == alice.principal_id
    assert "share_url" in r.value


def test_direct_call_raw_normalizes_not_found(mcp):
    alice = mcp.as_user(email="alice@example.com")
    r = alice.call_raw("markland_get", doc_id="doc_does_not_exist")
    r.assert_error("not_found")


def test_direct_call_raw_unknown_tool_raises_harness_error(mcp):
    alice = mcp.as_user(email="alice@example.com")
    from tests._mcp_harness import MCPHarnessError

    with pytest.raises(MCPHarnessError, match="no such tool"):
        alice.call_raw("markland_publshhh", content="x")


def test_call_returns_value_on_success(mcp):
    alice = mcp.as_user(email="alice@example.com")
    value = alice.call("markland_publish", content="# hi")
    assert value["owner_id"] == alice.principal_id


def test_call_raises_mcp_call_error(mcp):
    alice = mcp.as_user(email="alice@example.com")
    from tests._mcp_harness import MCPCallError

    with pytest.raises(MCPCallError) as exc_info:
        alice.call("markland_get", doc_id="doc_nope")
    assert exc_info.value.response.error_code == "not_found"
    assert exc_info.value.tool == "markland_get"
    assert exc_info.value.kwargs == {"doc_id": "doc_nope"}


def test_http_call_publish(mcp_http):
    alice = mcp_http.as_user(email="alice@example.com")
    value = alice.call("markland_publish", content="# hi")
    assert value["owner_id"] == alice.principal_id
    assert "share_url" in value


def test_http_anon_unauthenticated(mcp_http):
    r = mcp_http.anon().call_raw("markland_publish", content="x")
    r.assert_error("unauthenticated")


def test_http_session_per_caller(mcp_http):
    alice = mcp_http.as_user(email="alice@example.com")
    bob = mcp_http.as_user(email="bob@example.com")
    alice.call("markland_publish", content="# from alice")
    bob.call("markland_publish", content="# from bob")
    assert alice._http_session_id is not None
    assert bob._http_session_id is not None
    assert alice._http_session_id != bob._http_session_id


def test_mode_equivalence_publish(tmp_path):
    """Same call in direct and http modes produces equivalent Response shapes."""
    direct = MCPHarness.create(tmp_path / "d", mode="direct")
    http = MCPHarness.create(tmp_path / "h", mode="http")
    try:
        alice_d = direct.as_user(email="alice@example.com")
        alice_h = http.as_user(email="alice@example.com")

        rd = alice_d.call_raw("markland_publish", content="# hi")
        rh = alice_h.call_raw("markland_publish", content="# hi")

        assert rd.ok == rh.ok
        # IDs and timestamps differ; structure must match.
        assert set(rd.value) == set(rh.value), (rd.value, rh.value)
    finally:
        direct.close()
        http.close()


def test_email_capture_on_grant(mcp):
    alice = mcp.as_user(email="alice@example.com")
    pub = alice.call("markland_publish", content="# shared")

    # Seed bob first so the grant has a target user.
    mcp.as_user(email="bob@example.com")

    alice.call(
        "markland_grant",
        doc_id=pub["id"],
        principal="bob@example.com",
        level="view",
    )

    sent = mcp.emails_sent_to("bob@example.com")
    assert len(sent) == 1
    assert "shared" in (sent[0].get("subject", "") + sent[0].get("text", "")).lower()


from tests._mcp_harness import as_envelope


def test_as_envelope_strips_volatile_fields():
    payload = {
        "id": "doc_abc123",
        "owner_id": "usr_xyz789",
        "share_url": "https://harness.test/d/abc123",
        "share_token": "abc123",
        "created_at": "2026-04-27T03:00:00Z",
        "updated_at": "2026-04-27T03:00:01Z",
        "title": "Hello",
        "content": "# Hello",
        "version": 1,
        "is_public": False,
    }
    out = as_envelope(payload)
    assert out["id"] == "<DOC_ID>"
    assert out["owner_id"] == "<USR_ID>"
    assert out["share_url"] == "<SHARE_URL>"
    assert out["share_token"] == "<SHARE_TOKEN>"
    assert out["created_at"] == "<TIMESTAMP>"
    assert out["updated_at"] == "<TIMESTAMP>"
    # Stable fields untouched.
    assert out["title"] == "Hello"
    assert out["content"] == "# Hello"
    assert out["version"] == 1
    assert out["is_public"] is False


def test_as_envelope_recurses_into_lists():
    payload = {"items": [{"id": "doc_a"}, {"id": "doc_b"}]}
    out = as_envelope(payload)
    assert out == {"items": [{"id": "<DOC_ID>"}, {"id": "<DOC_ID>"}]}


def test_snapshot_assert_match_writes_in_update_mode(mcp, monkeypatch, tmp_path):
    fixtures_dir = tmp_path / "snapshots"
    monkeypatch.setattr(
        "tests._mcp_harness._SNAPSHOT_DIR", fixtures_dir, raising=False
    )
    mcp._snapshot_update = True

    mcp.snapshot("markland_publish", "minimal", {"id": "<DOC_ID>", "version": 1})

    path = fixtures_dir / "markland_publish.json"
    assert path.exists()
    import json
    data = json.loads(path.read_text())
    assert data["minimal"] == {"id": "<DOC_ID>", "version": 1}


def test_snapshot_missing_scenario_raises(mcp, tmp_path, monkeypatch):
    fixtures_dir = tmp_path / "snapshots"
    fixtures_dir.mkdir()
    monkeypatch.setattr(
        "tests._mcp_harness._SNAPSHOT_DIR", fixtures_dir, raising=False
    )
    mcp._snapshot_update = False

    with pytest.raises(AssertionError, match="--snapshot-update"):
        mcp.snapshot("markland_publish", "minimal", {"id": "<DOC_ID>"})


def test_snapshot_mismatch_raises_with_diff(mcp, tmp_path, monkeypatch):
    fixtures_dir = tmp_path / "snapshots"
    fixtures_dir.mkdir()
    (fixtures_dir / "markland_publish.json").write_text(
        '{"minimal": {"id": "<DOC_ID>", "version": 1}}\n'
    )
    monkeypatch.setattr(
        "tests._mcp_harness._SNAPSHOT_DIR", fixtures_dir, raising=False
    )
    mcp._snapshot_update = False

    with pytest.raises(AssertionError, match="snapshot mismatch"):
        mcp.snapshot("markland_publish", "minimal", {"id": "<DOC_ID>", "version": 2})
