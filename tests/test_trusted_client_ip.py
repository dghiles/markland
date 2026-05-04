"""P2-C / markland-91j: trusted_client_ip helper.

Asserts only Fly-Client-IP and request.client.host are trusted —
X-Forwarded-For (which the edge does not rewrite) is ignored.
"""

from __future__ import annotations

from starlette.requests import Request

from markland.web._request_ip import trusted_client_ip


def _make_request(*, headers: list[tuple[bytes, bytes]] | None = None,
                  client_host: str | None = "1.2.3.4") -> Request:
    scope: dict = {
        "type": "http",
        "headers": headers or [],
        "method": "GET",
        "path": "/",
    }
    if client_host is not None:
        scope["client"] = (client_host, 12345)
    else:
        scope["client"] = None
    return Request(scope)


def test_fly_client_ip_header_is_used():
    r = _make_request(headers=[(b"fly-client-ip", b"203.0.113.7")])
    assert trusted_client_ip(r) == "203.0.113.7"


def test_fly_client_ip_takes_precedence_over_socket_peer():
    """Even when uvicorn knows the socket peer, Fly-Client-IP wins."""
    r = _make_request(headers=[(b"fly-client-ip", b"203.0.113.7")],
                      client_host="10.0.0.1")
    assert trusted_client_ip(r) == "203.0.113.7"


def test_xff_is_ignored():
    """P2-C: X-Forwarded-For is client-controlled at the edge — ignore it."""
    r = _make_request(headers=[(b"x-forwarded-for", b"6.6.6.6, 7.7.7.7")])
    assert trusted_client_ip(r) == "1.2.3.4"


def test_xff_does_not_override_fly_client_ip():
    r = _make_request(headers=[
        (b"fly-client-ip", b"203.0.113.7"),
        (b"x-forwarded-for", b"6.6.6.6"),
    ])
    assert trusted_client_ip(r) == "203.0.113.7"


def test_falls_back_to_socket_peer():
    r = _make_request(headers=[])
    assert trusted_client_ip(r) == "1.2.3.4"


def test_returns_unknown_when_no_signal():
    r = _make_request(headers=[], client_host=None)
    assert trusted_client_ip(r) == "unknown"


def test_empty_fly_header_falls_through():
    r = _make_request(headers=[(b"fly-client-ip", b"   ")])
    assert trusted_client_ip(r) == "1.2.3.4"
