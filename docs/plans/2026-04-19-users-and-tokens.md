# Users and Tokens — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Replace the single hardcoded admin bearer token from Plan 1 with real user identity. Users sign in via magic link (email → signed 15-min single-use token → session cookie). Authenticated users create named API tokens on `/settings/tokens` — those are the bearer tokens that now gate `/mcp`. Every MCP request resolves to a `Principal` (currently always a user) attached to `request.state.principal`. Docs remain owner-less for now; anyone authenticated can call any existing doc tool. Ends with a usable hosted single-user (soon multi-user) experience.

**Architecture:** A `users` table stores accounts (id, email, display_name, is_admin). A `tokens` table stores argon2id-hashed bearer tokens tied to a principal (currently only `principal_type='user'`; `'agent'` is reserved for Plan 4). Magic-link sign-in uses `itsdangerous` to issue a single-use 15-minute signed token delivered via the existing `EmailClient`. Sessions are `itsdangerous`-signed cookies (`mk_session`) carrying `{user_id, exp}` for a 30-day lifetime. A new `PrincipalMiddleware` replaces `AdminBearerMiddleware` on `/mcp`: it reads `Authorization: Bearer mk_usr_<…>`, hashes/looks up the token, attaches `request.state.principal`, and 401s otherwise. Web-session routes (`/api/auth/*`, `/api/me`, `/api/tokens`) are auth'd via the session cookie, not the bearer. A `markland_whoami` MCP tool echoes the principal.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, SQLite (existing), `argon2-cffi>=23.1.0`, `itsdangerous>=2.2.0`, Resend (via existing `EmailClient`), Jinja2 (existing).

**Scope excluded (this plan):**
- Doc ownership and `owner_id` column (Plan 3)
- Grants table + `markland_grant`/`markland_revoke`/`markland_list_grants` (Plan 3)
- Agents table + agent tokens + `/settings/agents` (Plan 4)
- Invite links (Plan 5)
- Device flow for CLI onboarding (Plan 6)
- Email notification triggers beyond the magic-link email (Plan 7)
- Conflict handling / `version` column / `revisions` (Plan 8)
- Presence (Plan 9)
- Rate limiting, audit log, `/explore` auth-context polish (Plan 10)

**Operator runbook addition (documented in Task 14):** `MARKLAND_SESSION_SECRET` must be set in Fly secrets for the hosted deployment. Rotating this secret invalidates all existing session cookies (users are signed out; API tokens unaffected).

---

## File Structure

**New files:**
- `src/markland/service/auth.py` — argon2id token hash/verify, `create_user_token`, `resolve_token`, `revoke_token`, `list_tokens`, `Principal` dataclass
- `src/markland/service/sessions.py` — `itsdangerous` signed-cookie helpers (`issue_session`, `read_session`)
- `src/markland/service/magic_link.py` — signed magic-link token helpers + `send_magic_link` (calls `EmailClient`)
- `src/markland/service/users.py` — `create_user`, `get_user`, `get_user_by_email`, `upsert_user_by_email` (used by magic-link verify)
- `src/markland/web/principal_middleware.py` — new `PrincipalMiddleware`, replaces `AdminBearerMiddleware` on `/mcp`
- `src/markland/web/auth_routes.py` — `/api/auth/magic-link`, `/api/auth/verify`, `/api/auth/logout`, `/login`, `/verify`
- `src/markland/web/identity_routes.py` — `/api/me`, `POST /api/tokens`, `DELETE /api/tokens/{id}`, `/settings/tokens`
- `src/markland/web/templates/login.html` — magic-link request form
- `src/markland/web/templates/verify_sent.html` — "check your email" confirmation page
- `src/markland/web/templates/settings_tokens.html` — list/create/revoke tokens
- `tests/test_db_users_tokens.py` — schema migration test for `users` + `tokens`
- `tests/test_service_auth.py` — unit tests for hash/verify/create/resolve/revoke/list
- `tests/test_service_sessions.py` — unit tests for signed-cookie round-trip
- `tests/test_service_magic_link.py` — unit tests for magic-link token round-trip + send
- `tests/test_auth_routes.py` — route tests for magic-link/verify/logout
- `tests/test_identity_routes.py` — route tests for `/api/me` + `/api/tokens`
- `tests/test_principal_middleware.py` — unit tests for principal resolution middleware
- `tests/test_whoami_smoke.py` — end-to-end: user → token → `/mcp` → `markland_whoami`

**Modified files:**
- `pyproject.toml` — add `argon2-cffi>=23.1.0`, `itsdangerous>=2.2.0`
- `.env.example` — add `MARKLAND_SESSION_SECRET`
- `src/markland/config.py` — add `session_secret` field
- `src/markland/db.py` — add `users` + `tokens` table creation in `init_db`
- `src/markland/web/app.py` — swap `AdminBearerMiddleware` → `PrincipalMiddleware`; wire session_secret; include new routers
- `src/markland/server.py` — register `markland_whoami`, gate `markland_feature` on `principal.is_admin`
- `src/markland/run_app.py` — pass `session_secret` to `create_app`
- `docs/runbooks/first-deploy.md` — add `MARKLAND_SESSION_SECRET` to the `flyctl secrets set` step

**Unchanged:** All existing doc-CRUD logic, templates (landing/explore/document), `service/email.py`.

---

## Task 1: Dependencies + session secret config

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`
- Modify: `src/markland/config.py`
- Modify: `tests/test_config.py` (add session-secret assertions)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py`:

```python
def test_session_secret_loaded_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", "s3cret_test_value")
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.session_secret == "s3cret_test_value"


def test_session_secret_empty_when_unset(monkeypatch, tmp_path):
    monkeypatch.delenv("MARKLAND_SESSION_SECRET", raising=False)
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    cfg = get_config()
    assert cfg.session_secret == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL — `Config` has no `session_secret` attribute.

- [ ] **Step 3: Add dependencies**

Modify `pyproject.toml`'s `dependencies` list — insert after the `resend` line:

```toml
    "resend>=2.5.0",
    "argon2-cffi>=23.1.0",
    "itsdangerous>=2.2.0",
```

- [ ] **Step 4: Install**

Run: `uv sync --all-extras`
Expected: resolves and installs cleanly.

- [ ] **Step 5: Update `src/markland/config.py`**

Replace the full file with:

```python
"""Environment-based configuration for Markland."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    base_url: str
    data_dir: Path
    web_port: int
    admin_token: str
    sentry_dsn: str
    resend_api_key: str
    resend_from_email: str
    session_secret: str

    @property
    def db_path(self) -> Path:
        return self.data_dir / "markland.db"


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        data_dir_env = os.getenv("MARKLAND_DATA_DIR", "").strip()
        data_dir = Path(data_dir_env).expanduser() if data_dir_env else Path.home() / ".markland"
        data_dir.mkdir(parents=True, exist_ok=True)
        _config = Config(
            base_url=os.getenv("MARKLAND_BASE_URL", "http://localhost:8950").rstrip("/"),
            data_dir=data_dir,
            web_port=int(os.getenv("MARKLAND_WEB_PORT", "8950")),
            admin_token=os.getenv("MARKLAND_ADMIN_TOKEN", "").strip(),
            sentry_dsn=os.getenv("SENTRY_DSN", "").strip(),
            resend_api_key=os.getenv("RESEND_API_KEY", "").strip(),
            resend_from_email=os.getenv("RESEND_FROM_EMAIL", "notifications@markland.dev").strip(),
            session_secret=os.getenv("MARKLAND_SESSION_SECRET", "").strip(),
        )
    return _config


def reset_config() -> None:
    """Reset cached config (for tests)."""
    global _config
    _config = None
```

- [ ] **Step 6: Update `.env.example`**

Append to `.env.example`:

```
# Secret for signing session cookies and magic-link tokens. MUST be set in production.
# Generate: python -c "import secrets; print(secrets.token_urlsafe(48))"
# Rotating this secret signs out all users immediately.
MARKLAND_SESSION_SECRET=
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS.

---

## Task 2: `users` and `tokens` tables

**Files:**
- Modify: `src/markland/db.py`
- Create: `tests/test_db_users_tokens.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_db_users_tokens.py`:

```python
"""Schema tests for users and tokens tables."""

from markland.db import init_db


def _columns(conn, table: str) -> dict[str, str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {r[1]: r[2] for r in rows}


def _indexes(conn, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA index_list({table})").fetchall()
    return {r[1] for r in rows}


def test_users_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = _columns(conn, "users")
    assert set(cols) == {"id", "email", "display_name", "is_admin", "created_at"}
    assert cols["id"] == "TEXT"
    assert cols["email"] == "TEXT"
    assert cols["is_admin"] == "INTEGER"


def test_users_email_is_unique(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
        ("usr_a", "a@example.com", "A", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    import sqlite3
    try:
        conn.execute(
            "INSERT INTO users (id, email, display_name, is_admin, created_at) VALUES (?, ?, ?, 0, ?)",
            ("usr_b", "a@example.com", "B", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
        raise AssertionError("expected UNIQUE violation on users.email")
    except sqlite3.IntegrityError:
        pass


def test_tokens_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = _columns(conn, "tokens")
    assert set(cols) == {
        "id",
        "token_hash",
        "label",
        "principal_type",
        "principal_id",
        "created_at",
        "last_used_at",
        "revoked_at",
    }


def test_tokens_has_token_hash_index(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert "idx_token_hash" in _indexes(conn, "tokens")


def test_is_admin_defaults_to_zero(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, created_at) VALUES (?, ?, ?, ?)",
        ("usr_x", "x@example.com", "X", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", ("usr_x",)).fetchone()
    assert row[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db_users_tokens.py -v`
Expected: FAIL — tables don't exist.

- [ ] **Step 3: Extend `init_db`**

Modify `src/markland/db.py` — inside `init_db`, after the documents-table block but before `conn.commit()`, add:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            display_name TEXT,
            is_admin INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tokens (
            id TEXT PRIMARY KEY,
            token_hash TEXT NOT NULL,
            label TEXT,
            principal_type TEXT NOT NULL,
            principal_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            revoked_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_hash ON tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id)")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_db_users_tokens.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Run full suite**

Run: `uv run pytest tests/ -v`
Expected: all tests still pass.

---

## Task 3: `service/users.py` — user CRUD

**Files:**
- Create: `src/markland/service/users.py`
- Create: `tests/test_service_users.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_users.py`:

```python
"""Tests for the users service layer."""

from markland.db import init_db
from markland.service.users import (
    User,
    create_user,
    get_user,
    get_user_by_email,
    upsert_user_by_email,
)


def test_create_user_roundtrip(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    assert u.id.startswith("usr_")
    assert u.email == "alice@example.com"
    assert u.display_name == "Alice"
    assert u.is_admin is False
    fetched = get_user(conn, u.id)
    assert fetched == u


def test_get_user_by_email_case_insensitive(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="Bob@Example.com", display_name="Bob")
    assert get_user_by_email(conn, "bob@example.com") == u
    assert get_user_by_email(conn, "BOB@EXAMPLE.COM") == u


def test_get_user_returns_none_for_missing(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert get_user(conn, "usr_missing") is None
    assert get_user_by_email(conn, "none@example.com") is None


def test_upsert_user_by_email_creates_when_absent(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = upsert_user_by_email(conn, "new@example.com")
    assert u.email == "new@example.com"
    assert get_user_by_email(conn, "new@example.com") == u


def test_upsert_user_by_email_returns_existing(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = create_user(conn, email="carol@example.com", display_name="Carol")
    b = upsert_user_by_email(conn, "CAROL@example.com")
    assert b.id == a.id
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_users.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `service/users.py`**

Create `src/markland/service/users.py`:

```python
"""User account operations."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class User:
    id: str
    email: str
    display_name: str | None
    is_admin: bool
    created_at: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_user_id() -> str:
    return f"usr_{secrets.token_hex(8)}"


