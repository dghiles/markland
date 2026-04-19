"""In-memory async token-bucket rate limiter.

Per-key bucket keyed by caller-supplied string (principal_id for authed requests,
IP for anonymous). Three tiers: user (60/min), agent (120/min), anon (20/min).
Defaults overridable via env in web/rate_limit_middleware.py.

LRU eviction: when the number of tracked keys exceeds max_keys, the least
recently checked key is dropped. Memory footprint is O(max_keys) — each entry
is two floats + a string key.

No persistence. No cross-process sharing. Process restart resets all buckets —
acceptable at ~100-user launch scale. See spec §11.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Literal

Tier = Literal["user", "agent", "anon"]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    retry_after: float  # seconds until one token is available; 0 if allowed


class RateLimiter:
    """Async-safe token bucket with LRU eviction."""

    def __init__(
        self,
        *,
        defaults: dict[str, tuple[int, int]],
        max_keys: int = 10_000,
    ) -> None:
        # defaults: tier -> (capacity, refill_period_seconds)
        self._defaults = defaults
        self._max = max_keys
        # key -> [tokens: float, last_refill: float, capacity: float, period: float]
        self._buckets: OrderedDict[str, list[float]] = OrderedDict()
        self._lock = asyncio.Lock()

    def size(self) -> int:
        return len(self._buckets)

    async def check(self, key: str, *, tier: str) -> Decision:
        capacity, period = self._defaults.get(tier) or self._defaults.get(
            "anon", (20, 60)
        )
        now = time.monotonic()
        async with self._lock:
            if key in self._buckets:
                tokens, last, cap, per = self._buckets[key]
                elapsed = max(0.0, now - last)
                refill = (elapsed / per) * cap
                tokens = min(float(cap), tokens + refill)
                self._buckets.move_to_end(key)
            else:
                tokens, cap, per = float(capacity), float(capacity), float(period)
                self._buckets[key] = [tokens, now, cap, per]
                while len(self._buckets) > self._max:
                    self._buckets.popitem(last=False)

            if tokens >= 1.0:
                tokens -= 1.0
                self._buckets[key] = [tokens, now, cap, per]
                return Decision(allowed=True, retry_after=0.0)

            needed = 1.0 - tokens
            retry = (needed / cap) * per
            self._buckets[key] = [tokens, now, cap, per]
            return Decision(allowed=False, retry_after=float(retry))
