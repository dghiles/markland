"""Revokes must evict the resolved-token cache — reliably, and only for the
affected principal.

The shared sqlite3 connection can make commit() raise (InterfaceError,
SystemError) after the revoke's UPDATE already ran; the pending UPDATE is then
persisted by the next commit on that connection, from any thread. If the
eviction only runs after a clean commit, the DB says "revoked" while the cache
keeps serving the principal for up to TOKEN_CACHE_TTL_S, and the user's retry
is a no-op that doesn't evict either. Before the cache existed, the next
resolve saw the revoke immediately — these tests keep that property.
"""

from __future__ import annotations

import hashlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import auth
from markland.service.agents import create_agent, revoke_agent
from markland.service.auth import create_agent_token, create_user_token, resolve_token, revoke_token
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "s" * 32


class _MisreadCursor:
    """A cursor whose rowcount reads 0 although its UPDATE applied — what a
    concurrent statement from another thread does to sqlite3_changes() on an
    unserialised shared connection."""

    def __init__(self, cursor):
        self._cursor = cursor
        self.rowcount = 0

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class FlakyCommitConn(sqlite3.Connection):
    fail_next_commit = False
    misread_update_rowcount = False

    def commit(self):
        if FlakyCommitConn.fail_next_commit:
            FlakyCommitConn.fail_next_commit = False
            raise sqlite3.InterfaceError("bad parameter or other API misuse")
        return super().commit()

    def execute(self, sql, *args):
        cursor = super().execute(sql, *args)
        if FlakyCommitConn.misread_update_rowcount and sql.lstrip().upper().startswith("UPDATE"):
            FlakyCommitConn.misread_update_rowcount = False
            return _MisreadCursor(cursor)
        return cursor


@pytest.fixture
def conn(tmp_path, monkeypatch):
    real_connect = sqlite3.connect

    def connect(*args, **kwargs):
        kwargs["factory"] = FlakyCommitConn
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    FlakyCommitConn.fail_next_commit = False
    FlakyCommitConn.misread_update_rowcount = False
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


def test_revoke_token_evicts_when_commit_raises(conn):
    user = create_user(conn, email="a@x", display_name="A")
    token_id, token = create_user_token(conn, user_id=user.id, label="t")
    assert resolve_token(conn, token) is not None  # now cached

    FlakyCommitConn.fail_next_commit = True
    with pytest.raises(sqlite3.InterfaceError):
        revoke_token(conn, token_id=token_id, user_id=user.id)
    conn.commit()  # a later commit on the shared connection persists the UPDATE

    assert resolve_token(conn, token) is None


def test_revoke_agent_evicts_when_commit_raises(conn):
    user = create_user(conn, email="b@x", display_name="B")
    agent = create_agent(conn, owner_user_id=user.id, display_name="ag")
    _, token = create_agent_token(conn, agent_id=agent.id, owner_user_id=user.id, label="l")
    assert resolve_token(conn, token) is not None

    FlakyCommitConn.fail_next_commit = True
    with pytest.raises(sqlite3.InterfaceError):
        revoke_agent(conn, agent.id, owner_user_id=user.id)
    conn.commit()

    assert resolve_token(conn, token) is None


@pytest.fixture
def client_env(conn, monkeypatch):
    for kind in ("USER", "AGENT", "ANON"):
        monkeypatch.setenv(f"MARKLAND_RATE_LIMIT_{kind}_PER_MIN", "10000")
    conn.execute(
        "INSERT INTO users(id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@x', 'Alice', 0, '2026-01-01')"
    )
    conn.commit()
    app = create_app(conn, mount_mcp=False, base_url="https://markland.test", session_secret=SECRET)
    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(SESSION_COOKIE_NAME, issue_session("usr_alice", secret=SECRET))
        agent_id = client.post("/api/agents", json={"display_name": "scribe"}).json()["id"]
        tok = client.post(f"/api/agents/{agent_id}/tokens", json={"label": "l"}).json()
        client.cookies.clear()
        yield conn, client, agent_id, tok


def _signed_in(client) -> None:
    client.cookies.set(SESSION_COOKIE_NAME, issue_session("usr_alice", secret=SECRET))


def test_agent_token_route_evicts_when_commit_raises(client_env):
    conn, client, agent_id, tok = client_env
    bearer = {"Authorization": f"Bearer {tok['plaintext']}"}
    assert client.get("/admin/metrics", headers=bearer).status_code == 403  # cached

    _signed_in(client)
    FlakyCommitConn.fail_next_commit = True
    assert client.delete(f"/api/agents/{agent_id}/tokens/{tok['id']}").status_code == 500
    client.cookies.clear()
    conn.commit()

    assert client.get("/admin/metrics", headers=bearer).status_code == 401


def test_agent_token_route_redelete_does_not_disturb_other_principals(client_env):
    conn, client, agent_id, tok = client_env
    bob = create_user(conn, email="bob@x", display_name="Bob")
    _, bob_token = create_user_token(conn, user_id=bob.id, label="b")
    assert resolve_token(conn, bob_token) is not None  # bob is cached

    _signed_in(client)
    for _ in range(4):
        assert client.delete(f"/api/agents/{agent_id}/tokens/{tok['id']}").status_code == 204

    key = hashlib.sha256(bob_token.encode("utf-8")).digest()
    assert auth._token_cache.get(key) is not None  # an owner can't flush others


