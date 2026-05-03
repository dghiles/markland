"""Unit tests for SlidingWindowRateLimiter, especially the periodic-GC path.

Without GC, the per-IP hit dict grows unbounded with distinct keys ever seen.
GC drops keys whose most recent hit is older than the window.
"""

from __future__ import annotations

import time

from markland.web.device_routes import SlidingWindowRateLimiter


def test_check_enforces_limit_within_window():
    limiter = SlidingWindowRateLimiter(limit=3, window=60)
    for _ in range(3):
        ok, retry = limiter.check("ip1")
        assert ok is True
        assert retry == 0
    ok, retry = limiter.check("ip1")
    assert ok is False
    assert retry > 0


def test_distinct_keys_have_independent_budgets():
    limiter = SlidingWindowRateLimiter(limit=2, window=60)
    assert limiter.check("a") == (True, 0)
    assert limiter.check("a") == (True, 0)
    assert limiter.check("a")[0] is False
    # b is unaffected.
    assert limiter.check("b") == (True, 0)


def test_prune_drops_keys_with_no_recent_hits(monkeypatch):
    """After hits expire from a key's deque, _prune removes the key entirely."""
    limiter = SlidingWindowRateLimiter(limit=10, window=60)

    # 5 distinct IPs each hit once at t=0.
    fake_now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])
    for i in range(5):
        limiter.check(f"ip{i}")
    assert len(limiter._hits) == 5

    # Advance past the window. The deques still hold the old timestamp until
    # the next check trims them, so _prune must use the most recent hit's
    # age to decide.
    fake_now[0] += 120  # 2 windows later
    limiter._prune()
    assert len(limiter._hits) == 0, "all keys should have been GC'd"


def test_prune_keeps_keys_with_recent_hits(monkeypatch):
    limiter = SlidingWindowRateLimiter(limit=10, window=60)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])
    limiter.check("active")
    fake_now[0] += 30  # half a window later
    limiter._prune()
    assert "active" in limiter._hits


def test_prune_runs_automatically_after_threshold(monkeypatch):
    """Hitting `prune_every` calls triggers an automatic prune.

    Lock in that the GC actually fires from the hot path — without this, the
    leak fix is theoretical.
    """
    limiter = SlidingWindowRateLimiter(limit=100, window=60, prune_every=10)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])
    # Seed 5 keys at t=0.
    for i in range(5):
        limiter.check(f"old{i}")
    assert len(limiter._hits) == 5

    # Advance past the window so old keys are GC-eligible, then drive 10
    # checks against a fresh key to trip the auto-prune threshold.
    fake_now[0] += 120
    for _ in range(10):
        limiter.check("fresh")

    # Old keys gone, fresh remains.
    assert "fresh" in limiter._hits
    for i in range(5):
        assert f"old{i}" not in limiter._hits


def test_check_resets_prune_counter(monkeypatch):
    """After an auto-prune fires, the counter resets so the next prune is
    `prune_every` calls away — not on every subsequent call."""
    limiter = SlidingWindowRateLimiter(limit=100, window=60, prune_every=5)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])
    for _ in range(5):
        limiter.check("x")
    # Counter just reset; should be 0.
    assert limiter._calls_since_prune == 0
    limiter.check("x")
    assert limiter._calls_since_prune == 1
