"""Request-level auth cost: one token resolve per HTTP request, at most.

RateLimitMiddleware (outermost) resolves the bearer for rate-limit
tiering; PrincipalMiddleware (inner, /mcp and /admin/) gates on it. Both
must share one resolution per request — including an explicit
"resolved, invalid" outcome, so a bad token does not pay for two full
argon2 scans. Successful resolutions are then cached across requests.
"""

from __future__ import annotations

import secrets
import sqlite3
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import auth
from markland.service.auth import (
    _resolve_legacy,
    create_user_token,
    hash_token,
)
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.web.app import create_app
from markland.web.principal_middleware import PrincipalMiddleware

SECRET = "test-session-secret"


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> FakeClock:
    c = FakeClock()
    monkeypatch.setattr(auth._token_cache, "_clock", c)
    return c


@pytest.fixture
def uncached_spy():
    """Counts fresh (non-cache) resolutions."""
    with patch(
        "markland.service.auth._resolve_uncached", wraps=auth._resolve_uncached
    ) as spy:
        yield spy


@pytest.fixture
def scan_spy():
    with patch(
        "markland.service.auth._resolve_legacy", wraps=_resolve_legacy
    ) as spy:
        yield spy


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "10000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_AGENT_PER_MIN", "10000")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "10000")
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@x', 'Alice', 0, '2026-01-01')"
    )
    conn.commit()
    app = create_app(
        conn, mount_mcp=False, base_url="https://markland.test",
        session_secret=SECRET,
    )
    with TestClient(app) as client:
        yield conn, client
    conn.close()


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _insert_legacy_token(conn, *, user_id: str, token_id: str) -> str:
    plaintext = "mk_usr_" + secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'legacy', 'user', ?, '2026-01-01T00:00:00+00:00', NULL, NULL)",
        (token_id, hash_token(plaintext), user_id),
    )
    conn.commit()
    return plaintext


# --- one resolve per request --------------------------------------------------


def test_invalid_bearer_on_protected_path_costs_one_scan(env, argon2_verifies, scan_spy):
    """Before: RateLimit scanned, found nothing, then PrincipalMiddleware
    scanned again — 2N argon2 verifies per 401. Now only digest-less rows
    are ever verified, and still only once per request."""
    conn, client = env
    for i in range(3):
        create_user_token(conn, user_id="usr_alice", label=f"t{i}")
    _insert_legacy_token(conn, user_id="usr_alice", token_id="tok_legacy")

    r = client.get("/admin/metrics", headers=_bearer("mk_usr_not_a_real_token"))
    assert r.status_code == 401
    assert scan_spy.call_count == 1
    assert argon2_verifies.call_count == 1  # the legacy row, once — not twice


def test_invalid_bearer_is_rescanned_on_every_request(env, scan_spy):
    """Failures are not cached across requests (only within one)."""
    conn, client = env
    create_user_token(conn, user_id="usr_alice", label="t")
    for _ in range(3):
        r = client.get("/admin/metrics", headers=_bearer("mk_usr_nope"))
        assert r.status_code == 401
    assert scan_spy.call_count == 3


def test_valid_bearer_on_protected_path_resolves_once_without_argon2(
    env, uncached_spy, argon2_verifies
):
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    r = client.get("/admin/metrics", headers=_bearer(token))
    assert r.status_code == 403  # authenticated, not an admin
    assert uncached_spy.call_count == 1
    assert argon2_verifies.call_count == 0


def test_bearer_on_unprotected_path_resolves_once(env, uncached_spy):
    """Only RateLimitMiddleware sees this request's bearer."""
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    assert client.get("/health", headers=_bearer(token)).status_code == 200
    assert uncached_spy.call_count == 1


def test_principal_middleware_without_rate_limit_in_front(tmp_path, uncached_spy):
    """PrincipalMiddleware with no RateLimitMiddleware in front still
    authenticates, resolving exactly once per request."""
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@x', 'Bob', 0, '2026-01-01')"
    )
    conn.commit()
    _, token = create_user_token(conn, user_id="usr_bob", label="t")

    app = FastAPI()
    app.add_middleware(PrincipalMiddleware, db_conn=conn, protected_prefixes=("/mcp",))

    @app.get("/mcp/ping")
    def ping(request: Request):
        return JSONResponse({"id": request.state.principal.principal_id})

    client = TestClient(app)
    r = client.get("/mcp/ping", headers=_bearer(token))
    assert r.status_code == 200 and r.json() == {"id": "usr_bob"}
    assert uncached_spy.call_count == 1

    r = client.get("/mcp/ping", headers=_bearer("mk_usr_nope"))
    assert r.status_code == 401
    assert uncached_spy.call_count == 2  # the bad bearer, resolved once


def test_transient_error_in_rate_limit_resolve_is_retried_not_memoized(env):
    """An exception is not a verdict: PrincipalMiddleware retries instead of
    turning a transient DB error into a 401."""
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    real_lookup = auth._resolve_by_digest
    calls = []

    def flaky_lookup(c, digest):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.InterfaceError("simulated")
        return real_lookup(c, digest)

    with patch("markland.service.auth._resolve_by_digest", side_effect=flaky_lookup):
        r = client.get("/admin/metrics", headers=_bearer(token))
    assert r.status_code == 403  # authenticated on the retry
    assert len(calls) == 2


