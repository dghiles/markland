"""Tests for the in-process cache of successful token resolutions.

Why this exists: on 2026-09-26 a post-deploy reconnect burst paid an
Argon2id scan (~1 CPU-s) on every request until the Fly burst balance ran
out. Resolves now use an indexed digest lookup (markland-tex). A cache hit
still costs no SQL on the shared connection and no last_used_at write, and
a token with no digest yet still pays Argon2 on its first resolve.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from unittest.mock import patch

import pytest

from markland.db import init_db
from markland.service import auth
from markland.service.agents import create_agent, revoke_agent
from markland.service.auth import (
    create_agent_token,
    create_user_token,
    hash_token,
    resolve_token,
    revoke_token,
)
from markland.service.users import create_user


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

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


def _insert_legacy_token(conn, *, user_id: str, token_id: str) -> str:
    """Mint a pre-markland-9dm token: 'mk_usr_' + urlsafe(32), no token_id."""
    plaintext = "mk_usr_" + secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'legacy', 'user', ?, '2026-01-01T00:00:00+00:00', NULL, NULL)",
        (token_id, hash_token(plaintext), user_id),
    )
    conn.commit()
    return plaintext


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


# --- cache hits skip the DB and argon2 ----------------------------------------


def test_second_resolve_is_a_cache_hit(conn, uncached_spy):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")

    first = resolve_token(conn, plaintext)
    assert first is not None
    assert uncached_spy.call_count == 1

    second = resolve_token(conn, plaintext)
    assert second == first
    assert uncached_spy.call_count == 1  # cache hit: no fresh resolve


def test_cache_hit_issues_no_sql(conn):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    resolve_token(conn, plaintext)

    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert resolve_token(conn, plaintext) is not None
    finally:
        conn.set_trace_callback(None)
    assert statements == []


def test_legacy_token_costs_one_scan_ever_then_digest_hits(
    conn, argon2_verifies, uncached_spy, clock
):
    u = create_user(conn, email="a@x", display_name="A")
    for i in range(4):
        create_user_token(conn, user_id=u.id, label=f"other{i}")
    legacy = _insert_legacy_token(conn, user_id=u.id, token_id="tok_legacy_last")

    for _ in range(10):
        assert resolve_token(conn, legacy) is not None
    # One scan, of the only digest-less row; then cache hits.
    assert argon2_verifies.call_count == 1
    assert uncached_spy.call_count == 1

    clock.advance(auth.TOKEN_CACHE_TTL_S + 1)
    assert resolve_token(conn, legacy) is not None
    assert uncached_spy.call_count == 2  # the entry really expired
    assert argon2_verifies.call_count == 1  # but backfilled: a digest hit


def test_cache_is_keyed_by_sha256_and_never_holds_the_plaintext(conn):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    resolve_token(conn, plaintext)

    keys = list(auth._token_cache._entries)
    assert keys == [hashlib.sha256(plaintext.encode("utf-8")).digest()]
    assert plaintext not in repr(auth._token_cache._entries)


# --- failures are never cached ------------------------------------------------


def test_failed_resolve_is_not_cached(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="t")
    _insert_legacy_token(conn, user_id=u.id, token_id="tok_legacy")

    assert resolve_token(conn, "mk_usr_bogus") is None
    assert resolve_token(conn, "mk_usr_bogus") is None
    # The digest-less legacy row is re-verified on each attempt: nothing
    # remembered the failure. (The minted row has a digest: never verified.)
    assert argon2_verifies.call_count == 2
    assert len(auth._token_cache) == 0


def test_token_that_failed_resolves_once_it_becomes_valid(conn):
    """A None result must not be remembered: the same plaintext resolves as
    soon as a matching row exists."""
    u = create_user(conn, email="a@x", display_name="A")
    plaintext = "mk_usr_" + secrets.token_urlsafe(32)
    assert resolve_token(conn, plaintext) is None

    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES ('tok_late', ?, 'late', 'user', ?, '2026-01-01', NULL, NULL)",
        (hash_token(plaintext), u.id),
    )
    conn.commit()
    p = resolve_token(conn, plaintext)
    assert p is not None and p.principal_id == u.id


# --- last_used_at is touched at most once per TTL -------------------------------


def _last_used_writes(conn, fn) -> int:
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        fn()
    finally:
        conn.set_trace_callback(None)
    return sum("SET last_used_at" in s for s in statements)


def test_last_used_at_written_once_per_ttl(conn, clock):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")

    def five_resolves():
        for _ in range(5):
            assert resolve_token(conn, plaintext) is not None

    assert _last_used_writes(conn, five_resolves) == 1
    clock.advance(auth.TOKEN_CACHE_TTL_S + 1)
    assert _last_used_writes(conn, five_resolves) == 1


# --- invalidation: every in-process revoke path ---------------------------------


def test_revoke_token_evicts_cached_resolution(conn):
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="t")
    assert resolve_token(conn, plaintext) is not None  # warm

    assert revoke_token(conn, token_id=token_id, user_id=u.id) is True
    assert resolve_token(conn, plaintext) is None


def test_revoke_token_evicts_cached_legacy_resolution(conn):
    u = create_user(conn, email="a@x", display_name="A")
    legacy = _insert_legacy_token(conn, user_id=u.id, token_id="tok_legacy")
    assert resolve_token(conn, legacy) is not None  # warm

    assert revoke_token(conn, token_id="tok_legacy", user_id=u.id) is True
    assert resolve_token(conn, legacy) is None


def test_revoke_token_by_non_owner_does_not_flush_cache(conn):
    """A failed revoke changes nothing, so it must not evict: otherwise any
    signed-in user could force every legacy token back onto the scan path."""
    a = create_user(conn, email="a@x", display_name="A")
    b = create_user(conn, email="b@x", display_name="B")
    token_id, plaintext = create_user_token(conn, user_id=a.id, label="t")
    resolve_token(conn, plaintext)

    assert revoke_token(conn, token_id=token_id, user_id=b.id) is False
    assert len(auth._token_cache) == 1


def test_revoke_agent_evicts_cached_agent_token(conn):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    _, plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )
    assert resolve_token(conn, plaintext) is not None  # warm

    revoke_agent(conn, agent.id, owner_user_id=u.id)
    assert resolve_token(conn, plaintext) is None


def test_invalidate_token_cache_forces_fresh_resolution(conn, uncached_spy):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    resolve_token(conn, plaintext)
    auth.invalidate_token_cache()
    resolve_token(conn, plaintext)
    assert uncached_spy.call_count == 2


def test_revoke_racing_an_in_flight_resolve_does_not_repopulate_cache(conn):
    """The resolver reads the row, then (before it returns) the token is
    revoked in another thread. The in-flight request may still succeed,
    but its result must not be cached — the NEXT request must see the
    revocation."""
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="t")
    real_build = auth._build_principal_and_touch
    fired = []

    def build_then_revoke(*args):
        principal = real_build(*args)
        if not fired:
            fired.append(True)
            assert revoke_token(conn, token_id=token_id, user_id=u.id)
        return principal

    with patch(
        "markland.service.auth._build_principal_and_touch",
        side_effect=build_then_revoke,
    ):
        # In flight across the revoke: this request still succeeds.
        assert resolve_token(conn, plaintext) is not None

    assert resolve_token(conn, plaintext) is None


# --- is_admin changes -----------------------------------------------------------


def test_out_of_process_is_admin_change_lands_within_ttl(conn, clock):
    """scripts/admin/make_admin.py runs in another process and cannot evict
    this process's cache: the flag change takes effect once the cached
    entry expires (at most TOKEN_CACHE_TTL_S later)."""
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    assert resolve_token(conn, plaintext).is_admin is False

    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (u.id,))
    conn.commit()
    assert resolve_token(conn, plaintext).is_admin is False  # cached

    clock.advance(auth.TOKEN_CACHE_TTL_S + 1)
    assert resolve_token(conn, plaintext).is_admin is True


def test_is_admin_change_is_immediate_after_invalidation(conn):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    assert resolve_token(conn, plaintext).is_admin is False

    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (u.id,))
    conn.commit()
    auth.invalidate_token_cache()
    assert resolve_token(conn, plaintext).is_admin is True


# --- the cache container itself -------------------------------------------------


def _principal(i: int) -> auth.Principal:
    return auth.Principal(
        principal_id=f"usr_{i}", principal_type="user",
        display_name=None, is_admin=False,
    )


def test_cache_entry_expires_after_ttl():
    clock = FakeClock()
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=8, clock=clock)
    cache.put(b"k", _principal(1), generation=cache.generation)
    assert cache.get(b"k") == _principal(1)
    clock.advance(59.9)
    assert cache.get(b"k") == _principal(1)
    clock.advance(0.2)
    assert cache.get(b"k") is None
    assert len(cache) == 0


def test_cache_evicts_least_recently_used_beyond_max_entries():
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=3, clock=FakeClock())
    for i in range(3):
        cache.put(bytes([i]), _principal(i), generation=cache.generation)
    assert cache.get(bytes([0])) is not None  # 0 is now most recent
    cache.put(bytes([3]), _principal(3), generation=cache.generation)

    assert len(cache) == 3
    assert cache.get(bytes([1])) is None  # least recently used went
    assert cache.get(bytes([0])) is not None
    assert cache.get(bytes([3])) is not None


def test_default_cache_bounds():
    assert auth.TOKEN_CACHE_TTL_S == 60
    assert auth._token_cache._max_entries == 1024


def test_put_with_stale_generation_is_dropped():
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=8, clock=FakeClock())
    gen = cache.generation
    cache.clear()
    cache.put(b"k", _principal(1), generation=gen)
    assert cache.get(b"k") is None


def test_cache_is_safe_under_concurrent_threads():
    cache = auth._ResolvedTokenCache(ttl_s=60, max_entries=64, clock=FakeClock())
    errors: list[BaseException] = []
    start = threading.Barrier(8)

    def worker(seed: int) -> None:
        try:
            start.wait()
            for i in range(3000):
                key = bytes([(seed * 31 + i) % 200])
                if i % 97 == 0:
                    cache.clear()
                elif i % 2:
                    cache.put(key, _principal(i), generation=cache.generation)
                else:
                    cache.get(key)
                assert len(cache) <= 64
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert len(cache) <= 64


def test_warm_resolve_from_many_threads_never_touches_argon2(
    conn, argon2_verifies, uncached_spy
):
    u = create_user(conn, email="a@x", display_name="A")
    legacy = _insert_legacy_token(conn, user_id=u.id, token_id="tok_legacy")
    expected = resolve_token(conn, legacy)
    assert argon2_verifies.call_count == 1  # the one scan that backfilled it

    results: list = []
    lock = threading.Lock()

    def worker() -> None:
        for _ in range(200):
            p = resolve_token(conn, legacy)
            with lock:
                results.append(p)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(results) == 1600
    assert all(p == expected for p in results)
    assert argon2_verifies.call_count == 1
    assert uncached_spy.call_count == 1  # every warm resolve was a cache hit
