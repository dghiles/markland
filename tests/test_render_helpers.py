"""Unit tests for web.render_helpers."""

from __future__ import annotations

from starlette.requests import Request

from markland.db import init_db
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.web.render_helpers import render_with_nav


SECRET = "test-session-secret"
BASE_URL = "http://testserver"


class _FakeTpl:
    """Stand-in for a Jinja Template that records its render kwargs."""

    def __init__(self):
        self.last_kwargs: dict | None = None

    def render(self, **kwargs):
        self.last_kwargs = kwargs
        return "rendered"


def _make_request(*, cookies: dict[str, str] | None = None, path: str = "/") -> Request:
    cookie_header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("ascii")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "query_string": b"",
        # Starlette derives url.scheme and url.netloc from these; without them
        # both fields are empty strings and _canonical_host would return "://".
        "scheme": "http",
        "server": ("testserver", 80),
    }
    return Request(scope)


def test_render_with_nav_injects_anon_context(tmp_path, monkeypatch):
    """All three auto-injected kwargs land for an anonymous request."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    tpl = _FakeTpl()
    req = _make_request()

    result = render_with_nav(
        tpl, req, conn, base_url=BASE_URL, secret=SECRET, foo="bar"
    )

    assert result == "rendered"
    assert tpl.last_kwargs == {
        "foo": "bar",
        "signed_in_user": None,
        "request": req,
        "canonical_host": BASE_URL,
    }


def test_render_with_nav_injects_dict_for_signed_in(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    tpl = _FakeTpl()
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    render_with_nav(tpl, req, conn, base_url=BASE_URL, secret=SECRET)

    assert tpl.last_kwargs["signed_in_user"] == {"email": "alice@example.com"}
    assert tpl.last_kwargs["request"] is req
    assert tpl.last_kwargs["canonical_host"] == BASE_URL


def test_render_with_nav_caller_kwargs_take_precedence(tmp_path, monkeypatch):
    """Explicit kwargs (signed_in_user, request, canonical_host) override
    the auto-injected ones. Cheaper than building opt-out flags."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    tpl = _FakeTpl()
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    render_with_nav(
        tpl, req, conn,
        base_url=BASE_URL, secret=SECRET,
        signed_in_user=None,
        canonical_host="https://override.example",
    )

    assert tpl.last_kwargs["signed_in_user"] is None
    assert tpl.last_kwargs["canonical_host"] == "https://override.example"
    assert tpl.last_kwargs["request"] is req  # not overridden


def test_render_with_nav_canonical_host_falls_back_to_request(tmp_path, monkeypatch):
    """When base_url is empty, derive canonical_host from the request URL.
    This mirrors the auth_routes._canonical_host() behavior PR #34 added."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    tpl = _FakeTpl()
    req = _make_request()

    render_with_nav(tpl, req, conn, base_url="", secret=SECRET)

    # The Starlette test request scope yields scheme=http, host=testserver
    # by default. Either way, canonical_host should be a non-empty string.
    assert tpl.last_kwargs["canonical_host"]
    assert tpl.last_kwargs["canonical_host"].startswith("http")


def test_render_with_nav_passes_through_other_kwargs(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    tpl = _FakeTpl()
    req = _make_request()

    render_with_nav(
        tpl, req, conn,
        base_url=BASE_URL, secret=SECRET,
        title="Hi", count=3, items=[1, 2],
    )

    assert tpl.last_kwargs["title"] == "Hi"
    assert tpl.last_kwargs["count"] == 3
    assert tpl.last_kwargs["items"] == [1, 2]
    # And the auto-injected ones are still there too.
    assert tpl.last_kwargs["signed_in_user"] is None
    assert tpl.last_kwargs["request"] is req
    assert tpl.last_kwargs["canonical_host"] == BASE_URL