def _row_to_user(row: tuple) -> User:
    return User(
        id=row[0],
        email=row[1],
        display_name=row[2],
        is_admin=bool(row[3]),
        created_at=row[4],
    )


_COLS = "id, email, display_name, is_admin, created_at"


def create_user(
    conn: sqlite3.Connection,
    *,
    email: str,
    display_name: str | None = None,
) -> User:
    """Insert a new user. Email stored lowercased."""
    user = User(
        id=_generate_user_id(),
        email=email.strip().lower(),
        display_name=display_name,
        is_admin=False,
        created_at=_now(),
    )
    conn.execute(
        f"INSERT INTO users ({_COLS}) VALUES (?, ?, ?, ?, ?)",
        (user.id, user.email, user.display_name, 0, user.created_at),
    )
    conn.commit()
    return user


def get_user(conn: sqlite3.Connection, user_id: str) -> User | None:
    row = conn.execute(
        f"SELECT {_COLS} FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_email(conn: sqlite3.Connection, email: str) -> User | None:
    row = conn.execute(
        f"SELECT {_COLS} FROM users WHERE email = ?", (email.strip().lower(),)
    ).fetchone()
    return _row_to_user(row) if row else None


def upsert_user_by_email(
    conn: sqlite3.Connection,
    email: str,
    *,
    display_name: str | None = None,
) -> User:
    """Return the existing user with this email, or create one."""
    existing = get_user_by_email(conn, email)
    if existing is not None:
        return existing
    return create_user(conn, email=email, display_name=display_name)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_users.py -v`
Expected: PASS (5 tests).

---

## Task 4: `service/auth.py` — hash + verify token

**Files:**
- Create: `src/markland/service/auth.py` (initial version, hash/verify only)
- Create: `tests/test_service_auth.py` (hash/verify tests)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_auth.py`:

```python
"""Tests for service/auth.py — token hashing, creation, resolution."""

import pytest

from markland.db import init_db
from markland.service.auth import (
    Principal,
    create_user_token,
    hash_token,
    list_tokens,
    resolve_token,
    revoke_token,
    verify_token,
)
from markland.service.users import create_user


def test_hash_token_produces_argon2id_encoded_string():
    h = hash_token("mk_usr_abc123")
    assert h.startswith("$argon2id$")
    # Non-deterministic (random salt)
    assert hash_token("mk_usr_abc123") != h


def test_verify_token_accepts_match():
    h = hash_token("mk_usr_abc123")
    assert verify_token("mk_usr_abc123", h) is True


def test_verify_token_rejects_mismatch():
    h = hash_token("mk_usr_abc123")
    assert verify_token("mk_usr_wrong", h) is False


def test_verify_token_rejects_garbage_hash():
    assert verify_token("mk_usr_abc", "not-a-hash") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_auth.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement the hash/verify half of `service/auth.py`**

Create `src/markland/service/auth.py`:

```python
"""Token hashing, principal resolution, and per-user token lifecycle."""

from __future__ import annotations

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Default Argon2PasswordHasher parameters (per spec §4: argon2id; no custom params).
_hasher = PasswordHasher()


@dataclass(frozen=True)
class Principal:
    """Resolved identity attached to an authenticated request.

    principal_type is 'user' today; 'agent' is reserved for Plan 4.
    user_id is None for users; for agents it will be the owning user_id.
    """

    principal_id: str
    principal_type: str
    display_name: str | None
    is_admin: bool
    user_id: str | None = None


@dataclass(frozen=True)
class TokenRecord:
    id: str
    label: str | None
    principal_type: str
    principal_id: str
    created_at: str
    last_used_at: str | None
    revoked_at: str | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_token_id() -> str:
    return f"tok_{secrets.token_hex(8)}"


def _generate_user_token_plaintext() -> str:
    return f"mk_usr_{secrets.token_urlsafe(32)}"


def hash_token(plaintext: str) -> str:
    """Argon2id-hash a token. Salt is randomly generated per call."""
    return _hasher.hash(plaintext)


def verify_token(plaintext: str, hashed: str) -> bool:
    """Return True iff `plaintext` matches `hashed`. Safe on malformed hashes."""
    try:
        return _hasher.verify(hashed, plaintext)
    except (VerifyMismatchError, InvalidHashError):
        return False
    except Exception:
        return False


def create_user_token(
    conn: sqlite3.Connection,
    *,
    user_id: str,
    label: str,
) -> tuple[str, str]:
    """Create a new user token. Returns (token_id, plaintext).

    The plaintext is shown to the user ONCE and never persisted — only its hash.
    """
    plaintext = _generate_user_token_plaintext()
    token_id = _generate_token_id()
    hashed = hash_token(plaintext)
    conn.execute(
        """
        INSERT INTO tokens (
            id, token_hash, label, principal_type, principal_id,
            created_at, last_used_at, revoked_at
        ) VALUES (?, ?, ?, 'user', ?, ?, NULL, NULL)
        """,
        (token_id, hashed, label, user_id, _now()),
    )
    conn.commit()
    return token_id, plaintext


def resolve_token(conn: sqlite3.Connection, plaintext: str) -> Principal | None:
    """Find the token row whose hash matches `plaintext`, return its principal.

    Scans non-revoked tokens; argon2 verify per row. At 100-user scale with <1k
    total tokens this is fine; a per-request cache is a Plan 10 concern.
    """
    if not plaintext:
        return None
    rows = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE revoked_at IS NULL
        """
    ).fetchall()
    for token_id, token_hash, principal_type, principal_id in rows:
        if verify_token(plaintext, token_hash):
            if principal_type == "user":
                user_row = conn.execute(
                    "SELECT id, display_name, is_admin FROM users WHERE id = ?",
                    (principal_id,),
                ).fetchone()
                if user_row is None:
                    return None
                # Fire-and-forget update of last_used_at. Failure must not block auth.
                try:
                    conn.execute(
                        "UPDATE tokens SET last_used_at = ? WHERE id = ?",
                        (_now(), token_id),
                    )
                    conn.commit()
                except sqlite3.Error:
                    pass
                return Principal(
                    principal_id=user_row[0],
                    principal_type="user",
                    display_name=user_row[1],
                    is_admin=bool(user_row[2]),
                    user_id=None,
                )
            # 'agent' principals reserved for Plan 4
            return None
    return None


def revoke_token(
    conn: sqlite3.Connection,
    *,
    token_id: str,
    user_id: str,
) -> bool:
    """Revoke `token_id` iff it belongs to `user_id`. Returns True on success."""
    cursor = conn.execute(
        """
        UPDATE tokens
        SET revoked_at = ?
        WHERE id = ? AND principal_type = 'user' AND principal_id = ? AND revoked_at IS NULL
        """,
        (_now(), token_id, user_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def list_tokens(conn: sqlite3.Connection, *, user_id: str) -> list[TokenRecord]:
    """List this user's non-revoked tokens, newest first."""
    rows = conn.execute(
        """
        SELECT id, label, principal_type, principal_id, created_at, last_used_at, revoked_at
        FROM tokens
        WHERE principal_type = 'user' AND principal_id = ? AND revoked_at IS NULL
        ORDER BY created_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [
        TokenRecord(
            id=r[0],
            label=r[1],
            principal_type=r[2],
            principal_id=r[3],
            created_at=r[4],
            last_used_at=r[5],
            revoked_at=r[6],
        )
        for r in rows
    ]
```

- [ ] **Step 4: Run hash/verify tests**

Run: `uv run pytest tests/test_service_auth.py::test_hash_token_produces_argon2id_encoded_string tests/test_service_auth.py::test_verify_token_accepts_match tests/test_service_auth.py::test_verify_token_rejects_mismatch tests/test_service_auth.py::test_verify_token_rejects_garbage_hash -v`
Expected: PASS (4 tests).

---

## Task 5: `service/auth.py` — create + resolve token

**Files:**
- Modify: `tests/test_service_auth.py` (add create/resolve tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_service_auth.py`:

```python
def test_create_user_token_returns_plaintext_with_mk_usr_prefix(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    assert token_id.startswith("tok_")
    assert plaintext.startswith("mk_usr_")
    assert len(plaintext) >= 30


def test_resolve_token_returns_principal_for_valid_token(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    _, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    principal = resolve_token(conn, plaintext)
    assert principal is not None
    assert principal.principal_id == u.id
    assert principal.principal_type == "user"
    assert principal.display_name == "Alice"
    assert principal.is_admin is False


def test_resolve_token_returns_none_for_unknown(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert resolve_token(conn, "mk_usr_does_not_exist") is None


def test_resolve_token_returns_none_for_empty(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert resolve_token(conn, "") is None


def test_resolve_token_updates_last_used_at(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    assert conn.execute("SELECT last_used_at FROM tokens WHERE id = ?", (token_id,)).fetchone()[0] is None
    resolve_token(conn, plaintext)
    assert conn.execute("SELECT last_used_at FROM tokens WHERE id = ?", (token_id,)).fetchone()[0] is not None


def test_resolve_token_returns_admin_flag(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="op@example.com", display_name="Op")
    conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (u.id,))
    conn.commit()
    _, plaintext = create_user_token(conn, user_id=u.id, label="ops")
    principal = resolve_token(conn, plaintext)
    assert principal is not None and principal.is_admin is True
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_service_auth.py -v`
Expected: PASS (all tests including the new six).

---

## Task 6: `service/auth.py` — revoke + list

**Files:**
- Modify: `tests/test_service_auth.py` (add revoke/list tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_service_auth.py`:

```python
def test_revoke_token_succeeds_for_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="laptop")
    assert revoke_token(conn, token_id=token_id, user_id=u.id) is True
    assert resolve_token(conn, plaintext) is None


def test_revoke_token_refuses_non_owner(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = create_user(conn, email="alice@example.com", display_name="Alice")
    b = create_user(conn, email="bob@example.com", display_name="Bob")
    token_id, plaintext = create_user_token(conn, user_id=a.id, label="laptop")
    assert revoke_token(conn, token_id=token_id, user_id=b.id) is False
    # Alice's token still resolves
    assert resolve_token(conn, plaintext) is not None


def test_revoke_already_revoked_is_false(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="Alice")
    token_id, _ = create_user_token(conn, user_id=u.id, label="l")
    assert revoke_token(conn, token_id=token_id, user_id=u.id) is True
    assert revoke_token(conn, token_id=token_id, user_id=u.id) is False


def test_list_tokens_returns_only_user_tokens(tmp_path):
    conn = init_db(tmp_path / "t.db")
    a = create_user(conn, email="alice@example.com", display_name="A")
    b = create_user(conn, email="bob@example.com", display_name="B")
    create_user_token(conn, user_id=a.id, label="a1")
    create_user_token(conn, user_id=a.id, label="a2")
    create_user_token(conn, user_id=b.id, label="b1")
    rows = list_tokens(conn, user_id=a.id)
    labels = {r.label for r in rows}
    assert labels == {"a1", "a2"}


def test_list_tokens_excludes_revoked(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="alice@example.com", display_name="A")
    tid1, _ = create_user_token(conn, user_id=u.id, label="k1")
    create_user_token(conn, user_id=u.id, label="k2")
    revoke_token(conn, token_id=tid1, user_id=u.id)
    assert {r.label for r in list_tokens(conn, user_id=u.id)} == {"k2"}
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_service_auth.py -v`
Expected: PASS (all tests including the new five).

---

## Task 7: `service/sessions.py` — signed session cookies

**Files:**
- Create: `src/markland/service/sessions.py`
- Create: `tests/test_service_sessions.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_sessions.py`:

```python
"""Tests for itsdangerous-backed session cookies."""

import time

import pytest

from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    InvalidSession,
    issue_session,
    read_session,
)


def test_cookie_constants():
    assert SESSION_COOKIE_NAME == "mk_session"
    assert SESSION_MAX_AGE_SECONDS == 60 * 60 * 24 * 30  # 30 days


def test_issue_and_read_roundtrip():
    token = issue_session("usr_abc", secret="topsecret")
    payload = read_session(token, secret="topsecret")
    assert payload["user_id"] == "usr_abc"
    assert "exp" in payload


def test_read_rejects_wrong_secret():
    token = issue_session("usr_abc", secret="topsecret")
    with pytest.raises(InvalidSession):
        read_session(token, secret="wrong")


def test_read_rejects_tampered_token():
    token = issue_session("usr_abc", secret="topsecret")
    tampered = token[:-4] + "XXXX" if len(token) > 4 else "bad"
    with pytest.raises(InvalidSession):
        read_session(tampered, secret="topsecret")


def test_read_rejects_expired(monkeypatch):
    token = issue_session("usr_abc", secret="topsecret", max_age_seconds=1)
    time.sleep(2)
    with pytest.raises(InvalidSession):
        read_session(token, secret="topsecret", max_age_seconds=1)


def test_empty_secret_refuses_to_issue():
    with pytest.raises(ValueError):
        issue_session("usr_abc", secret="")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_sessions.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `service/sessions.py`**

Create `src/markland/service/sessions.py`:

```python
"""Signed session cookies via itsdangerous.

Cookie name: `mk_session`. Payload: `{"user_id": str, "exp": iso8601}`.
Signed with `MARKLAND_SESSION_SECRET`. 30-day default lifetime.
Rotating the secret invalidates all outstanding sessions.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from itsdangerous.serializer import Serializer

SESSION_COOKIE_NAME = "mk_session"
SESSION_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days
_SALT = "mk.session.v1"


class InvalidSession(Exception):
    """Raised when a session cookie is missing, tampered, or expired."""


def _signer(secret: str) -> TimestampSigner:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return TimestampSigner(secret, salt=_SALT)


def issue_session(
    user_id: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
) -> str:
    """Return a signed cookie value for `user_id`."""
    if not secret:
        raise ValueError("session secret must be non-empty")
    serializer = Serializer(secret, salt=_SALT)
    exp = (datetime.now(timezone.utc) + timedelta(seconds=max_age_seconds)).isoformat()
    raw = serializer.dumps({"user_id": user_id, "exp": exp})
    # Add timestamp signing on top so we can enforce max_age at verify time.
    return _signer(secret).sign(raw.encode("utf-8")).decode("utf-8")


def read_session(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = SESSION_MAX_AGE_SECONDS,
) -> dict:
    """Parse a cookie value. Raises `InvalidSession` on any failure."""
    if not token:
        raise InvalidSession("empty session token")
    try:
        unsigned = _signer(secret).unsign(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidSession("session expired") from e
    except BadSignature as e:
        raise InvalidSession("bad signature") from e
    try:
        serializer = Serializer(secret, salt=_SALT)
        payload = serializer.loads(unsigned.decode("utf-8"))
    except BadSignature as e:
        raise InvalidSession("bad payload") from e
    if not isinstance(payload, dict) or "user_id" not in payload:
        raise InvalidSession("malformed payload")
    return payload
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_sessions.py -v`
Expected: PASS (6 tests).

---

## Task 8: `service/magic_link.py` — signed single-use login token

**Files:**
- Create: `src/markland/service/magic_link.py`
- Create: `tests/test_service_magic_link.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_magic_link.py`:

```python
"""Tests for magic-link token issuance + verification + email delivery."""

import time
from unittest.mock import MagicMock

import pytest

from markland.service.magic_link import (
    MAGIC_LINK_MAX_AGE_SECONDS,
    InvalidMagicLink,
    issue_magic_link_token,
    read_magic_link_token,
    send_magic_link,
)


def test_max_age_is_15_minutes():
    assert MAGIC_LINK_MAX_AGE_SECONDS == 15 * 60


def test_issue_and_read_roundtrip():
    token = issue_magic_link_token("alice@example.com", secret="s")
    email = read_magic_link_token(token, secret="s")
    assert email == "alice@example.com"


def test_read_rejects_wrong_secret():
    token = issue_magic_link_token("alice@example.com", secret="s")
    with pytest.raises(InvalidMagicLink):
        read_magic_link_token(token, secret="other")


def test_read_rejects_expired():
    token = issue_magic_link_token("alice@example.com", secret="s", max_age_seconds=1)
    time.sleep(2)
    with pytest.raises(InvalidMagicLink):
        read_magic_link_token(token, secret="s", max_age_seconds=1)


def test_send_magic_link_composes_url_and_calls_client():
    email_client = MagicMock()
    email_client.send.return_value = "email_abc"
    token = send_magic_link(
        email="alice@example.com",
        secret="s",
        base_url="https://markland.dev",
        email_client=email_client,
    )
    assert isinstance(token, str) and len(token) > 10
    args, kwargs = email_client.send.call_args
    sent = kwargs if kwargs else {}
    # Client called with to/subject/html
    assert sent["to"] == "alice@example.com"
    assert "Markland" in sent["subject"]
    assert "https://markland.dev/verify?token=" in sent["html"]


def test_send_magic_link_normalizes_email():
    email_client = MagicMock()
    email_client.send.return_value = None
    send_magic_link(
        email="  Alice@Example.COM  ",
        secret="s",
        base_url="https://markland.dev",
        email_client=email_client,
    )
    sent_kwargs = email_client.send.call_args.kwargs
    assert sent_kwargs["to"] == "alice@example.com"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_magic_link.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `service/magic_link.py`**

Create `src/markland/service/magic_link.py`:

```python
"""Magic-link login: itsdangerous-signed single-use tokens, delivered by EmailClient.

Token carries the target email; validity = 15 minutes. "Single-use" is enforced at
the verify route by issuing a session immediately on first success; the token itself
has no server-side state (the 15-minute expiry is the belt-and-braces).
"""

from __future__ import annotations

from urllib.parse import urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from markland.service.email import EmailClient

MAGIC_LINK_MAX_AGE_SECONDS = 15 * 60
_SALT = "mk.magiclink.v1"


class InvalidMagicLink(Exception):
    """Raised when a magic-link token is missing, tampered, or expired."""


def _serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise ValueError("session secret must be non-empty")
    return URLSafeTimedSerializer(secret, salt=_SALT)


def issue_magic_link_token(
    email: str,
    *,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,  # kept for symmetry; serializer ignores
) -> str:
    """Sign a token carrying this email."""
    return _serializer(secret).dumps(email.strip().lower())


def read_magic_link_token(
    token: str,
    *,
    secret: str,
    max_age_seconds: int = MAGIC_LINK_MAX_AGE_SECONDS,
) -> str:
    """Return the email encoded in `token`. Raises `InvalidMagicLink`."""
    try:
        return _serializer(secret).loads(token, max_age=max_age_seconds)
    except SignatureExpired as e:
        raise InvalidMagicLink("magic link expired") from e
    except BadSignature as e:
        raise InvalidMagicLink("invalid magic link") from e


def send_magic_link(
    *,
    email: str,
    secret: str,
    base_url: str,
    email_client: EmailClient,
) -> str:
    """Issue a magic-link token, email it to `email`, return the token for testing.

    Email send failure is propagated (EmailClient may raise EmailSendError); the
    route handler decides whether that bubbles up as a 500 or is logged silently.
    """
    normalized = email.strip().lower()
    token = issue_magic_link_token(normalized, secret=secret)
    verify_url = f"{base_url.rstrip('/')}/verify?" + urlencode({"token": token})
    subject = "Your Markland login link"
    html = (
        "<p>Click the link below to sign in to Markland. "
        "It expires in 15 minutes and can only be used once.</p>"
        f'<p><a href="{verify_url}">{verify_url}</a></p>'
        "<p>If you didn't request this, ignore this email.</p>"
    )
    email_client.send(to=normalized, subject=subject, html=html)
    return token
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_magic_link.py -v`
Expected: PASS (6 tests).

---

## Task 9: `PrincipalMiddleware` replacing `AdminBearerMiddleware`

**Files:**
- Create: `src/markland/web/principal_middleware.py`
- Create: `tests/test_principal_middleware.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_principal_middleware.py`:

```python
"""Tests for PrincipalMiddleware — bearer-token → request.state.principal on /mcp."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.principal_middleware import PrincipalMiddleware


def _app(conn):
    app = FastAPI()
    app.add_middleware(PrincipalMiddleware, db_conn=conn, protected_prefix="/mcp")

    @app.get("/mcp/ping")
    def mcp_ping(request: Request):
        p = request.state.principal
        return JSONResponse({"id": p.principal_id, "type": p.principal_type})

    @app.get("/public")
    def public():
        return JSONResponse({"ok": True})

    return app


def test_public_path_does_not_require_token(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    assert client.get("/public").status_code == 200


def test_missing_auth_header_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthenticated"}


def test_malformed_auth_header_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": "nonsense"})
    assert r.status_code == 401


def test_unknown_token_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": "Bearer mk_usr_unknown"})
    assert r.status_code == 401


def test_revoked_token_returns_401(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@example.com", display_name="A")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="l")
    from markland.service.auth import revoke_token
    revoke_token(conn, token_id=token_id, user_id=u.id)
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 401


def test_valid_token_attaches_principal(tmp_path):
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@example.com", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="l")
    client = TestClient(_app(conn))
    r = client.get("/mcp/ping", headers={"Authorization": f"Bearer {plaintext}"})
    assert r.status_code == 200
    assert r.json() == {"id": u.id, "type": "user"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_principal_middleware.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement `PrincipalMiddleware`**

Create `src/markland/web/principal_middleware.py`:

```python
"""Middleware that resolves Bearer tokens to Principals on protected paths.

Replaces the Plan-1 `AdminBearerMiddleware`. On a request under `protected_prefix`:
  1. Extract `Authorization: Bearer <token>`.
  2. Call `service.auth.resolve_token`.
  3. On success, attach the `Principal` to `request.state.principal`.
  4. On any failure (no header, malformed header, unknown/revoked token) return 401.
"""

from __future__ import annotations

import sqlite3

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from markland.service.auth import resolve_token


class PrincipalMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        db_conn: sqlite3.Connection,
        protected_prefix: str = "/mcp",
    ) -> None:
        super().__init__(app)
        self._conn = db_conn
        self._prefix = protected_prefix

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self._prefix):
            return await call_next(request)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        plaintext = header[7:].strip()
        principal = resolve_token(self._conn, plaintext)
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        request.state.principal = principal
        return await call_next(request)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_principal_middleware.py -v`
Expected: PASS (6 tests).

---

## Task 10: Auth routes — `/api/auth/magic-link`, `/api/auth/verify`, `/api/auth/logout`, `/login`, `/verify`

**Files:**
- Create: `src/markland/web/auth_routes.py`
- Create: `src/markland/web/templates/login.html`
- Create: `src/markland/web/templates/verify_sent.html`
- Create: `tests/test_auth_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_routes.py`:

```python
"""Route tests for magic-link login flow."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.magic_link import issue_magic_link_token
from markland.service.sessions import SESSION_COOKIE_NAME
from markland.service.users import get_user_by_email
from markland.web.app import create_app


@pytest.fixture
def client_and_conn(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    email_client = MagicMock()
    email_client.send.return_value = None
    app = create_app(
        conn,
        mount_mcp=False,
        admin_token="",
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    with TestClient(app) as c:
        yield c, conn, email_client


def test_login_page_renders(client_and_conn):
    client, _, _ = client_and_conn
    r = client.get("/login")
    assert r.status_code == 200
    assert "magic link" in r.text.lower() or "email" in r.text.lower()


def test_post_magic_link_sends_email(client_and_conn):
    client, _, email_client = client_and_conn
    r = client.post("/api/auth/magic-link", json={"email": "alice@example.com"})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    email_client.send.assert_called_once()


def test_post_magic_link_rejects_missing_email(client_and_conn):
    client, _, _ = client_and_conn
    r = client.post("/api/auth/magic-link", json={})
    assert r.status_code == 400


def test_verify_with_valid_token_creates_user_and_session(client_and_conn):
    client, conn, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert SESSION_COOKIE_NAME in r.cookies
    assert get_user_by_email(conn, "alice@example.com") is not None


def test_verify_with_bad_token_returns_400(client_and_conn):
    client, _, _ = client_and_conn
    r = client.post("/api/auth/verify", json={"token": "garbage"})
    assert r.status_code == 400


def test_logout_clears_session_cookie(client_and_conn):
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    client.post("/api/auth/verify", json={"token": token})
    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    # After logout, /api/me should be 401
    r2 = client.get("/api/me")
    assert r2.status_code == 401


def test_verify_page_renders(client_and_conn):
    client, _, _ = client_and_conn
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.get(f"/verify?token={token}")
    # Page sets cookie and shows success OR redirects to /settings/tokens.
    assert r.status_code in (200, 302, 303)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_auth_routes.py -v`
Expected: FAIL — routes don't exist; `create_app` doesn't accept `session_secret` or `email_client` kwargs yet.

- [ ] **Step 3: Write the `login.html` template**

Create `src/markland/web/templates/login.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Sign in — Markland</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 28rem; margin: 4rem auto; padding: 1rem; }
    h1 { font-size: 1.5rem; }
    label { display: block; margin-top: 1rem; }
    input[type=email] { width: 100%; padding: 0.5rem; font-size: 1rem; box-sizing: border-box; }
    button { margin-top: 1rem; padding: 0.5rem 1rem; font-size: 1rem; cursor: pointer; }
    .msg { margin-top: 1rem; color: #0a7; }
    .err { margin-top: 1rem; color: #c22; }
  </style>
</head>
<body>
  <h1>Sign in to Markland</h1>
  <p>Enter your email; we'll send you a one-time sign-in link.</p>
  <form id="f">
    <label for="email">Email</label>
    <input type="email" id="email" name="email" required>
    <button type="submit">Send magic link</button>
  </form>
  <div id="msg"></div>
  <script>
    document.getElementById('f').addEventListener('submit', async (e) => {
      e.preventDefault();
      const email = document.getElementById('email').value.trim();
      const msg = document.getElementById('msg');
      msg.className = '';
      msg.textContent = 'Sending…';
      const r = await fetch('/api/auth/magic-link', {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({email}),
      });
      if (r.ok) {
        msg.className = 'msg';
        msg.textContent = 'Check your email for the sign-in link.';
      } else {
        msg.className = 'err';
        msg.textContent = 'Something went wrong. Check the email and try again.';
      }
    });
  </script>
</body>
</html>
```

- [ ] **Step 4: Write the `verify_sent.html` template**

Create `src/markland/web/templates/verify_sent.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Signed in — Markland</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 28rem; margin: 4rem auto; padding: 1rem; }
  </style>
</head>
<body>
  <h1>Signed in</h1>
  <p>Go to <a href="/settings/tokens">your tokens</a> to create an API token for your MCP client.</p>
</body>
</html>
```

- [ ] **Step 5: Implement `auth_routes.py`**

Create `src/markland/web/auth_routes.py`:

```python
"""Magic-link auth: /api/auth/magic-link, /api/auth/verify, /api/auth/logout, /login, /verify."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, EmailStr

from markland.service.email import EmailClient, EmailSendError
from markland.service.magic_link import (
    InvalidMagicLink,
    read_magic_link_token,
    send_magic_link,
)
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_MAX_AGE_SECONDS,
    issue_session,
)
from markland.service.users import upsert_user_by_email

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class _MagicLinkRequest(BaseModel):
    email: EmailStr


