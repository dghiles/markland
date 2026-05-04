"""Trusted client-IP resolution (P2-C / markland-91j).

Background: rate_limit_middleware and device_routes previously trusted the
first hop of `X-Forwarded-For`. That header is fully client-controlled when
the request enters our edge, so an attacker can spoof their key and either
evade per-IP rate limits or exhaust someone else's bucket.

Fly.io rewrites `Fly-Client-IP` on every hop, so it is the only header we
can trust for IP identity in production. Outside Fly (local dev, tests,
self-hosted deployments without an XFF-rewriting proxy) we fall back to
`request.client.host`. We never read `X-Forwarded-For` for identity.

Tests live in tests/test_trusted_client_ip.py.
"""

from __future__ import annotations

from starlette.requests import Request


def trusted_client_ip(request: Request) -> str:
    """Return a string suitable for keying per-IP buckets.

    Order:
        1. `Fly-Client-IP` header (Fly always rewrites this — safe).
        2. `request.client.host` (uvicorn-resolved socket peer).
        3. The literal string `"unknown"` if neither is available.

    `X-Forwarded-For` is intentionally NOT consulted: the first hop is
    client-supplied at the edge and trivially spoofable.
    """
    fly_ip = request.headers.get("fly-client-ip", "").strip()
    if fly_ip:
        return fly_ip
    if request.client and request.client.host:
        return request.client.host
    return "unknown"