def test_cache_expiry_counts_from_resolve_start(conn, monkeypatch):
    """A slow (e.g. CPU-throttled) legacy scan must not stretch the TTL.

    Out-of-process writes (scripts/admin/*) are documented to land within
    TOKEN_CACHE_TTL_S of the DB read; stamping expiry when put() runs would add
    the whole scan duration on top.
    """
    clock = FakeClock()
    monkeypatch.setattr(auth._token_cache, "_clock", clock)
    user = create_user(conn, email="c@x", display_name="C")
    _, token = create_user_token(conn, user_id=user.id, label="t")

    real_resolve = auth._resolve_uncached

    def slow_resolve(c, plaintext):
        principal = real_resolve(c, plaintext)
        clock.now += 30.0  # the DB read happened at the start; the scan ran long
        return principal

    monkeypatch.setattr(auth, "_resolve_uncached", slow_resolve)
    started = clock.now
    assert resolve_token(conn, token) is not None

    key = hashlib.sha256(token.encode("utf-8")).digest()
    clock.now = started + auth.TOKEN_CACHE_TTL_S - 0.1
    assert auth._token_cache.get(key) is not None
    clock.now = started + auth.TOKEN_CACHE_TTL_S + 0.1
    assert auth._token_cache.get(key) is None


# --- rowcount is not trusted -----------------------------------------------------


def test_revoke_token_evicts_when_rowcount_is_misread(conn):
    user = create_user(conn, email="d@x", display_name="D")
    token_id, token = create_user_token(conn, user_id=user.id, label="t")
    assert resolve_token(conn, token) is not None

    FlakyCommitConn.misread_update_rowcount = True
    revoke_token(conn, token_id=token_id, user_id=user.id)
    assert conn.execute("SELECT revoked_at FROM tokens WHERE id=?", (token_id,)).fetchone()[0] is not None

    assert resolve_token(conn, token) is None


def test_revoke_agent_evicts_when_rowcount_is_misread(conn):
    user = create_user(conn, email="e@x", display_name="E")
    agent = create_agent(conn, owner_user_id=user.id, display_name="ag")
    _, token = create_agent_token(conn, agent_id=agent.id, owner_user_id=user.id, label="l")
    assert resolve_token(conn, token) is not None

    FlakyCommitConn.misread_update_rowcount = True
    revoke_agent(conn, agent.id, owner_user_id=user.id)

    assert resolve_token(conn, token) is None


def test_agent_token_route_evicts_when_rowcount_is_misread(client_env):
    _, client, agent_id, tok = client_env
    bearer = {"Authorization": f"Bearer {tok['plaintext']}"}
    assert client.get("/admin/metrics", headers=bearer).status_code == 403

    _signed_in(client)
    FlakyCommitConn.misread_update_rowcount = True
    assert client.delete(f"/api/agents/{agent_id}/tokens/{tok['id']}").status_code == 204
    client.cookies.clear()

    assert client.get("/admin/metrics", headers=bearer).status_code == 401


# --- eviction is scoped to the affected principal --------------------------------


def test_mint_and_revoke_does_not_flush_other_principals(conn):
    """No global flush lever: a signed-in user minting and revoking their own
    tokens must not push everyone else's cached tokens back onto the scan."""
    alice = create_user(conn, email="f@x", display_name="Alice")
    bob = create_user(conn, email="g@x", display_name="Bob")
    _, bob_token = create_user_token(conn, user_id=bob.id, label="b")
    assert resolve_token(conn, bob_token) is not None

    for _ in range(3):
        tid, _ = create_user_token(conn, user_id=alice.id, label="throwaway")
        assert revoke_token(conn, token_id=tid, user_id=alice.id) is True

    key = hashlib.sha256(bob_token.encode("utf-8")).digest()
    assert auth._token_cache.get(key) is not None


def _p(pid: str) -> auth.Principal:
    return auth.Principal(principal_id=pid, principal_type="user", display_name=None, is_admin=False)


def test_eviction_drops_only_the_same_principals_in_flight_put():
    """A resolve that straddles an eviction of ITS principal must not re-cache;
    evictions of other principals must not stop it caching (else revoke spam
    could keep every legacy scan uncached)."""
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=8, clock=FakeClock())

    gen, read_at = cache.begin()
    cache.evict_principal("usr_alice")
    cache.put(b"bob", _p("usr_bob"), generation=gen, read_at=read_at)
    assert cache.get(b"bob") is not None

    gen, read_at = cache.begin()
    cache.evict_principal("usr_bob")
    cache.put(b"bob2", _p("usr_bob"), generation=gen, read_at=read_at)
    assert cache.get(b"bob2") is None


def test_evict_principal_removes_only_that_principals_entries():
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=8, clock=FakeClock())
    cache.put(b"a1", _p("usr_alice"), generation=cache.generation)
    cache.put(b"a2", _p("usr_alice"), generation=cache.generation)
    cache.put(b"b1", _p("usr_bob"), generation=cache.generation)

    cache.evict_principal("usr_alice")

    assert cache.get(b"a1") is None and cache.get(b"a2") is None
    assert cache.get(b"b1") is not None


def test_clear_still_drops_every_in_flight_put():
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=8, clock=FakeClock())
    gen, read_at = cache.begin()
    cache.clear()
    cache.put(b"k", _p("usr_bob"), generation=gen, read_at=read_at)
    assert cache.get(b"k") is None