class _VerifyRequest(BaseModel):
    token: str


def build_auth_router(
    *,
    db_conn: sqlite3.Connection,
    session_secret: str,
    base_url: str,
    email_client: EmailClient,
) -> APIRouter:
    router = APIRouter()
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    login_tpl = env.get_template("login.html")
    verify_sent_tpl = env.get_template("verify_sent.html")

    @router.get("/login", response_class=HTMLResponse)
    def login_page() -> HTMLResponse:
        return HTMLResponse(login_tpl.render())

    @router.post("/api/auth/magic-link")
    def magic_link(body: _MagicLinkRequest) -> JSONResponse:
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            send_magic_link(
                email=str(body.email),
                secret=session_secret,
                base_url=base_url,
                email_client=email_client,
            )
        except EmailSendError:
            # Best-effort: do not leak whether the email succeeded
            pass
        return JSONResponse({"ok": True})

    @router.post("/api/auth/verify")
    def verify(body: _VerifyRequest, response: Response) -> JSONResponse:
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            email = read_magic_link_token(body.token, secret=session_secret)
        except InvalidMagicLink as e:
            raise HTTPException(400, str(e)) from e
        user = upsert_user_by_email(db_conn, email)
        cookie = issue_session(user.id, secret=session_secret)
        resp = JSONResponse({"ok": True, "user_id": user.id})
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=base_url.startswith("https://"),
            samesite="lax",
            path="/",
        )
        return resp

    @router.get("/verify", response_class=HTMLResponse)
    def verify_page(request: Request, token: str) -> HTMLResponse:
        if not session_secret:
            raise HTTPException(500, "session secret not configured")
        try:
            email = read_magic_link_token(token, secret=session_secret)
        except InvalidMagicLink:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Link expired or invalid</h1>"
                "<p><a href='/login'>Request a new one</a></p>"
                "</body></html>",
                status_code=400,
            )
        user = upsert_user_by_email(db_conn, email)
        cookie = issue_session(user.id, secret=session_secret)
        resp = HTMLResponse(verify_sent_tpl.render())
        resp.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=cookie,
            max_age=SESSION_MAX_AGE_SECONDS,
            httponly=True,
            secure=base_url.startswith("https://"),
            samesite="lax",
            path="/",
        )
        return resp

    @router.post("/api/auth/logout")
    def logout() -> JSONResponse:
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return resp

    return router
