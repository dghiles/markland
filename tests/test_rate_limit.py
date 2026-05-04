"""Token-bucket rate limiter unit tests + middleware integration."""

import asyncio

import pytest

from markland.service.rate_limit import RateLimiter


def test_burst_allowed_up_to_limit():
    rl = RateLimiter(defaults={"user": (60, 60)}, max_keys=1000)

    async def run():
        results = []
        for _ in range(60):
            results.append(await rl.check("user:alice", tier="user"))
        return results

    results = asyncio.run(run())
    assert all(r.allowed for r in results)


def test_61st_request_returns_429_with_retry_after():
    rl = RateLimiter(defaults={"user": (60, 60)}, max_keys=1000)

    async def run():
        for _ in range(60):
            await rl.check("user:alice", tier="user")
        return await rl.check("user:alice", tier="user")

    r = asyncio.run(run())
    assert not r.allowed
    assert r.retry_after > 0
    assert r.retry_after <= 60


def test_bucket_refills_over_time(monkeypatch):
    rl = RateLimiter(defaults={"user": (2, 60)}, max_keys=1000)
    now = [1000.0]
    monkeypatch.setattr("markland.service.rate_limit.time.monotonic", lambda: now[0])

    async def run():
        assert (await rl.check("k", tier="user")).allowed
        assert (await rl.check("k", tier="user")).allowed
        assert not (await rl.check("k", tier="user")).allowed
        # Advance 30s → one token refilled (2 tokens / 60s = 1 token / 30s).
        now[0] += 30.0
        assert (await rl.check("k", tier="user")).allowed
        assert not (await rl.check("k", tier="user")).allowed

    asyncio.run(run())


def test_separate_keys_have_independent_buckets():
    rl = RateLimiter(defaults={"user": (1, 60)}, max_keys=1000)

    async def run():
        a = await rl.check("alice", tier="user")
        b = await rl.check("bob", tier="user")
        a2 = await rl.check("alice", tier="user")
        return a.allowed, b.allowed, a2.allowed

    a, b, a2 = asyncio.run(run())
    assert a is True
    assert b is True
    assert a2 is False


def test_tiers_select_correct_limits():
    rl = RateLimiter(
        defaults={"user": (60, 60), "agent": (120, 60), "anon": (20, 60)},
        max_keys=1000,
    )

    async def run():
        user_burst = [await rl.check("u", tier="user") for _ in range(61)]
        agent_burst = [await rl.check("a", tier="agent") for _ in range(121)]
        anon_burst = [await rl.check("n", tier="anon") for _ in range(21)]
        return user_burst, agent_burst, anon_burst

    u, a, n = asyncio.run(run())
    assert u[-1].allowed is False and all(x.allowed for x in u[:60])
    assert a[-1].allowed is False and all(x.allowed for x in a[:120])
    assert n[-1].allowed is False and all(x.allowed for x in n[:20])


def test_lru_eviction_triggers_beyond_max_keys():
    rl = RateLimiter(defaults={"user": (60, 60)}, max_keys=3)

    async def run():
        for k in ["a", "b", "c", "d"]:
            await rl.check(k, tier="user")
        return rl.size()

    size = asyncio.run(run())
    assert size <= 3


from fastapi.testclient import TestClient


def test_middleware_returns_429_after_user_limit(tmp_path, monkeypatch):
    from markland.db import init_db
    from markland.service.auth import create_user_token
    from markland.service.users import create_user
    from markland.web.app import create_app

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_USER_PER_MIN", "3")
    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "100")

    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@a.com", display_name="A")
    _, raw_token = create_user_token(conn, user_id=u.id, label="test")

    app = create_app(conn, mount_mcp=False, base_url="http://t")
    client = TestClient(app)

    headers = {"Authorization": f"Bearer {raw_token}"}
    codes = [client.get("/health", headers=headers).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert 429 in codes[3:]

    # 429 response must carry Retry-After.
    r = client.get("/health", headers=headers)
    if r.status_code == 429:
        assert "retry-after" in {k.lower() for k in r.headers.keys()}


def test_middleware_unauthed_uses_fly_client_ip(tmp_path, monkeypatch):
    """P2-C / markland-91j: anonymous tier keys off Fly-Client-IP, not the
    spoofable first hop of X-Forwarded-For."""
    from markland.db import init_db
    from markland.web.app import create_app

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "2")

    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://t")
    client = TestClient(app)

    headers = {"Fly-Client-IP": "1.2.3.4"}
    codes = [client.get("/health", headers=headers).status_code for _ in range(4)]
    assert codes[:2] == [200, 200]
    assert 429 in codes[2:]

    r = client.get("/health", headers={"Fly-Client-IP": "5.6.7.8"})
    assert r.status_code == 200


def test_middleware_ignores_xff_for_keying(tmp_path, monkeypatch):
    """P2-C: an attacker who controls X-Forwarded-For must NOT be able to
    masquerade as a different IP to evade or exhaust someone else's
    bucket. Without Fly-Client-IP, all such requests share request.client
    (testserver) and burn the same bucket regardless of XFF spoofing."""
    from markland.db import init_db
    from markland.web.app import create_app

    monkeypatch.setenv("MARKLAND_RATE_LIMIT_ANON_PER_MIN", "2")

    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, mount_mcp=False, base_url="http://t")
    client = TestClient(app)

    # Burn the budget by spamming 'attacker'.
    for _ in range(3):
        client.get("/health", headers={"X-Forwarded-For": "1.1.1.1"})

    # Now claim to be a different IP — should still be rate-limited
    # because XFF is ignored and the underlying request.client is shared.
    r = client.get("/health", headers={"X-Forwarded-For": "9.9.9.9"})
    assert r.status_code == 429


def test_unknown_tier_falls_back_to_anon():
    rl = RateLimiter(defaults={"anon": (1, 60)}, max_keys=1000)

    async def run():
        r1 = await rl.check("x", tier="mystery")
        r2 = await rl.check("x", tier="mystery")
        return r1.allowed, r2.allowed

    a, b = asyncio.run(run())
    assert a is True
    assert b is False
