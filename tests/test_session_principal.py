"""Unit tests for web.session_principal."""

from __future__ import annotations

from starlette.requests import Request

from markland.db import init_db
from markland.service.auth import Principal
from markland.service.sessions import SESSION_COOKIE_NAME, issue_session
from markland.service.users import create_user
from markland.service.users import User
from markland.web.session_principal import session_principal, session_user


SECRET = "test-session-secret"


def _make_request(*, cookies: dict[str, str] | None = None) -> Request:
    """Build a Starlette Request with given cookies and no body."""
    cookie_header = "; ".join(f"{k}={v}" for k, v in (cookies or {}).items())
    headers: list[tuple[bytes, bytes]] = []
    if cookie_header:
        headers.append((b"cookie", cookie_header.encode("ascii")))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": headers,
        "query_string": b"",
    }
    return Request(scope)


def test_returns_none_when_no_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    req = _make_request()
    assert session_principal(req, conn) is None


def test_returns_none_when_cookie_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    req = _make_request(cookies={SESSION_COOKIE_NAME: "garbage"})
    assert session_principal(req, conn) is None


def test_returns_none_when_user_missing(tmp_path, monkeypatch):
    """Cookie is valid but user has been deleted between requests."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    cookie = issue_session("usr_nonexistent", secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})
    assert session_principal(req, conn) is None


def test_returns_principal_for_valid_session(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="alice@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    p = session_principal(req, conn)
    assert isinstance(p, Principal)
    assert p.principal_id == user.id
    assert p.principal_type == "user"
    assert p.is_admin is False


def test_principal_carries_admin_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="root@example.com")
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user.id,))
    conn.commit()
    cookie = issue_session(user.id, secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    p = session_principal(req, conn)
    assert p is not None
    assert p.is_admin is True


def test_session_user_returns_user_for_valid_session(tmp_path, monkeypatch):
    """session_user returns the User directly so handlers that need email
    don't have to round-trip through Principal + a second get_user lookup."""
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    user = create_user(conn, email="bob@example.com")
    cookie = issue_session(user.id, secret=SECRET)
    req = _make_request(cookies={SESSION_COOKIE_NAME: cookie})

    u = session_user(req, conn)
    assert isinstance(u, User)
    assert u.id == user.id
    assert u.email == "bob@example.com"


def test_session_user_returns_none_when_invalid(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    conn = init_db(tmp_path / "t.db")
    req = _make_request(cookies={SESSION_COOKIE_NAME: "garbage"})
    assert session_user(req, conn) is None