# --- cache across requests ----------------------------------------------------


def test_repeat_requests_hit_the_cache(env, uncached_spy):
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    for _ in range(5):
        assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 403
    assert uncached_spy.call_count == 1


def test_legacy_token_scans_once_then_resolves_by_digest(
    env, argon2_verifies, scan_spy, clock
):
    conn, client = env
    for i in range(4):
        create_user_token(conn, user_id="usr_alice", label=f"t{i}")
    legacy = _insert_legacy_token(conn, user_id="usr_alice", token_id="tok_legacy")

    for _ in range(5):
        assert client.get("/admin/metrics", headers=_bearer(legacy)).status_code == 403
    assert scan_spy.call_count == 1
    assert argon2_verifies.call_count == 1  # only the digest-less row

    clock.advance(auth.TOKEN_CACHE_TTL_S + 1)
    assert client.get("/admin/metrics", headers=_bearer(legacy)).status_code == 403
    assert scan_spy.call_count == 1  # backfilled: a digest hit, no scan
    assert argon2_verifies.call_count == 1


# --- invalidation through the real endpoints ------------------------------------


def _sign_in(client, user_id: str = "usr_alice") -> None:
    client.cookies.set(SESSION_COOKIE_NAME, issue_session(user_id, secret=SECRET))


def test_revoking_user_token_via_api_rejects_next_request(env):
    conn, client = env
    token_id, token = create_user_token(conn, user_id="usr_alice", label="t")
    assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 403

    _sign_in(client)
    assert client.delete(f"/api/tokens/{token_id}").status_code == 200
    client.cookies.clear()

    assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 401


def test_revoking_agent_token_via_api_rejects_next_request(env):
    _, client = env
    _sign_in(client)
    agent_id = client.post("/api/agents", json={"display_name": "scribe"}).json()["id"]
    t = client.post(f"/api/agents/{agent_id}/tokens", json={"label": "l"}).json()
    client.cookies.clear()
    assert client.get("/admin/metrics", headers=_bearer(t["plaintext"])).status_code == 403

    _sign_in(client)
    assert client.delete(f"/api/agents/{agent_id}/tokens/{t['id']}").status_code == 204
    client.cookies.clear()

    assert client.get("/admin/metrics", headers=_bearer(t["plaintext"])).status_code == 401


def test_revoking_agent_via_api_rejects_its_token_on_next_request(env):
    _, client = env
    _sign_in(client)
    agent_id = client.post("/api/agents", json={"display_name": "scribe"}).json()["id"]
    t = client.post(f"/api/agents/{agent_id}/tokens", json={"label": "l"}).json()
    client.cookies.clear()
    assert client.get("/admin/metrics", headers=_bearer(t["plaintext"])).status_code == 403

    _sign_in(client)
    assert client.delete(f"/api/agents/{agent_id}").status_code == 204
    client.cookies.clear()

    assert client.get("/admin/metrics", headers=_bearer(t["plaintext"])).status_code == 401


def test_revoking_agent_via_settings_form_rejects_its_token_on_next_request(env):
    _, client = env
    _sign_in(client)
    agent_id = client.post("/api/agents", json={"display_name": "scribe"}).json()["id"]
    t = client.post(f"/api/agents/{agent_id}/tokens", json={"label": "l"}).json()
    client.cookies.clear()
    assert client.get("/admin/metrics", headers=_bearer(t["plaintext"])).status_code == 403

    _sign_in(client)
    r = client.post(f"/settings/agents/{agent_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    client.cookies.clear()

    assert client.get("/admin/metrics", headers=_bearer(t["plaintext"])).status_code == 401


# --- is_admin -------------------------------------------------------------------


def test_admin_promotion_out_of_process_lands_within_ttl(env, clock):
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 403

    # What scripts/admin/make_admin.py does, from another process.
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = 'usr_alice'")
    conn.commit()
    assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 403

    clock.advance(auth.TOKEN_CACHE_TTL_S + 1)
    assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 200


# --- failed auth is cheap (markland-ts6) ------------------------------------------


def test_failed_auth_over_http_costs_no_argon2_without_pre_cutoff_rows(
    env, argon2_verifies, uncached_spy
):
    """The bearer resolves before the rate-limit check, so a failed auth
    must be cheap on its own. With no pre-cutoff digest-less rows, a burst
    of bad bearers is all 401s, one resolve each, and zero Argon2 — even
    while a new-shape token is still waiting for its backfill."""
    conn, client = env
    for i in range(3):
        create_user_token(conn, user_id="usr_alice", label=f"t{i}")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'dormant', 'user', 'usr_alice', "
        "'2026-09-01T00:00:00+00:00', NULL, NULL)",
        (token_id, hash_token(plaintext)),
    )
    conn.commit()

    bad = [
        "mk_usr_" + secrets.token_urlsafe(32),
        "mk_usr_deadbeefdeadbeef_" + secrets.token_urlsafe(32),
    ] * 10
    for token in bad:
        r = client.get("/admin/metrics", headers=_bearer(token))
        assert r.status_code == 401
    assert uncached_spy.call_count == len(bad)
    assert argon2_verifies.call_count == 0