```

- [ ] **Step 6: Teach `create_app` about the new kwargs (partial wiring)**

Modify `src/markland/web/app.py` — expand the `create_app` signature and include the auth router. Replace the full `create_app` function:

```python
def create_app(
    db_conn: sqlite3.Connection,
    *,
    mount_mcp: bool = False,
    admin_token: str = "",
    base_url: str = "",
    session_secret: str = "",
    email_client=None,
) -> FastAPI:
    from markland.service.email import EmailClient
    from markland.web.auth_routes import build_auth_router

    if email_client is None:
        email_client = EmailClient(api_key="", from_email="notifications@markland.dev")

    app = FastAPI(title="Markland", docs_url=None, redoc_url=None)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    landing_tpl = env.get_template("landing.html")
    explore_tpl = env.get_template("explore.html")
    document_tpl = env.get_template("document.html")

    mcp_snippet = _load_mcp_snippet()
    mcp_snippet_json = json.dumps(mcp_snippet)

    @app.get("/health")
    def health():
        return JSONResponse({"status": "ok"})

    @app.get("/", response_class=HTMLResponse)
    def landing():
        docs = list_featured_and_recent_public(db_conn, limit=8)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            landing_tpl.render(docs=cards, mcp_config_json=mcp_snippet_json)
        )

    @app.get("/explore", response_class=HTMLResponse)
    def explore(q: str | None = None):
        query = (q or "").strip() or None
        docs = list_public_documents(db_conn, query=query, limit=50)
        total_docs = list_public_documents(db_conn, query=query, limit=10_000)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            explore_tpl.render(docs=cards, query=query, total=len(total_docs))
        )

    @app.get("/d/{share_token}", response_class=HTMLResponse)
    def view_document(share_token: str):
        doc = get_document_by_token(db_conn, share_token)
        if doc is None:
            return HTMLResponse(
                "<html><body style='font-family:system-ui;padding:2rem;'>"
                "<h1>Document not found</h1>"
                "</body></html>",
                status_code=404,
            )
        content_html = render_markdown(doc.content)
        html = document_tpl.render(
            title=doc.title,
            content_html=content_html,
            created_at=doc.created_at,
        )
        return HTMLResponse(html)

    app.include_router(
        build_auth_router(
            db_conn=db_conn,
            session_secret=session_secret,
            base_url=base_url,
            email_client=email_client,
        )
    )

    if mount_mcp:
        from markland.server import build_mcp
        from markland.web.principal_middleware import PrincipalMiddleware

        mcp_instance = build_mcp(db_conn, base_url)
        mcp_app = mcp_instance.streamable_http_app()

        app.add_middleware(
            PrincipalMiddleware,
            db_conn=db_conn,
            protected_prefix="/mcp",
        )
        app.mount("/mcp", mcp_app)

    return app
```

- [ ] **Step 7: Run auth-route tests**

Run: `uv run pytest tests/test_auth_routes.py -v`
Expected: most tests PASS. `test_logout_clears_session_cookie` depends on `/api/me` existing — that's Task 11; skip/allow it to fail for this task.

Run: `uv run pytest tests/test_auth_routes.py -v -k "not logout"`
Expected: PASS (6 tests).

---

## Task 11: Identity routes — `/api/me`, `/api/tokens`, `/settings/tokens`

**Files:**
- Create: `src/markland/web/identity_routes.py`
- Create: `src/markland/web/templates/settings_tokens.html`
- Create: `tests/test_identity_routes.py`
- Modify: `src/markland/web/app.py` (include new router)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_identity_routes.py`:

```python
"""Tests for /api/me, /api/tokens, and /settings/tokens."""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.magic_link import issue_magic_link_token
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    email_client = MagicMock()
    email_client.send.return_value = None
    app = create_app(
        conn,
        mount_mcp=False,
        admin_token="",
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    with TestClient(app) as c:
        yield c


def _sign_in(client, email: str) -> None:
    token = issue_magic_link_token(email, secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200


def test_me_requires_session(client):
    r = client.get("/api/me")
    assert r.status_code == 401


def test_me_returns_user(client):
    _sign_in(client, "alice@example.com")
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "alice@example.com"
    assert body["user_id"].startswith("usr_")
    assert body["is_admin"] is False


def test_create_token_requires_session(client):
    r = client.post("/api/tokens", json={"label": "laptop"})
    assert r.status_code == 401


def test_create_token_returns_plaintext_once(client):
    _sign_in(client, "alice@example.com")
    r = client.post("/api/tokens", json={"label": "laptop"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"].startswith("mk_usr_")
    assert body["id"].startswith("tok_")
    assert body["label"] == "laptop"


def test_list_tokens_omits_plaintext(client):
    _sign_in(client, "alice@example.com")
    client.post("/api/tokens", json={"label": "laptop"})
    client.post("/api/tokens", json={"label": "phone"})
    r = client.get("/api/me")
    labels = {t["label"] for t in r.json()["tokens"]}
    assert labels == {"laptop", "phone"}
    for t in r.json()["tokens"]:
        assert "token" not in t


def test_delete_token_revokes(client):
    _sign_in(client, "alice@example.com")
    created = client.post("/api/tokens", json={"label": "laptop"}).json()
    token_id = created["id"]
    r = client.delete(f"/api/tokens/{token_id}")
    assert r.status_code == 200
    me = client.get("/api/me").json()
    assert all(t["id"] != token_id for t in me["tokens"])


def test_delete_token_other_user_returns_404(client):
    _sign_in(client, "alice@example.com")
    created = client.post("/api/tokens", json={"label": "laptop"}).json()
    token_id = created["id"]

    # Sign in as a different user
    client.post("/api/auth/logout")
    _sign_in(client, "bob@example.com")
    r = client.delete(f"/api/tokens/{token_id}")
    assert r.status_code == 404


def test_settings_tokens_page_requires_session(client):
    r = client.get("/settings/tokens", follow_redirects=False)
    assert r.status_code in (302, 303, 401)


def test_settings_tokens_page_renders_when_signed_in(client):
    _sign_in(client, "alice@example.com")
    r = client.get("/settings/tokens")
    assert r.status_code == 200
    assert "Tokens" in r.text or "tokens" in r.text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_identity_routes.py -v`
Expected: FAIL — routes don't exist.

- [ ] **Step 3: Write the `settings_tokens.html` template**

Create `src/markland/web/templates/settings_tokens.html`:

```html
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Tokens — Markland</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 48rem; margin: 2rem auto; padding: 1rem; }
    h1 { font-size: 1.5rem; }
    table { width: 100%; border-collapse: collapse; margin-top: 1rem; }
    th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #eee; }
    form.inline { display: inline; }
    .newtoken { background: #efe; border: 1px solid #aca; padding: 1rem; margin-top: 1rem; word-break: break-all; }
    .newtoken code { font-size: 1rem; }
    button { padding: 0.4rem 0.8rem; cursor: pointer; }
    input[type=text] { padding: 0.4rem; width: 16rem; }
  </style>
</head>
<body>
  <h1>API tokens for {{ user.email }}</h1>
  <p>Use these tokens in your MCP client's <code>Authorization: Bearer …</code> header.</p>

  <h2>Create a token</h2>
  <form id="create">
    <input type="text" id="label" name="label" placeholder="e.g. laptop" required>
    <button type="submit">Create</button>
  </form>
  <div id="newbox"></div>

  <h2>Your tokens</h2>
  {% if tokens %}
  <table>
    <thead><tr><th>Label</th><th>Created</th><th>Last used</th><th></th></tr></thead>
    <tbody>
    {% for t in tokens %}
      <tr id="row-{{ t.id }}">
        <td>{{ t.label or "(unlabeled)" }}</td>
        <td>{{ t.created_at }}</td>
        <td>{{ t.last_used_at or "never" }}</td>
        <td>
          <button class="revoke" data-id="{{ t.id }}">Revoke</button>
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p>No tokens yet.</p>
  {% endif %}

  <p style="margin-top:2rem;"><a href="#" id="logout">Sign out</a></p>

  <script>
    document.getElementById('create').addEventListener('submit', async (e) => {
      e.preventDefault();
      const label = document.getElementById('label').value.trim();
      const r = await fetch('/api/tokens', {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({label}),
      });
      if (r.ok) {
        const body = await r.json();
        document.getElementById('newbox').innerHTML =
          '<div class="newtoken">New token (copy now — it will not be shown again):<br>' +
          '<code>' + body.token + '</code></div>';
        setTimeout(() => location.reload(), 500);
      }
    });
    document.querySelectorAll('.revoke').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        if (!confirm('Revoke this token?')) return;
        const r = await fetch('/api/tokens/' + id, {method: 'DELETE'});
        if (r.ok) document.getElementById('row-' + id).remove();
      });
    });
    document.getElementById('logout').addEventListener('click', async (e) => {
      e.preventDefault();
      await fetch('/api/auth/logout', {method: 'POST'});
      location.href = '/login';
    });
  </script>
</body>
</html>
```

- [ ] **Step 4: Implement `identity_routes.py`**

Create `src/markland/web/identity_routes.py`:

```python
"""Session-authed identity endpoints: /api/me, /api/tokens, /settings/tokens.

All routes here read the `mk_session` cookie via `service.sessions.read_session`.
Unlike `/mcp`, these are NOT gated by PrincipalMiddleware — sessions, not bearers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel, Field

from markland.service.auth import (
    create_user_token,
    list_tokens,
    revoke_token,
)
from markland.service.sessions import (
    SESSION_COOKIE_NAME,
    InvalidSession,
    read_session,
)
from markland.service.users import User, get_user

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class _CreateTokenRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)


def _require_session_user(
    request: Request,
    conn: sqlite3.Connection,
    session_secret: str,
) -> User:
    cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
    try:
        payload = read_session(cookie, secret=session_secret)
    except InvalidSession as e:
        raise HTTPException(401, "unauthenticated") from e
    user = get_user(conn, payload["user_id"])
    if user is None:
        raise HTTPException(401, "unauthenticated")
    return user


def build_identity_router(
    *,
    db_conn: sqlite3.Connection,
    session_secret: str,
) -> APIRouter:
    router = APIRouter()
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    settings_tpl = env.get_template("settings_tokens.html")

    @router.get("/api/me")
    def me(request: Request) -> JSONResponse:
        user = _require_session_user(request, db_conn, session_secret)
        tokens = list_tokens(db_conn, user_id=user.id)
        return JSONResponse({
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "is_admin": user.is_admin,
            "tokens": [
                {
                    "id": t.id,
                    "label": t.label,
                    "created_at": t.created_at,
                    "last_used_at": t.last_used_at,
                }
                for t in tokens
            ],
        })

    @router.post("/api/tokens")
    def create_token(request: Request, body: _CreateTokenRequest) -> JSONResponse:
        user = _require_session_user(request, db_conn, session_secret)
        token_id, plaintext = create_user_token(
            db_conn, user_id=user.id, label=body.label
        )
        return JSONResponse({
            "id": token_id,
            "label": body.label,
            "token": plaintext,
        })

    @router.delete("/api/tokens/{token_id}")
    def delete_token(request: Request, token_id: str) -> JSONResponse:
        user = _require_session_user(request, db_conn, session_secret)
        ok = revoke_token(db_conn, token_id=token_id, user_id=user.id)
        if not ok:
            raise HTTPException(404, "token not found")
        return JSONResponse({"ok": True})

    @router.get("/settings/tokens", response_class=HTMLResponse)
    def settings_tokens(request: Request):
        cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
        try:
            payload = read_session(cookie, secret=session_secret)
        except InvalidSession:
            return RedirectResponse("/login", status_code=303)
        user = get_user(db_conn, payload["user_id"])
        if user is None:
            return RedirectResponse("/login", status_code=303)
        tokens = list_tokens(db_conn, user_id=user.id)
        return HTMLResponse(settings_tpl.render(user=user, tokens=tokens))

    return router
```

- [ ] **Step 5: Wire the router into `create_app`**

Modify `src/markland/web/app.py` — add the import near the top of `create_app` and the `include_router` call right after the auth router include:

```python
        from markland.web.identity_routes import build_identity_router
```

…and after `app.include_router(build_auth_router(...))`:

```python
    app.include_router(
        build_identity_router(
            db_conn=db_conn,
            session_secret=session_secret,
        )
    )
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_identity_routes.py -v`
Expected: PASS (9 tests).

Re-run auth-route tests including the previously-skipped logout test:

Run: `uv run pytest tests/test_auth_routes.py -v`
Expected: PASS (7 tests).

---

## Task 12: `markland_whoami` + `is_admin` gate on `markland_feature`

**Files:**
- Modify: `src/markland/server.py`
- Create: `tests/test_whoami_tool.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_whoami_tool.py`:

```python
"""Unit tests for the whoami tool function and the is_admin gate on feature."""

import pytest

from markland.db import init_db
from markland.server import _feature_requires_admin, _whoami_for_principal
from markland.service.auth import Principal


def test_whoami_returns_principal_fields():
    p = Principal(
        principal_id="usr_abc",
        principal_type="user",
        display_name="Alice",
        is_admin=False,
    )
    assert _whoami_for_principal(p) == {
        "principal_id": "usr_abc",
        "principal_type": "user",
        "display_name": "Alice",
    }


def test_feature_requires_admin_allows_admin(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Principal(
        principal_id="usr_x",
        principal_type="user",
        display_name="X",
        is_admin=True,
    )
    # Should not raise
    _feature_requires_admin(p)


def test_feature_requires_admin_rejects_non_admin(tmp_path):
    conn = init_db(tmp_path / "t.db")
    p = Principal(
        principal_id="usr_x",
        principal_type="user",
        display_name="X",
        is_admin=False,
    )
    with pytest.raises(PermissionError):
        _feature_requires_admin(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_whoami_tool.py -v`
Expected: FAIL — helpers don't exist.

- [ ] **Step 3: Update `src/markland/server.py`**

Replace `src/markland/server.py` in full:

```python
"""Markland MCP Server — publish and share markdown documents."""

import logging

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Context

from markland.config import get_config
from markland.db import init_db
from markland.service.auth import Principal
from markland.tools.documents import (
    delete_doc,
    feature_doc,
    get_doc,
    list_docs,
    publish_doc,
    search_docs,
    set_visibility_doc,
    share_doc,
    update_doc,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("markland")


def _whoami_for_principal(principal: Principal) -> dict:
    return {
        "principal_id": principal.principal_id,
        "principal_type": principal.principal_type,
        "display_name": principal.display_name,
    }


def _feature_requires_admin(principal: Principal) -> None:
    if not principal.is_admin:
        raise PermissionError("markland_feature requires admin")


def _principal_from_ctx(ctx: Context | None) -> Principal | None:
    """Extract `request.state.principal` that PrincipalMiddleware attached."""
    if ctx is None:
        return None
    req = getattr(ctx, "request_context", None)
    if req is None:
        return None
    request = getattr(req, "request", None)
    if request is None:
        return None
    state = getattr(request, "state", None)
    if state is None:
        return None
    return getattr(state, "principal", None)


def build_mcp(db_conn, base_url: str) -> FastMCP:
    """Build a FastMCP instance with all Markland tools registered."""
    mcp = FastMCP("markland")

    @mcp.tool()
    def markland_whoami(ctx: Context) -> dict:
        """Return the caller's identity."""
        principal = _principal_from_ctx(ctx)
        if principal is None:
            # In stdio mode or when middleware hasn't attached a principal, fall
            # back to an anonymous identity for backwards compat.
            return {
                "principal_id": "anonymous",
                "principal_type": "user",
                "display_name": None,
            }
        return _whoami_for_principal(principal)

    @mcp.tool()
    def markland_publish(content: str, title: str | None = None, public: bool = False) -> dict:
        """Publish a markdown document and get a shareable link."""
        return publish_doc(db_conn, base_url, title, content, public=public)

    @mcp.tool()
    def markland_list() -> list[dict]:
        """List all published documents, most recent first."""
        return list_docs(db_conn)

    @mcp.tool()
    def markland_get(doc_id: str) -> dict:
        """Get a document's full content by ID."""
        return get_doc(db_conn, doc_id)

    @mcp.tool()
    def markland_search(query: str) -> list[dict]:
        """Search documents by title or content."""
        return search_docs(db_conn, query)

    @mcp.tool()
    def markland_share(doc_id: str) -> dict:
        """Get the shareable link for a document."""
        return share_doc(db_conn, base_url, doc_id)

    @mcp.tool()
    def markland_update(doc_id: str, content: str | None = None, title: str | None = None) -> dict:
        """Update a document's content or title."""
        return update_doc(db_conn, base_url, doc_id, content=content, title=title)

    @mcp.tool()
    def markland_delete(doc_id: str) -> dict:
        """Delete a document."""
        return delete_doc(db_conn, doc_id)

    @mcp.tool()
    def markland_set_visibility(doc_id: str, public: bool) -> dict:
        """Promote a doc to public (appears in /explore) or demote to unlisted."""
        return set_visibility_doc(db_conn, base_url, doc_id, is_public=public)

    @mcp.tool()
    def markland_feature(doc_id: str, featured: bool = True, ctx: Context | None = None) -> dict:
        """Pin or unpin a doc to the landing page hero. Admin only."""
        principal = _principal_from_ctx(ctx)
        if principal is not None:
            _feature_requires_admin(principal)
        return feature_doc(db_conn, doc_id, is_featured=featured)

    return mcp


if __name__ == "__main__":
    config = get_config()
    db_conn = init_db(config.db_path)
    logger.info("Starting Markland MCP server (stdio, db: %s)", config.db_path)
    mcp_instance = build_mcp(db_conn, config.base_url)
    mcp_instance.run()
```

- [ ] **Step 4: Run unit tests**

Run: `uv run pytest tests/test_whoami_tool.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: everything passes. The existing `test_http_mcp.py` from Plan 1 still uses the old `AdminBearerMiddleware` indirectly via `create_app(..., admin_token=...)`; if it fails because the middleware changed, update it — see Task 13.

---

## Task 13: Remove `AdminBearerMiddleware` from `create_app`; update Plan-1 tests

**Files:**
- Modify: `src/markland/web/app.py` (delete the `admin_token` branch)
- Delete: `src/markland/web/auth_middleware.py`
- Delete: `tests/test_auth_middleware.py`
- Modify: `tests/test_http_mcp.py` — use a real user + token for the authed case

- [ ] **Step 1: Rewrite `test_http_mcp.py`**

Replace `tests/test_http_mcp.py`:

```python
"""Integration test: MCP tools reachable over HTTP with a real user token."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.auth import create_user_token
from markland.service.users import create_user
from markland.web.app import create_app


@pytest.fixture
def client_and_token(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(db_path)
    user = create_user(conn, email="smoke@example.com", display_name="Smoke")
    _, plaintext = create_user_token(conn, user_id=user.id, label="smoke")
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://testserver",
        session_secret="test-secret",
    )
    with TestClient(app) as c:
        yield c, plaintext


def test_mcp_endpoint_rejects_unauthenticated(client_and_token):
    client, _ = client_and_token
    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401


def test_mcp_endpoint_rejects_unknown_bearer(client_and_token):
    client, _ = client_and_token
    r = client.post(
        "/mcp/",
        headers={"Authorization": "Bearer mk_usr_unknown"},
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401


def test_mcp_endpoint_accepts_valid_user_token(client_and_token):
    client, plaintext = client_and_token
    r = client.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {plaintext}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
    )
    assert r.status_code == 200


def test_web_routes_still_public(client_and_token):
    client, _ = client_and_token
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.get("/explore").status_code == 200
```

- [ ] **Step 2: Delete the old middleware + its tests**

Run:
```bash
rm /Users/daveyhiles/Developer/markland/src/markland/web/auth_middleware.py
rm /Users/daveyhiles/Developer/markland/tests/test_auth_middleware.py
```
Expected: files removed.

- [ ] **Step 3: Strip `admin_token` references from `create_app`**

Modify `src/markland/web/app.py` — change the signature and remove any trailing `admin_token` usage. Replace the `create_app` signature line and remove the old `admin_token` kwarg:

```python
def create_app(
    db_conn: sqlite3.Connection,
    *,
    mount_mcp: bool = False,
    base_url: str = "",
    session_secret: str = "",
    email_client=None,
) -> FastAPI:
```

(The body no longer uses `admin_token`; all gating goes through `PrincipalMiddleware`.)

- [ ] **Step 4: Update `run_app.py` to pass `session_secret` instead of `admin_token`**

Replace `src/markland/run_app.py`:

```python
"""Unified HTTP entrypoint: web viewer + MCP on /mcp, Sentry init."""

import logging

import uvicorn

from markland.config import get_config
from markland.db import init_db
from markland.service.email import EmailClient
from markland.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("markland.app")

config = get_config()

if config.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=config.sentry_dsn,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")

db_conn = init_db(config.db_path)
email_client = EmailClient(
    api_key=config.resend_api_key,
    from_email=config.resend_from_email,
)
app = create_app(
    db_conn,
    mount_mcp=True,
    base_url=config.base_url,
    session_secret=config.session_secret,
    email_client=email_client,
)


if __name__ == "__main__":
    host = "0.0.0.0" if config.session_secret else "127.0.0.1"
    logger.info(
        "Starting Markland hosted app on %s:%d (db: %s, mcp_enabled=%s)",
        host,
        config.web_port,
        config.db_path,
        bool(config.session_secret),
    )
    uvicorn.run(app, host=host, port=config.web_port, log_level="info")
```

- [ ] **Step 5: Update Plan-1 sentry test if it passed `admin_token`**

If `tests/test_sentry_init.py` from Plan 1 sets `MARKLAND_ADMIN_TOKEN`, swap that for `MARKLAND_SESSION_SECRET`. Specifically, where it sets `"MARKLAND_ADMIN_TOKEN", "t"`, change to `"MARKLAND_SESSION_SECRET", "t"`.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: everything passes. Any lingering reference to `AdminBearerMiddleware` or `admin_token` in `create_app` keyword args gets flagged here.

---

## Task 14: Smoke test — sign up → create token → hit /mcp → whoami

**Files:**
- Create: `tests/test_whoami_smoke.py`
- Modify: `docs/runbooks/first-deploy.md` (add `MARKLAND_SESSION_SECRET` + admin-promotion note)

- [ ] **Step 1: Write the smoke test**

Create `tests/test_whoami_smoke.py`:

```python
"""End-to-end: user signs up via magic link, creates a token, calls markland_whoami over HTTP."""

import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.magic_link import issue_magic_link_token
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    email_client = MagicMock()
    email_client.send.return_value = None
    app = create_app(
        conn,
        mount_mcp=True,
        base_url="http://testserver",
        session_secret="test-secret",
        email_client=email_client,
    )
    with TestClient(app) as c:
        yield c


def test_full_onboarding_flow_and_whoami(client):
    # 1. Request magic link
    r = client.post("/api/auth/magic-link", json={"email": "alice@example.com"})
    assert r.status_code == 200

    # 2. Simulate clicking the email link (test bypasses the email itself)
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200

    # 3. Create a bearer token while session is active
    r = client.post("/api/tokens", json={"label": "claude-code"})
    assert r.status_code == 200
    bearer = r.json()["token"]
    assert bearer.startswith("mk_usr_")

    # 4. Hit /mcp with the bearer and call markland_whoami
    r = client.post(
        "/mcp/",
        headers={
            "Authorization": f"Bearer {bearer}",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "smoke", "version": "0"},
            },
        },
    )
    assert r.status_code == 200


def test_mcp_rejects_without_bearer_even_with_session(client):
    # Verify that a logged-in session (cookie) does NOT authorize /mcp.
    # /mcp requires a bearer token, full stop.
    token = issue_magic_link_token("alice@example.com", secret="test-secret")
    client.post("/api/auth/verify", json={"token": token})
    r = client.post(
        "/mcp/",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    )
    assert r.status_code == 401
```

- [ ] **Step 2: Run the smoke test**

Run: `uv run pytest tests/test_whoami_smoke.py -v`
Expected: PASS (2 tests).

- [ ] **Step 3: Update the first-deploy runbook**

Modify `docs/runbooks/first-deploy.md` — in section 3 ("Fly app + volume + secrets"), replace the `flyctl secrets set` block with:

```bash
# Generate a session secret (rotating this signs out all users)
SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"

# Set secrets (fly encrypts at rest, injects as env vars)
flyctl secrets set \
  MARKLAND_SESSION_SECRET="$SESSION_SECRET" \
  SENTRY_DSN="<your sentry dsn or empty>" \
  RESEND_API_KEY="<your resend key>" \
  LITESTREAM_REPLICA_URL="s3://markland-db.<accountid>.r2.cloudflarestorage.com/markland" \
  LITESTREAM_ACCESS_KEY_ID="<r2 access key>" \
  LITESTREAM_SECRET_ACCESS_KEY="<r2 secret key>"
```

Remove the `MARKLAND_ADMIN_TOKEN` export and the `$ADMIN_TOKEN` reference from the deploy-sanity `curl` commands; replace them with a note:

```markdown
After deploy, sanity-check:
```bash
curl -s https://markland.fly.dev/health
# /mcp now requires a real user bearer token. Sign up first:
open https://markland.fly.dev/login
# Create a token on /settings/tokens, then:
MK_BEARER="mk_usr_<paste>"
curl -sSo /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $MK_BEARER" https://markland.fly.dev/mcp/
```
```

Append a new section at the end of the runbook:

```markdown
## 8. Promote yourself to admin

After first sign-in, promote your user to admin so `markland_feature` works:

```bash
flyctl ssh console -C "sqlite3 /data/markland.db \"UPDATE users SET is_admin = 1 WHERE email = 'you@yourdomain.com';\""
```

Admin promotion is SQLite-only at launch — no UI. Repeat for additional admins.

## 9. Rotating MARKLAND_SESSION_SECRET

Rotating `MARKLAND_SESSION_SECRET` invalidates all active web sessions (users are signed out) and all outstanding magic-link tokens. API bearer tokens are **unaffected** — they're argon2id-hashed in the DB, not secret-signed. Rotate with:

```bash
flyctl secrets set MARKLAND_SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_urlsafe(48))')"
```
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: every test passes.

---

## Task 15: Manual verification against local run

**Files:** none (manual smoke).

- [ ] **Step 1: Run the app locally**

Run (in one terminal):
```bash
MARKLAND_SESSION_SECRET=dev-local-secret \
MARKLAND_BASE_URL=http://localhost:8950 \
uv run python src/markland/run_app.py
```
Expected: log line with `mcp_enabled=True`.

- [ ] **Step 2: Manual walkthrough**

In a browser, visit `http://localhost:8950/login`. Submit your email. The terminal logs the "Email disabled" line with the magic-link URL embedded in the rendered HTML; copy the `/verify?token=…` URL from the log output (or from the EmailClient's logged-body if visible), open it in the browser. You should land on `/settings/tokens` (via the `verify_sent.html` link).

Click **Create** with label `local-smoke`. Copy the displayed `mk_usr_…` token.

In another terminal:
```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8950/mcp/
# Expected: 401

curl -s -o /dev/null -w "%{http_code}\n" \
  -H "Authorization: Bearer mk_usr_PASTE_HERE" \
  -H "Accept: application/json, text/event-stream" \
  -X POST http://localhost:8950/mcp/ \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}'
# Expected: 200
```

Stop the server (Ctrl-C).

- [ ] **Step 3: Verification**

Confirmed working:
- `/login` renders, `POST /api/auth/magic-link` returns 200, the email client's `send` is invoked with a `/verify?token=…` URL in the HTML body.
- `/verify?token=…` sets the `mk_session` cookie and renders `verify_sent.html`.
- `/settings/tokens` renders only with a valid session, shows existing tokens, lets you create and revoke.
- `/api/me`, `POST /api/tokens`, `DELETE /api/tokens/{id}` behave per tests.
- `/mcp/` returns 401 without a bearer and 200 with a valid `mk_usr_…` token.

---

## Completion criteria

- `uv run pytest tests/ -v` passes with all new test files: `test_db_users_tokens.py`, `test_service_users.py`, `test_service_auth.py`, `test_service_sessions.py`, `test_service_magic_link.py`, `test_principal_middleware.py`, `test_auth_routes.py`, `test_identity_routes.py`, `test_whoami_tool.py`, `test_whoami_smoke.py`. Plan-1 tests `test_http_mcp.py` and `test_sentry_init.py` still pass after the `admin_token` → `session_secret` rename.
- `AdminBearerMiddleware` is deleted; `PrincipalMiddleware` gates `/mcp`; no hardcoded-admin-token code path remains.
- A local run (`MARKLAND_SESSION_SECRET=… uv run python src/markland/run_app.py`) supports the full flow: `/login` → magic-link email (logged in EmailClient no-op mode) → `/verify` sets `mk_session` → `/settings/tokens` creates a `mk_usr_…` token → that token authenticates `/mcp` → `markland_whoami` returns the user's identity.
- `is_admin` defaults to 0; flipping it via SQLite unblocks `markland_feature`. The runbook documents the promotion command.
- `docs/runbooks/first-deploy.md` documents `MARKLAND_SESSION_SECRET`, removes the admin-token step, and includes the admin-promotion + secret-rotation notes.

## What this plan does NOT deliver

Per spec §17, later plans handle:

- **Plan 3 — doc ownership and grants.** This plan leaves docs owner-less; any authenticated principal can call all existing doc tools. Plan 3 adds `documents.owner_id`, the `grants` table, `markland_grant` / `markland_revoke` / `markland_list_grants`, and the per-doc permission resolution from spec §5.
- **Plan 4 — agents.** `tokens.principal_type` already supports `'agent'` in the schema; `resolve_token` and `PrincipalMiddleware` short-circuit on agent rows. Plan 4 adds the `agents` table, `/settings/agents`, agent tokens, `markland_list_my_agents`, and the user-owned-agent inheritance rule.
- **Plan 5 — invite links.** Not in scope.
- **Plan 6 — device flow for CLI onboarding.** `/api/auth/device-*` endpoints, `/device` and `/setup` pages, and the Claude-Code paste-a-URL runbook.
- **Plan 7 — email notification triggers.** This plan only sends the magic-link email; grant/invite notifications arrive in Plan 7.
- **Plan 8 — conflict handling.** No `version` column, no `revisions` table, no `if_version` / `If-Match` yet.
- **Plan 9 — presence.** No `presence` table or `markland_set_status` / `markland_clear_status`.
- **Plan 10 — launch polish.** No rate limiting, no audit log, no `/explore` auth-context tweaks.
