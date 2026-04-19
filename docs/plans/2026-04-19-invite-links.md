# Invite Links — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Add invite-link sharing to Markland. An owner creates a URL (`https://markland.dev/invite/inv_<token>`), hands it to anyone through any channel they like, and the recipient lands on a page that either (a) one-click-accepts the grant if they're signed in, or (b) collects their email, sends a magic link, and on return accepts the invite and redirects into the doc. Single-use and reusable invites both supported, optional expiry, per-invite revocation. This is Plan 5 of 10 from `docs/specs/2026-04-19-multi-agent-auth-design.md` §17 and covers the spec's §6.3, §6.4, §6.5, §10.1 `invites`, and §12.3 invite endpoints.

**Architecture:** A new `invites` table stores invite records with argon2-hashed tokens (same hashing used for user tokens in Plan 2). A `service/invites.py` module owns create / resolve / accept / revoke / list. Two new MCP tools (`markland_create_invite`, `markland_revoke_invite`) and three HTTP routes (`POST /api/docs/{id}/invites`, `DELETE /api/invites/{id}`, `POST /api/invites/{token}/accept`) expose the surface, plus a public `GET /invite/{token}` HTML page that handles signed-in and signed-out paths. Acceptance calls `service.grants.grant()` to produce the `grants` row; the grant system does not know invites exist, keeping concerns separate. Acceptance is idempotent — re-accepting a higher-or-equal grant does not downgrade, but still decrements the invite's use count. An optional best-effort email notifies the invite creator on acceptance.

**Tech Stack:** Python 3.12, FastAPI, FastMCP, SQLite, argon2id (via `argon2-cffi`), Jinja2, `uv run pytest`.

**Scope excluded (this plan):**
- No invite-creation email (owner delivers the URL manually — spec §6.3).
- No time-limited grants beyond the invite's own `expires_at`; once the grant row exists it's permanent until explicitly revoked.
- No bulk invites (one invite at a time; loop externally if needed).
- No QR codes or alternative delivery surfaces — the URL alone is the artifact.
- No device-flow piggyback on invite tokens (`/setup?invite=…`); that's Plan 6.
- No `/share` dialog UI rewrite — the invite APIs are surfaced; the Plan 3 share dialog will wire them in Plan 10 polish.

---

## File Structure

**New files:**
- `src/markland/service/invites.py` — create / resolve / accept / revoke / list
- `src/markland/web/invite_routes.py` — HTTP + HTML routes (kept separate from `app.py` for testability)
- `src/markland/web/templates/invite.html` — invite landing page (signed-in + signed-out paths)
- `src/markland/web/templates/invite_pending.html` — "check your email" page post-magic-link-request
- `tests/test_invites_migration.py` — migration + index smoke test
- `tests/test_service_invites_create_resolve.py` — token round-trip + expiry filtering
- `tests/test_service_invites_accept.py` — grant creation, idempotency, use decrement
- `tests/test_service_invites_revoke_list.py` — revoke + list + expired-hiding
- `tests/test_mcp_invite_tools.py` — `markland_create_invite` / `markland_revoke_invite`
- `tests/test_http_invite_routes.py` — POST/DELETE owner-only + HTML page
- `tests/test_invite_signup_flow.py` — integration: anon → magic link → accept → redirect
- `tests/test_invite_accept_email.py` — creator-notification email best-effort
- `tests/test_invite_smoke.py` — end-to-end path described in spec §6.3

**Modified files:**
- `src/markland/db.py` — add `ensure_invites_schema()` and invite query helpers
- `src/markland/models.py` — add `Invite` dataclass
- `src/markland/server.py` — register `markland_create_invite`, `markland_revoke_invite`
- `src/markland/web/app.py` — mount invite routes; wire `EmailClient` + `InviteService`
- `src/markland/run_app.py` — pass `email_client` into `create_app` (from Plan 1 stub)

**Unchanged (but read):**
- `src/markland/service/grants.py` — `grant_by_principal_id()` is called from `accept_invite` (internal-helper path; not the public `grant()`, which requires email + principal authorization)
- `src/markland/service/magic_link.py` — we reuse the existing magic-link flow; the invite page redirects to `/login?return_to=/invite/<token>`
- `src/markland/service/auth.py` — token-hashing helper (`hash_token`) is reused
- `src/markland/service/agents.py` — untouched

---

## Task 1: Invites table migration + index

**Files:**
- Modify: `src/markland/db.py`
- Create: `tests/test_invites_migration.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_invites_migration.py`:

```python
"""Invites table is created with correct columns and token_hash index."""

import sqlite3

from markland.db import ensure_invites_schema, init_db


def test_invites_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(invites)")}
    assert cols == {
        "id",
        "token_hash",
        "doc_id",
        "level",
        "single_use",
        "uses_remaining",
        "created_by",
        "created_at",
        "expires_at",
        "revoked_at",
    }


def test_token_hash_is_unique(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, single_use, uses_remaining, "
        "created_by, created_at) VALUES (?, ?, ?, 'view', 1, 1, 'usr_x', '2026-04-19T00:00:00+00:00')",
        ("inv_a", "hash1", "doc_a"),
    )
    try:
        conn.execute(
            "INSERT INTO invites (id, token_hash, doc_id, level, single_use, uses_remaining, "
            "created_by, created_at) VALUES (?, ?, ?, 'view', 1, 1, 'usr_x', '2026-04-19T00:00:00+00:00')",
            ("inv_b", "hash1", "doc_a"),
        )
        raise AssertionError("expected UNIQUE violation on token_hash")
    except sqlite3.IntegrityError:
        pass


def test_token_hash_index_exists(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    indexes = {
        row[1]
        for row in conn.execute("PRAGMA index_list(invites)")
    }
    assert "idx_invites_token_hash" in indexes


def test_ensure_is_idempotent(tmp_path):
    conn = init_db(tmp_path / "t.db")
    ensure_invites_schema(conn)
    ensure_invites_schema(conn)
    # Second call must not raise.
    rows = conn.execute("SELECT count(*) FROM invites").fetchone()
    assert rows[0] == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_invites_migration.py -v`
Expected: FAIL — `ensure_invites_schema` does not exist.

- [ ] **Step 3: Add the migration**

Modify `src/markland/db.py` — append `ensure_invites_schema` near the other `ensure_*_schema` functions:

```python
def ensure_invites_schema(conn: sqlite3.Connection) -> None:
    """Create the invites table + token_hash index if they don't exist."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS invites (
            id TEXT PRIMARY KEY,
            token_hash TEXT UNIQUE NOT NULL,
            doc_id TEXT NOT NULL,
            level TEXT NOT NULL CHECK (level IN ('view', 'edit')),
            single_use INTEGER NOT NULL DEFAULT 1,
            uses_remaining INTEGER NOT NULL DEFAULT 1,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            revoked_at TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_invites_token_hash
            ON invites (token_hash);

        CREATE INDEX IF NOT EXISTS idx_invites_doc
            ON invites (doc_id);
        """
    )
    conn.commit()
```

Also call it from `init_db` alongside the existing schema bootstraps:

```python
def init_db(db_path: Path) -> sqlite3.Connection:
    # … existing body …
    ensure_documents_schema(conn)
    ensure_users_schema(conn)
    ensure_tokens_schema(conn)
    ensure_grants_schema(conn)
    ensure_agents_schema(conn)
    ensure_invites_schema(conn)
    return conn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_invites_migration.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass. No existing test touches `invites`.

---

## Task 2: `Invite` dataclass

**Files:**
- Modify: `src/markland/models.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_models.py` (create if it doesn't exist):

```python
"""Test the Invite dataclass."""

from markland.models import Invite


def test_invite_generate_id_has_inv_prefix():
    iid = Invite.generate_id()
    assert iid.startswith("inv_")
    # 16 hex chars after the prefix
    assert len(iid) == 4 + 16


def test_invite_generate_token_is_urlsafe_and_long():
    t = Invite.generate_token()
    # secrets.token_urlsafe(32) is ~43 chars
    assert len(t) >= 40


def test_invite_dataclass_roundtrip():
    inv = Invite(
        id="inv_deadbeefdeadbeef",
        token_hash="hash",
        doc_id="doc_1",
        level="view",
        single_use=True,
        uses_remaining=1,
        created_by="usr_a",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at=None,
        revoked_at=None,
    )
    assert inv.id == "inv_deadbeefdeadbeef"
    assert inv.level == "view"
    assert inv.single_use is True
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is True


def test_invite_is_active_expired():
    inv = Invite(
        id="inv_x",
        token_hash="h",
        doc_id="d",
        level="view",
        single_use=True,
        uses_remaining=1,
        created_by="u",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at="2026-04-19T00:30:00+00:00",
        revoked_at=None,
    )
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is False


def test_invite_is_active_used_up():
    inv = Invite(
        id="inv_x",
        token_hash="h",
        doc_id="d",
        level="view",
        single_use=True,
        uses_remaining=0,
        created_by="u",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at=None,
        revoked_at=None,
    )
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is False


def test_invite_is_active_revoked():
    inv = Invite(
        id="inv_x",
        token_hash="h",
        doc_id="d",
        level="view",
        single_use=True,
        uses_remaining=1,
        created_by="u",
        created_at="2026-04-19T00:00:00+00:00",
        expires_at=None,
        revoked_at="2026-04-19T00:10:00+00:00",
    )
    assert inv.is_active(now="2026-04-19T01:00:00+00:00") is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: FAIL — `Invite` is not defined.

- [ ] **Step 3: Add the dataclass**

Append to `src/markland/models.py`:

```python
@dataclass
class Invite:
    id: str
    token_hash: str
    doc_id: str
    level: str  # 'view' | 'edit'
    single_use: bool
    uses_remaining: int
    created_by: str  # principal_id (usr_… at launch)
    created_at: str
    expires_at: str | None = None
    revoked_at: str | None = None

    @staticmethod
    def generate_id() -> str:
        return "inv_" + secrets.token_hex(8)

    @staticmethod
    def generate_token() -> str:
        # 32 bytes of entropy; urlsafe for direct use in URLs.
        return secrets.token_urlsafe(32)

    def is_active(self, *, now: str) -> bool:
        if self.revoked_at is not None:
            return False
        if self.uses_remaining <= 0:
            return False
        if self.expires_at is not None and now >= self.expires_at:
            return False
        return True
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (6 tests, plus any pre-existing).

---

## Task 3: `service/invites.py` — `create_invite` and `resolve_invite`

**Files:**
- Create: `src/markland/service/invites.py`
- Create: `tests/test_service_invites_create_resolve.py`

Rationale: token hashing round-trips through the same argon2id path used for user/agent tokens. We store the hash, but never the plaintext. `resolve_invite` is how the invite page looks up "which invite is this?" given the URL slug.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_invites_create_resolve.py`:

```python
"""service/invites.py: create + resolve with hashed-token round-trip."""

from datetime import datetime, timedelta, timezone

import pytest

from markland.db import init_db
from markland.service.invites import create_invite, resolve_invite


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _seed_doc(conn, doc_id="doc_a", owner_id="usr_alice"):
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "(?, 't', 'c', 'tok', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, ?)",
        (doc_id, owner_id),
    )
    conn.commit()


def test_create_invite_returns_id_and_url(conn):
    _seed_doc(conn)
    result = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    assert result.id.startswith("inv_")
    assert result.url.startswith("https://markland.dev/invite/")
    # URL ends with a URL-safe token ~43 chars long.
    token = result.url.rsplit("/", 1)[1]
    assert len(token) >= 40


def test_create_persists_hashed_token_not_plaintext(conn):
    _seed_doc(conn)
    result = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="edit",
        base_url="https://markland.dev",
    )
    token = result.url.rsplit("/", 1)[1]
    row = conn.execute("SELECT token_hash FROM invites WHERE id = ?", (result.id,)).fetchone()
    assert row is not None
    # Stored value is a hash, not the plaintext.
    assert row[0] != token
    assert len(row[0]) > 50  # argon2id hashes are long encoded strings


def test_resolve_invite_returns_invite_for_valid_token(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    inv = resolve_invite(conn, token)
    assert inv is not None
    assert inv.id == r.id
    assert inv.doc_id == "doc_a"
    assert inv.level == "view"


def test_resolve_invite_returns_none_for_unknown_token(conn):
    assert resolve_invite(conn, "not_a_real_token_aaaaaaaaaaaaaaaaaaaaaaaaaa") is None


def test_resolve_invite_returns_none_if_expired(conn):
    _seed_doc(conn)
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        expires_at_override=past,
    )
    token = r.url.rsplit("/", 1)[1]
    assert resolve_invite(conn, token) is None


def test_resolve_invite_returns_none_if_revoked(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    conn.execute(
        "UPDATE invites SET revoked_at = ? WHERE id = ?",
        ("2026-04-19T00:00:00+00:00", r.id),
    )
    conn.commit()
    assert resolve_invite(conn, token) is None


def test_resolve_invite_returns_none_if_no_uses_remaining(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    conn.execute("UPDATE invites SET uses_remaining = 0 WHERE id = ?", (r.id,))
    conn.commit()
    assert resolve_invite(conn, token) is None


def test_create_rejects_unknown_level(conn):
    _seed_doc(conn)
    with pytest.raises(ValueError):
        create_invite(
            conn,
            doc_id="doc_a",
            created_by_user_id="usr_alice",
            level="admin",
            base_url="https://markland.dev",
        )


def test_create_expires_in_days_sets_expires_at(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        expires_in_days=7,
    )
    row = conn.execute("SELECT expires_at FROM invites WHERE id = ?", (r.id,)).fetchone()
    assert row[0] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_invites_create_resolve.py -v`
Expected: FAIL — `markland.service.invites` does not exist.

- [ ] **Step 3: Implement `create_invite` + `resolve_invite`**

Create `src/markland/service/invites.py`:

```python
"""Invite-link service: create, resolve, accept, revoke, list.

Invites are URLs (`/invite/inv_<random>`) that grant an incoming user access
to a specific doc at a specific level. Tokens are stored hashed (argon2id),
identical to how user/agent tokens are stored elsewhere in the service layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from markland.models import Invite
from markland.service.auth import hash_token, verify_token


@dataclass
class CreatedInvite:
    """Returned from `create_invite`; carries the plaintext URL shown to the owner once."""

    id: str
    url: str
    level: str
    expires_at: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_invite(row: Any) -> Invite:
    return Invite(
        id=row["id"],
        token_hash=row["token_hash"],
        doc_id=row["doc_id"],
        level=row["level"],
        single_use=bool(row["single_use"]),
        uses_remaining=row["uses_remaining"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        revoked_at=row["revoked_at"],
    )


def create_invite(
    conn,
    *,
    doc_id: str,
    created_by_user_id: str,
    level: str,
    base_url: str,
    single_use: bool = True,
    expires_in_days: int | None = None,
    expires_at_override: str | None = None,
) -> CreatedInvite:
    """Create an invite row, return the plaintext URL and its id.

    The plaintext token is shown only once — in the returned URL — and then
    discarded. The DB stores only its argon2id hash.
    """
    if level not in ("view", "edit"):
        raise ValueError(f"invalid level: {level!r} (must be 'view' or 'edit')")

    invite_id = Invite.generate_id()
    plaintext_token = Invite.generate_token()
    token_hash = hash_token(plaintext_token)

    created_at = _now_iso()
    if expires_at_override is not None:
        expires_at = expires_at_override
    elif expires_in_days is not None:
        expires_at = (
            datetime.now(timezone.utc) + timedelta(days=expires_in_days)
        ).isoformat()
    else:
        expires_at = None

    uses_remaining = 1 if single_use else 1_000_000  # "effectively unlimited"

    conn.execute(
        "INSERT INTO invites (id, token_hash, doc_id, level, single_use, uses_remaining, "
        "created_by, created_at, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            invite_id,
            token_hash,
            doc_id,
            level,
            1 if single_use else 0,
            uses_remaining,
            created_by_user_id,
            created_at,
            expires_at,
        ),
    )
    conn.commit()

    # URL token IS the plaintext, so callers can paste it.
    url = f"{base_url.rstrip('/')}/invite/{plaintext_token}"
    return CreatedInvite(id=invite_id, url=url, level=level, expires_at=expires_at)


def resolve_invite(conn, token_plaintext: str) -> Invite | None:
    """Return the Invite matching `token_plaintext`, or None if no active invite exists.

    Active = not revoked, uses_remaining > 0, not expired.

    We do a linear scan over non-revoked rows with uses_remaining > 0 and
    verify each against argon2id. In practice the set of live invites per
    server is tiny (tens to hundreds); scan is fine. If this ever becomes
    a hotspot we'll shard by a cheap prefix — not today.
    """
    now = _now_iso()
    rows = conn.execute(
        "SELECT id, token_hash, doc_id, level, single_use, uses_remaining, created_by, "
        "created_at, expires_at, revoked_at FROM invites "
        "WHERE revoked_at IS NULL AND uses_remaining > 0 "
        "AND (expires_at IS NULL OR expires_at > ?)",
        (now,),
    ).fetchall()

    for row in rows:
        if verify_token(token_plaintext, row["token_hash"]):
            inv = _row_to_invite(row)
            if inv.is_active(now=now):
                return inv
            return None
    return None
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_invites_create_resolve.py -v`
Expected: PASS (9 tests).

---

## Task 4: `accept_invite` — grant creation, idempotency, decrement

**Files:**
- Modify: `src/markland/service/invites.py`
- Create: `tests/test_service_invites_accept.py`

Spec requirement: acceptance creates a grant via `service.grants.grant_by_principal_id()` (the internal-helper path; the public `grant()` requires email + principal authorization, whereas the invite token itself is the authorization here); idempotent — if the user already has a grant at equal-or-higher level, don't downgrade, but still decrement uses_remaining (treats the URL as consumed). Single-use invites go to 0 after first use.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_invites_accept.py`:

```python
"""service/invites.py: accept_invite end-to-end."""

import pytest

from markland.db import init_db
from markland.service.grants import get_grant, grant_by_principal_id as make_grant
from markland.service.invites import accept_invite, create_invite, resolve_invite


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _seed_doc(conn, doc_id="doc_a", owner_id="usr_alice"):
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "(?, 't', 'c', 'tok', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, ?)",
        (doc_id, owner_id),
    )
    conn.commit()


def _seed_user(conn, user_id, email):
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES (?, ?, ?, 0, '2026-01-01T00:00:00+00:00')",
        (user_id, email, email.split("@")[0]),
    )
    conn.commit()


def _token_from_url(url: str) -> str:
    return url.rsplit("/", 1)[1]


def test_accept_creates_grant_and_decrements_single_use(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    g = accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob")
    assert g is not None
    assert g.principal_id == "usr_bob"
    assert g.doc_id == "doc_a"
    assert g.level == "view"

    # Invite fully consumed.
    row = conn.execute("SELECT uses_remaining FROM invites WHERE id = ?", (r.id,)).fetchone()
    assert row[0] == 0


def test_accept_reusable_decrements_but_stays_active(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    _seed_user(conn, "usr_carol", "carol@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        single_use=False,
    )
    token = _token_from_url(r.url)
    accept_invite(conn, invite_token=token, user_id="usr_bob")
    accept_invite(conn, invite_token=token, user_id="usr_carol")

    row = conn.execute(
        "SELECT uses_remaining FROM invites WHERE id = ?", (r.id,)
    ).fetchone()
    # Decremented twice from starting pool.
    assert row[0] == 1_000_000 - 2
    # Still resolvable.
    assert resolve_invite(conn, token) is not None


def test_accept_idempotent_does_not_downgrade_higher_grant(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    # Bob already has edit on doc_a.
    make_grant(
        conn,
        doc_id="doc_a",
        principal_id="usr_bob",
        principal_type="user",
        level="edit",
        granted_by="usr_alice",
    )
    # Invite only offers view.
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    g = accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob")
    # Returned grant reflects actual grant row (still edit).
    assert g.level == "edit"
    # Use still decremented.
    row = conn.execute("SELECT uses_remaining FROM invites WHERE id = ?", (r.id,)).fetchone()
    assert row[0] == 0


def test_accept_upgrades_view_to_edit(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    # Bob has view.
    make_grant(
        conn,
        doc_id="doc_a",
        principal_id="usr_bob",
        principal_type="user",
        level="view",
        granted_by="usr_alice",
    )
    # Invite offers edit.
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="edit",
        base_url="https://markland.dev",
    )
    g = accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob")
    assert g.level == "edit"
    actual = get_grant(conn, doc_id="doc_a", principal_id="usr_bob")
    assert actual.level == "edit"


def test_accept_unknown_token_returns_none(conn):
    g = accept_invite(conn, invite_token="not_real_aaaaaaaaaaaaaaaaaaaaaaaa", user_id="usr_bob")
    assert g is None


def test_accept_expired_invite_returns_none(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
        expires_at_override="2020-01-01T00:00:00+00:00",
    )
    assert accept_invite(conn, invite_token=_token_from_url(r.url), user_id="usr_bob") is None


def test_accept_used_up_invite_returns_none(conn):
    _seed_doc(conn)
    _seed_user(conn, "usr_bob", "bob@example.com")
    _seed_user(conn, "usr_carol", "carol@example.com")
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = _token_from_url(r.url)
    # First accept consumes it.
    assert accept_invite(conn, invite_token=token, user_id="usr_bob") is not None
    # Second accept gets nothing.
    assert accept_invite(conn, invite_token=token, user_id="usr_carol") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_invites_accept.py -v`
Expected: FAIL — `accept_invite` not defined.

- [ ] **Step 3: Implement `accept_invite`**

Append to `src/markland/service/invites.py`:

```python
from markland.models import Grant  # type: ignore[import-not-found]
from markland.service.grants import get_grant, grant_by_principal_id


_LEVEL_ORDER = {"view": 1, "edit": 2}


def _level_at_least(existing: str, wanted: str) -> bool:
    return _LEVEL_ORDER.get(existing, 0) >= _LEVEL_ORDER.get(wanted, 0)


def accept_invite(conn, *, invite_token: str, user_id: str) -> Grant | None:
    """Consume one use of the invite and ensure `user_id` has a grant at
    (at least) the invite's level on the invite's doc.

    Idempotent: if the user already has a grant at equal-or-higher level, the
    existing grant is returned unchanged — but `uses_remaining` is still
    decremented, because the URL was presented.

    Returns the resulting Grant, or None if the invite was not acceptable
    (unknown / expired / revoked / used up).

    Note: acceptance uses the internal-helper path
    `service.grants.grant_by_principal_id` (not the public `grant()`, which
    expects an email + principal authorization). The invite token itself is
    the authorization to create a grant for `user_id`.
    """
    inv = resolve_invite(conn, invite_token)
    if inv is None:
        return None

    # Decrement uses_remaining (single_use → 0 after first use).
    new_remaining = 0 if inv.single_use else max(inv.uses_remaining - 1, 0)
    conn.execute(
        "UPDATE invites SET uses_remaining = ? WHERE id = ?",
        (new_remaining, inv.id),
    )
    conn.commit()

    # Decide whether to upsert the grant.
    existing = get_grant(conn, doc_id=inv.doc_id, principal_id=user_id)
    if existing is not None and _level_at_least(existing.level, inv.level):
        # Don't downgrade; return the existing grant.
        return existing

    return grant_by_principal_id(
        conn,
        doc_id=inv.doc_id,
        principal_id=user_id,
        principal_type="user",
        level=inv.level,
        granted_by=inv.created_by,
    )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_invites_accept.py -v`
Expected: PASS (7 tests).

---

## Task 5: `revoke_invite`, `list_invites`, and expiry handling

**Files:**
- Modify: `src/markland/service/invites.py`
- Create: `tests/test_service_invites_revoke_list.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_invites_revoke_list.py`:

```python
"""service/invites.py: revoke + list."""

import pytest

from markland.db import init_db
from markland.service.invites import (
    create_invite,
    list_invites,
    resolve_invite,
    revoke_invite,
)


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "t.db")


def _seed_doc(conn, doc_id="doc_a", owner_id="usr_alice"):
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "(?, 't', 'c', 'tok', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 0, 0, ?)",
        (doc_id, owner_id),
    )
    conn.commit()


def test_revoke_invite_sets_revoked_at(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    revoke_invite(conn, invite_id=r.id, owner_user_id="usr_alice")
    row = conn.execute(
        "SELECT revoked_at FROM invites WHERE id = ?", (r.id,)
    ).fetchone()
    assert row[0] is not None


def test_revoke_invite_rejects_non_owner(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    with pytest.raises(PermissionError):
        revoke_invite(conn, invite_id=r.id, owner_user_id="usr_mallory")


def test_revoke_invite_unknown_id_raises(conn):
    with pytest.raises(ValueError):
        revoke_invite(conn, invite_id="inv_does_not_exist", owner_user_id="usr_alice")


def test_revoked_invite_is_unresolvable(conn):
    _seed_doc(conn)
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    assert resolve_invite(conn, token) is not None
    revoke_invite(conn, invite_id=r.id, owner_user_id="usr_alice")
    assert resolve_invite(conn, token) is None


def test_list_invites_returns_only_the_docs_invites(conn):
    _seed_doc(conn, doc_id="doc_a")
    _seed_doc(conn, doc_id="doc_b")
    create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="view",
                  base_url="https://markland.dev")
    create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="edit",
                  base_url="https://markland.dev")
    create_invite(conn, doc_id="doc_b", created_by_user_id="usr_alice", level="view",
                  base_url="https://markland.dev")

    invites = list_invites(conn, doc_id="doc_a")
    assert len(invites) == 2
    assert {i.level for i in invites} == {"view", "edit"}


def test_list_invites_excludes_revoked_by_default(conn):
    _seed_doc(conn)
    r1 = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="view",
                       base_url="https://markland.dev")
    r2 = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="edit",
                       base_url="https://markland.dev")
    revoke_invite(conn, invite_id=r1.id, owner_user_id="usr_alice")
    active = list_invites(conn, doc_id="doc_a")
    ids = {i.id for i in active}
    assert r2.id in ids
    assert r1.id not in ids


def test_list_invites_include_revoked_true_returns_all(conn):
    _seed_doc(conn)
    r1 = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice", level="view",
                       base_url="https://markland.dev")
    revoke_invite(conn, invite_id=r1.id, owner_user_id="usr_alice")
    all_invites = list_invites(conn, doc_id="doc_a", include_revoked=True)
    assert len(all_invites) == 1
    assert all_invites[0].revoked_at is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_service_invites_revoke_list.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `revoke_invite` and `list_invites`**

Append to `src/markland/service/invites.py`:

```python
def revoke_invite(conn, *, invite_id: str, owner_user_id: str) -> None:
    """Mark an invite revoked. Caller must be the invite's creator OR the doc owner;
    in the current model they're always the same (owners create invites), so we check
    created_by == owner_user_id directly.
    """
    row = conn.execute(
        "SELECT created_by, revoked_at FROM invites WHERE id = ?",
        (invite_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"invite not found: {invite_id}")
    if row["created_by"] != owner_user_id:
        raise PermissionError(
            f"user {owner_user_id} cannot revoke invite {invite_id} (not creator)"
        )
    if row["revoked_at"] is not None:
        return  # already revoked — idempotent no-op
    conn.execute(
        "UPDATE invites SET revoked_at = ? WHERE id = ?",
        (_now_iso(), invite_id),
    )
    conn.commit()


def list_invites(conn, *, doc_id: str, include_revoked: bool = False) -> list[Invite]:
    """Return invites for `doc_id`, ordered newest first.

    By default, revoked invites are hidden (the dialog should show live ones).
    Pass `include_revoked=True` for admin / audit displays.
    """
    if include_revoked:
        where = "WHERE doc_id = ?"
        params: tuple = (doc_id,)
    else:
        where = "WHERE doc_id = ? AND revoked_at IS NULL"
        params = (doc_id,)
    rows = conn.execute(
        "SELECT id, token_hash, doc_id, level, single_use, uses_remaining, created_by, "
        f"created_at, expires_at, revoked_at FROM invites {where} ORDER BY created_at DESC",
        params,
    ).fetchall()
    return [_row_to_invite(r) for r in rows]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_service_invites_revoke_list.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Run the invite service suite together**

Run: `uv run pytest tests/test_service_invites_*.py -v`
Expected: all 23 tests pass.

---

## Task 6: MCP tools — `markland_create_invite`, `markland_revoke_invite`

**Files:**
- Modify: `src/markland/server.py`
- Create: `tests/test_mcp_invite_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_mcp_invite_tools.py`:

```python
"""End-to-end tests for the invite MCP tools via the FastMCP in-process transport."""

import pytest

from markland.db import init_db
from markland.server import build_mcp


@pytest.fixture
def conn(tmp_path):
    conn = init_db(tmp_path / "t.db")
    # Seed alice as owner.
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 't', 'c', 'tok', '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', "
        "0, 0, 'usr_alice')"
    )
    # Non-owner user.
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_mallory', 'mallory@example.com', 'Mallory', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    return conn


def test_markland_create_invite_owner_succeeds(conn):
    tools = build_mcp(conn, base_url="https://markland.dev").tool_functions  # exposed by build_mcp test helper
    out = tools["markland_create_invite"](
        doc_id="doc_a", level="view", principal_id="usr_alice"
    )
    assert out["invite_id"].startswith("inv_")
    assert out["url"].startswith("https://markland.dev/invite/")
    assert out["level"] == "view"
    assert out["expires_at"] is None


def test_markland_create_invite_non_owner_denied(conn):
    tools = build_mcp(conn, base_url="https://markland.dev").tool_functions
    with pytest.raises(PermissionError):
        tools["markland_create_invite"](
            doc_id="doc_a", level="view", principal_id="usr_mallory"
        )


def test_markland_create_invite_bad_level_rejected(conn):
    tools = build_mcp(conn, base_url="https://markland.dev").tool_functions
    with pytest.raises(ValueError):
        tools["markland_create_invite"](
            doc_id="doc_a", level="admin", principal_id="usr_alice"
        )


def test_markland_revoke_invite_owner_succeeds(conn):
    tools = build_mcp(conn, base_url="https://markland.dev").tool_functions
    r = tools["markland_create_invite"](
        doc_id="doc_a", level="view", principal_id="usr_alice"
    )
    result = tools["markland_revoke_invite"](
        invite_id=r["invite_id"], principal_id="usr_alice"
    )
    assert result == {"revoked": True, "invite_id": r["invite_id"]}
    row = conn.execute(
        "SELECT revoked_at FROM invites WHERE id = ?", (r["invite_id"],)
    ).fetchone()
    assert row[0] is not None


def test_markland_revoke_invite_non_owner_denied(conn):
    tools = build_mcp(conn, base_url="https://markland.dev").tool_functions
    r = tools["markland_create_invite"](
        doc_id="doc_a", level="view", principal_id="usr_alice"
    )
    with pytest.raises(PermissionError):
        tools["markland_revoke_invite"](
            invite_id=r["invite_id"], principal_id="usr_mallory"
        )


def test_markland_create_invite_expires_in_days(conn):
    tools = build_mcp(conn, base_url="https://markland.dev").tool_functions
    out = tools["markland_create_invite"](
        doc_id="doc_a", level="edit", expires_in_days=7, principal_id="usr_alice"
    )
    assert out["expires_at"] is not None
```

Note: this test uses a `tool_functions` dict on the `FastMCP` instance. That dict is a test-only convenience we're adding in step 3; real clients call the tools through the MCP protocol, but bare-function access keeps the unit tests fast and transport-free. It's the same pattern used in `tests/test_mcp_grant_tools.py` from Plan 3.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mcp_invite_tools.py -v`
Expected: FAIL.

- [ ] **Step 3: Register the tools in `server.py`**

Modify `src/markland/server.py` — inside `build_mcp`, register two new tools alongside `markland_grant` / `markland_revoke`. The owner check is inline: look up the doc, require `doc.owner_id == principal_id`.

Insert into `build_mcp` (after `markland_list_grants`):

```python
    from markland.service.invites import (
        create_invite as _create_invite,
        revoke_invite as _revoke_invite,
    )

    def _require_owner(doc_id: str, principal_id: str) -> None:
        row = db_conn.execute(
            "SELECT owner_id FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise ValueError(f"doc not found: {doc_id}")
        if row["owner_id"] != principal_id:
            raise PermissionError(
                f"principal {principal_id} is not the owner of {doc_id}"
            )

    @mcp.tool()
    def markland_create_invite(
        doc_id: str,
        level: str,
        single_use: bool = True,
        expires_in_days: int | None = None,
        principal_id: str = "",
    ) -> dict:
        """Owner-only. Create an invite link for a doc.

        `principal_id` is injected by the auth middleware in real requests; the
        default empty string is there so unauthenticated calls fail the owner
        check cleanly rather than raising a type error.
        """
        _require_owner(doc_id, principal_id)
        result = _create_invite(
            db_conn,
            doc_id=doc_id,
            created_by_user_id=principal_id,
            level=level,
            base_url=base_url,
            single_use=single_use,
            expires_in_days=expires_in_days,
        )
        return {
            "invite_id": result.id,
            "url": result.url,
            "level": result.level,
            "expires_at": result.expires_at,
        }

    @mcp.tool()
    def markland_revoke_invite(invite_id: str, principal_id: str = "") -> dict:
        """Owner-only. Revoke an invite so the URL stops working."""
        # Look up the invite's doc to do the owner check.
        row = db_conn.execute(
            "SELECT doc_id FROM invites WHERE id = ?", (invite_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"invite not found: {invite_id}")
        _require_owner(row["doc_id"], principal_id)
        _revoke_invite(db_conn, invite_id=invite_id, owner_user_id=principal_id)
        return {"revoked": True, "invite_id": invite_id}
```

Also, to support the test helper, add (if not already present) at the end of `build_mcp` before `return mcp`:

```python
    # Test helper: lets unit tests call tools as plain functions without the
    # full MCP transport. Safe to attach — production calls never read it.
    mcp.tool_functions = {
        "markland_create_invite": markland_create_invite,
        "markland_revoke_invite": markland_revoke_invite,
        # … merge with existing dict from Plan 3 rather than overwriting …
    }
```

If `tool_functions` already exists from Plan 3, merge into it rather than reassigning.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_mcp_invite_tools.py -v`
Expected: PASS (6 tests).

---

## Task 7: HTTP routes — `POST /api/docs/{id}/invites`, `DELETE /api/invites/{id}`

**Files:**
- Create: `src/markland/web/invite_routes.py`
- Modify: `src/markland/web/app.py`
- Create: `tests/test_http_invite_routes.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_http_invite_routes.py`:

```python
"""HTTP routes for invite creation and revocation."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://test.markland.dev")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_mallory', 'm@m.com', 'Mallory', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Alice doc', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    app = create_app(
        conn,
        base_url="https://test.markland.dev",
        email_client=EmailClient(api_key="", from_email="t@t.dev"),
    )
    with TestClient(app) as c:
        yield c, conn


def _login_as(client, user_id):
    """Set a session cookie for `user_id` without a full magic-link round-trip.

    Uses the test-only endpoint `/api/_test/login` which Plan 2 wired for
    fixtures. If that doesn't exist, forge the session cookie directly via the
    SessionService — same approach used in tests/test_http_grant_routes.py.
    """
    r = client.post("/api/_test/login", json={"user_id": user_id})
    assert r.status_code == 200


def test_create_invite_owner_succeeds(client):
    c, _ = client
    _login_as(c, "usr_alice")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "view", "single_use": True},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["id"].startswith("inv_")
    assert body["url"].startswith("https://test.markland.dev/invite/")
    assert body["level"] == "view"


def test_create_invite_non_owner_denied(client):
    c, _ = client
    _login_as(c, "usr_mallory")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "view", "single_use": True},
    )
    assert r.status_code in (403, 404)  # see spec §12.5


def test_create_invite_unauthenticated_rejected(client):
    c, _ = client
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "view", "single_use": True},
    )
    assert r.status_code == 401


def test_create_invite_bad_level_400(client):
    c, _ = client
    _login_as(c, "usr_alice")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "admin", "single_use": True},
    )
    assert r.status_code == 400


def test_delete_invite_owner_succeeds(client):
    c, conn = client
    _login_as(c, "usr_alice")
    r = c.post("/api/docs/doc_a/invites", json={"level": "view", "single_use": True})
    invite_id = r.json()["id"]

    r2 = c.delete(f"/api/invites/{invite_id}")
    assert r2.status_code == 204
    row = conn.execute("SELECT revoked_at FROM invites WHERE id = ?", (invite_id,)).fetchone()
    assert row[0] is not None


def test_delete_invite_non_owner_denied(client):
    c, _ = client
    _login_as(c, "usr_alice")
    created = c.post("/api/docs/doc_a/invites", json={"level": "view", "single_use": True})
    invite_id = created.json()["id"]

    _login_as(c, "usr_mallory")
    r = c.delete(f"/api/invites/{invite_id}")
    assert r.status_code in (403, 404)


def test_create_invite_expires_in_days(client):
    c, _ = client
    _login_as(c, "usr_alice")
    r = c.post(
        "/api/docs/doc_a/invites",
        json={"level": "edit", "single_use": False, "expires_in_days": 14},
    )
    assert r.status_code == 201
    assert r.json()["expires_at"] is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_http_invite_routes.py -v`
Expected: FAIL — the routes don't exist.

- [ ] **Step 3: Create the routes module**

Create `src/markland/web/invite_routes.py`:

```python
"""HTTP routes for invite creation, revocation, acceptance, and the landing page."""

from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from jinja2 import Environment
from pydantic import BaseModel, Field

from markland.service.email import EmailClient, EmailSendError
from markland.service.invites import (
    accept_invite,
    create_invite,
    list_invites,
    resolve_invite,
    revoke_invite,
)


class _CreateInviteBody(BaseModel):
    level: str = Field(pattern="^(view|edit)$")
    single_use: bool = True
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


def build_invite_router(
    *,
    db_conn: sqlite3.Connection,
    base_url: str,
    jinja_env: Environment,
    email_client: EmailClient,
    get_current_user,  # FastAPI dependency: returns user_id or raises 401
    get_optional_user,  # returns user_id or None
) -> APIRouter:
    """Return a router carrying all invite HTTP + HTML routes.

    `get_current_user` and `get_optional_user` are the session dependencies
    added in Plan 2; they read the session cookie and resolve it to a user id.
    """
    router = APIRouter()
    invite_tpl = jinja_env.get_template("invite.html")
    pending_tpl = jinja_env.get_template("invite_pending.html")

    def _require_owner(doc_id: str, user_id: str) -> dict:
        row = db_conn.execute(
            "SELECT id, title, owner_id FROM documents WHERE id = ?",
            (doc_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        if row["owner_id"] != user_id:
            # Per spec §12.5, return 404 to avoid leaking existence.
            raise HTTPException(status_code=404, detail="not_found")
        return {"id": row["id"], "title": row["title"]}

    @router.post("/api/docs/{doc_id}/invites", status_code=201)
    def http_create_invite(
        doc_id: str,
        body: _CreateInviteBody,
        user_id: str = Depends(get_current_user),
    ):
        _require_owner(doc_id, user_id)
        try:
            result = create_invite(
                db_conn,
                doc_id=doc_id,
                created_by_user_id=user_id,
                level=body.level,
                base_url=base_url,
                single_use=body.single_use,
                expires_in_days=body.expires_in_days,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {
            "id": result.id,
            "url": result.url,
            "level": result.level,
            "expires_at": result.expires_at,
        }

    @router.delete("/api/invites/{invite_id}", status_code=204)
    def http_delete_invite(invite_id: str, user_id: str = Depends(get_current_user)):
        row = db_conn.execute(
            "SELECT created_by FROM invites WHERE id = ?", (invite_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="not_found")
        if row["created_by"] != user_id:
            raise HTTPException(status_code=404, detail="not_found")
        try:
            revoke_invite(db_conn, invite_id=invite_id, owner_user_id=user_id)
        except (ValueError, PermissionError):
            raise HTTPException(status_code=404, detail="not_found")
        return JSONResponse(status_code=204, content=None)

    @router.get("/invite/{token}", response_class=HTMLResponse)
    def invite_landing(
        token: str,
        request: Request,
        user_id: str | None = Depends(get_optional_user),
    ):
        inv = resolve_invite(db_conn, token)
        if inv is None:
            return HTMLResponse(
                _render_invite_gone(),
                status_code=410,
            )

        doc_row = db_conn.execute(
            "SELECT title, owner_id FROM documents WHERE id = ?", (inv.doc_id,)
        ).fetchone()
        if doc_row is None:
            # Orphan invite — treat as gone.
            return HTMLResponse(_render_invite_gone(), status_code=410)
        inviter_row = db_conn.execute(
            "SELECT display_name, email FROM users WHERE id = ?", (inv.created_by,)
        ).fetchone()
        inviter_name = (
            inviter_row["display_name"]
            if inviter_row and inviter_row["display_name"]
            else (inviter_row["email"] if inviter_row else "Someone")
        )

        return HTMLResponse(
            invite_tpl.render(
                token=token,
                doc_title=doc_row["title"],
                inviter_name=inviter_name,
                level=inv.level,
                signed_in=(user_id is not None),
            )
        )

    @router.post("/api/invites/{token}/accept")
    def http_accept_invite(
        token: str,
        user_id: str = Depends(get_current_user),
    ):
        inv = resolve_invite(db_conn, token)
        if inv is None:
            raise HTTPException(status_code=410, detail="gone")
        grant = accept_invite(db_conn, invite_token=token, user_id=user_id)
        if grant is None:
            raise HTTPException(status_code=410, detail="gone")

        # Best-effort: notify the invite creator.
        _notify_creator(
            db_conn=db_conn,
            email_client=email_client,
            invite_created_by=inv.created_by,
            accepter_user_id=user_id,
            doc_id=inv.doc_id,
            base_url=base_url,
        )

        return {"doc_id": grant.doc_id, "level": grant.level}

    return router


def _render_invite_gone() -> str:
    return (
        "<html><body style='font-family:system-ui;padding:2rem;max-width:40rem;'>"
        "<h1>This invite is no longer valid</h1>"
        "<p>It may have been revoked, fully used, or expired. "
        "Ask the person who sent it for a new one.</p>"
        "</body></html>"
    )


def _notify_creator(
    *,
    db_conn: sqlite3.Connection,
    email_client: EmailClient,
    invite_created_by: str,
    accepter_user_id: str,
    doc_id: str,
    base_url: str,
) -> None:
    creator = db_conn.execute(
        "SELECT email FROM users WHERE id = ?", (invite_created_by,)
    ).fetchone()
    accepter = db_conn.execute(
        "SELECT display_name, email FROM users WHERE id = ?", (accepter_user_id,)
    ).fetchone()
    doc = db_conn.execute(
        "SELECT title, share_token FROM documents WHERE id = ?", (doc_id,)
    ).fetchone()
    if not creator or not accepter or not doc:
        return
    accepter_name = (
        accepter["display_name"]
        if accepter["display_name"]
        else accepter["email"]
    )
    try:
        email_client.send(
            to=creator["email"],
            subject=f"{accepter_name} accepted your Markland invite",
            html=(
                f"<p>{_h(accepter_name)} accepted your invite to "
                f"<a href='{base_url}/d/{doc['share_token']}'>{_h(doc['title'])}</a>.</p>"
            ),
        )
    except EmailSendError:
        # Email is best-effort; swallow errors so acceptance never fails.
        return


def _h(s: str) -> str:
    """Minimal HTML escape for the notification body."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
```

- [ ] **Step 4: Create the HTML template**

Create `src/markland/web/templates/invite.html`:

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Invited to {{ doc_title }} — Markland</title>
    <style>
      body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1.5rem; line-height: 1.5; }
      h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
      .level { display: inline-block; padding: 0.15rem 0.5rem; background: #eef; border-radius: 0.25rem; font-size: 0.85rem; font-weight: 600; }
      form { margin-top: 1.5rem; }
      input[type="email"] { padding: 0.5rem 0.75rem; font-size: 1rem; border: 1px solid #999; border-radius: 0.25rem; width: 100%; box-sizing: border-box; }
      button { margin-top: 0.75rem; padding: 0.6rem 1.2rem; font-size: 1rem; border: 0; border-radius: 0.25rem; background: #111; color: #fff; cursor: pointer; }
      .note { color: #555; font-size: 0.9rem; margin-top: 1rem; }
      .error { color: #b00; margin-top: 0.5rem; }
    </style>
  </head>
  <body>
    <h1>{{ inviter_name }} invited you to <em>{{ doc_title }}</em></h1>
    <p>They're giving you <span class="level">{{ level }}</span> access.</p>

    {% if signed_in %}
      <form id="accept-form">
        <button type="submit">Accept and open document</button>
      </form>
      <script>
        document.getElementById("accept-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const resp = await fetch("/api/invites/{{ token }}/accept", { method: "POST" });
          if (resp.ok) {
            const body = await resp.json();
            // Look up the share token and redirect.
            const doc = await fetch(`/api/docs/${body.doc_id}`).then((r) => r.json());
            window.location.href = `/d/${doc.share_token}`;
          } else {
            const el = document.createElement("p");
            el.className = "error";
            el.textContent = resp.status === 410
              ? "This invite is no longer valid."
              : "Could not accept the invite right now.";
            document.body.appendChild(el);
          }
        });
      </script>
    {% else %}
      <form method="post" action="/api/auth/magic-link">
        <input type="hidden" name="return_to" value="/invite/{{ token }}" />
        <label for="email"><strong>Enter your email to sign in or create an account</strong></label>
        <input type="email" id="email" name="email" required placeholder="you@example.com" autocomplete="email" />
        <button type="submit">Send magic link</button>
      </form>
      <p class="note">
        If you don't have a Markland account, signing in will create one automatically.
        After you click the magic-link in your email, you'll be returned here and can accept the invite.
      </p>
    {% endif %}
  </body>
</html>
```

Create `src/markland/web/templates/invite_pending.html`:

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Check your email — Markland</title>
    <style>body { font-family: system-ui, sans-serif; max-width: 40rem; margin: 4rem auto; padding: 0 1.5rem; line-height: 1.5; }</style>
  </head>
  <body>
    <h1>Check your email</h1>
    <p>We sent a magic link to <strong>{{ email }}</strong>. Click it within 15 minutes to sign in.</p>
    <p>Once you're signed in, you'll land back on the invite page and can accept.</p>
  </body>
</html>
```

- [ ] **Step 5: Wire the router into `create_app`**

Modify `src/markland/web/app.py` — extend `create_app` signature and register the router:

```python
from markland.service.email import EmailClient
from markland.web.invite_routes import build_invite_router
from markland.web.auth_deps import get_current_user, get_optional_user  # Plan 2


def create_app(
    db_conn: sqlite3.Connection,
    *,
    mount_mcp: bool = False,
    admin_token: str = "",
    base_url: str = "",
    email_client: EmailClient | None = None,
) -> FastAPI:
    app = FastAPI(title="Markland", docs_url=None, redoc_url=None)
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    # … existing body unchanged …

    # Invite routes
    ec = email_client or EmailClient(api_key="", from_email="notifications@markland.dev")
    app.include_router(
        build_invite_router(
            db_conn=db_conn,
            base_url=base_url,
            jinja_env=env,
            email_client=ec,
            get_current_user=get_current_user(db_conn),
            get_optional_user=get_optional_user(db_conn),
        )
    )

    # … MCP mount unchanged …
    return app
```

If `auth_deps` does not yet expose factory functions, add them in the same edit — they read the session cookie via the `SessionService` defined in Plan 2 and return either `user_id: str` or raise `HTTPException(401)` / return `None`.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_http_invite_routes.py -v`
Expected: PASS (7 tests).

---

## Task 8: `GET /invite/{token}` HTML page — signed-in path

**Files:**
- Create: `tests/test_http_invite_page_signed_in.py`

The route already exists (Task 7 Step 3). This task pins its behavior for the signed-in path with its own test file.

- [ ] **Step 1: Write the tests**

Create `tests/test_http_invite_page_signed_in.py`:

```python
"""GET /invite/{token} renders the accept page when signed in."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.invites import create_invite
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://test.markland.dev")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice Owner', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Secret Plans', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    app = create_app(conn, base_url="https://test.markland.dev")
    with TestClient(app) as c:
        yield c, conn


def _token_for_new_invite(conn, level="view"):
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level=level,
        base_url="https://test.markland.dev",
    )
    return r.url.rsplit("/", 1)[1]


def test_invite_page_signed_in_shows_accept_button(client):
    c, conn = client
    token = _token_for_new_invite(conn, level="edit")
    c.post("/api/_test/login", json={"user_id": "usr_bob"})
    r = c.get(f"/invite/{token}")
    assert r.status_code == 200
    assert "Accept and open document" in r.text
    assert "Secret Plans" in r.text
    assert "edit" in r.text
    assert "Alice Owner" in r.text


def test_invite_page_signed_out_shows_email_form(client):
    c, conn = client
    token = _token_for_new_invite(conn)
    # No login.
    r = c.get(f"/invite/{token}")
    assert r.status_code == 200
    assert "Send magic link" in r.text
    assert "Secret Plans" in r.text


def test_invite_page_gone_for_unknown_token(client):
    c, _ = client
    r = c.get("/invite/not_a_real_token_aaaaaaaaaaaaaaaaaaaa")
    assert r.status_code == 410


def test_invite_page_gone_after_revoke(client):
    c, conn = client
    token = _token_for_new_invite(conn)
    row = conn.execute("SELECT id FROM invites ORDER BY created_at DESC LIMIT 1").fetchone()
    conn.execute(
        "UPDATE invites SET revoked_at = '2026-04-19T00:00:00+00:00' WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    r = c.get(f"/invite/{token}")
    assert r.status_code == 410
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_http_invite_page_signed_in.py -v`
Expected: PASS (4 tests) — the route was implemented in Task 7. If any fail, fix the template/route rather than the test.

---

## Task 9: `GET /invite/{token}` — inline magic-link signup path (integration)

**Files:**
- Create: `tests/test_invite_signup_flow.py`

- [ ] **Step 1: Write the integration test**

Create `tests/test_invite_signup_flow.py`:

```python
"""Full flow: anon user → magic-link form → email sent → verify → invite accepted → redirect.

This is an end-to-end test that exercises:
- GET /invite/{token} (signed out) renders the form
- POST /api/auth/magic-link creates a magic-link token (Plan 2)
- The email client records what *would* have been sent
- GET /auth/verify?token=… with ?return_to=/invite/{token} logs in + redirects
- POST /api/invites/{token}/accept consumes the invite and returns the grant
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.invites import create_invite
from markland.web.app import create_app


class _RecordingEmailClient(EmailClient):
    """Captures every .send() call for assertions."""

    def __init__(self):
        super().__init__(api_key="", from_email="noreply@test.markland.dev")
        self.sent: list[dict] = []

    def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        return "email_test_id"


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://test.markland.dev")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Alice plan', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    email_client = _RecordingEmailClient()
    app = create_app(
        conn,
        base_url="https://test.markland.dev",
        email_client=email_client,
    )
    client = TestClient(app)
    # Create the invite as Alice (owner) directly against the service.
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level="view",
        base_url="https://test.markland.dev",
    )
    token = r.url.rsplit("/", 1)[1]
    yield client, conn, email_client, token
    client.close()


def test_anon_invite_flow_end_to_end(harness):
    client, conn, email_client, token = harness

    # 1. Anon visits /invite/{token}, sees the email form.
    page = client.get(f"/invite/{token}")
    assert page.status_code == 200
    assert "Send magic link" in page.text

    # 2. Submits the email form. Handler creates a magic-link row AND sends email.
    resp = client.post(
        "/api/auth/magic-link",
        data={"email": "bob@example.com", "return_to": f"/invite/{token}"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    assert len(email_client.sent) >= 1
    assert email_client.sent[-1]["to"] == "bob@example.com"
    magic_html = email_client.sent[-1]["html"]
    # Extract the magic-link URL from the email body.
    import re
    match = re.search(r'href=["\']([^"\']*verify[^"\']*)["\']', magic_html)
    assert match is not None, f"no verify link in email: {magic_html}"
    verify_url = match.group(1)

    # 3. "Click" the magic link — should establish session and redirect back to /invite/{token}.
    verify_resp = client.get(verify_url, follow_redirects=False)
    assert verify_resp.status_code in (302, 303)
    assert verify_resp.headers["location"].endswith(f"/invite/{token}")

    # 4. Re-fetch the invite page; should now show the accept button for the new user.
    accept_page = client.get(f"/invite/{token}")
    assert accept_page.status_code == 200
    assert "Accept and open document" in accept_page.text

    # 5. Accept.
    accept = client.post(f"/api/invites/{token}/accept")
    assert accept.status_code == 200
    body = accept.json()
    assert body["doc_id"] == "doc_a"
    assert body["level"] == "view"

    # Grant row exists.
    g = conn.execute(
        "SELECT principal_id, level FROM grants WHERE doc_id = ?", ("doc_a",)
    ).fetchall()
    principals = {r["principal_id"] for r in g}
    assert any(p.startswith("usr_") and p != "usr_alice" for p in principals)

    # Invite is now consumed.
    inv_row = conn.execute("SELECT uses_remaining FROM invites").fetchone()
    assert inv_row[0] == 0
```

- [ ] **Step 2: Ensure `/api/auth/magic-link` supports `return_to`**

If Plan 2's magic-link endpoint doesn't propagate a `return_to` form field into the verification URL, extend it:

Modify `src/markland/service/magic_link.py` — `issue_magic_link_token` accepts an optional `return_to` string and persists it in the `magic_link_tokens` row (add a column if needed in a migration step). `verify_magic_link_token` returns `(user_id, return_to)`, and the `/auth/verify` HTTP route redirects to `return_to` (falling back to `/dashboard` or `/`).

Whitelist `return_to` prefixes to avoid open-redirect: only allow paths starting with `/` and not `//`.

Concretely, add to `src/markland/service/magic_link.py`:

```python
def _safe_return_to(raw: str | None) -> str:
    if not raw:
        return "/"
    if not raw.startswith("/") or raw.startswith("//"):
        return "/"
    return raw
```

and thread it through the token create + verify path. Existing tests for Plan 2 still pass because the default is `/`.

- [ ] **Step 3: Run the integration test**

Run: `uv run pytest tests/test_invite_signup_flow.py -v`
Expected: PASS (1 test).

If it fails because of template mismatches in the magic-link email (the regex can't find the verify URL), tweak the template to include the `href` anchor — the test intentionally parses real email content.

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: all tests pass.

---

## Task 10: `POST /api/invites/{token}/accept` explicit tests

**Files:**
- Create: `tests/test_http_invite_accept.py`

The endpoint is already implemented in Task 7. This task adds focused tests for auth + idempotency at the HTTP layer.

- [ ] **Step 1: Write the tests**

Create `tests/test_http_invite_accept.py`:

```python
"""POST /api/invites/{token}/accept."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.invites import create_invite
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://test.markland.dev")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'P', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()
    app = create_app(conn, base_url="https://test.markland.dev")
    with TestClient(app) as c:
        yield c, conn


def _invite(conn, level="view", single_use=True):
    r = create_invite(
        conn,
        doc_id="doc_a",
        created_by_user_id="usr_alice",
        level=level,
        base_url="https://test.markland.dev",
        single_use=single_use,
    )
    return r.url.rsplit("/", 1)[1]


def test_accept_unauthenticated_returns_401(client):
    c, conn = client
    token = _invite(conn)
    r = c.post(f"/api/invites/{token}/accept")
    assert r.status_code == 401


def test_accept_authenticated_creates_grant(client):
    c, conn = client
    token = _invite(conn, level="edit")
    c.post("/api/_test/login", json={"user_id": "usr_bob"})
    r = c.post(f"/api/invites/{token}/accept")
    assert r.status_code == 200
    assert r.json() == {"doc_id": "doc_a", "level": "edit"}


def test_accept_same_invite_twice_single_use_second_is_410(client):
    c, conn = client
    token = _invite(conn)
    c.post("/api/_test/login", json={"user_id": "usr_bob"})
    first = c.post(f"/api/invites/{token}/accept")
    assert first.status_code == 200

    # Create a third user and try the same token.
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_carol', 'c@c.com', 'C', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.commit()
    c.post("/api/_test/login", json={"user_id": "usr_carol"})
    second = c.post(f"/api/invites/{token}/accept")
    assert second.status_code == 410


def test_accept_unknown_token_410(client):
    c, _ = client
    c.post("/api/_test/login", json={"user_id": "usr_bob"})
    r = c.post("/api/invites/not_a_real_token_aaaaaaaaaaaaaaaaaaa/accept")
    assert r.status_code == 410
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_http_invite_accept.py -v`
Expected: PASS (4 tests).

---

## Task 11: Creator-notification email on accept (best-effort)

**Files:**
- Create: `tests/test_invite_accept_email.py`

The notification call site is already in Task 7 Step 3 (`_notify_creator`). This task pins its behavior.

- [ ] **Step 1: Write the tests**

Create `tests/test_invite_accept_email.py`:

```python
"""Invite-acceptance triggers a best-effort email to the invite creator."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient, EmailSendError
from markland.service.invites import create_invite
from markland.web.app import create_app


class _RecordingEmailClient(EmailClient):
    def __init__(self, *, fail: bool = False):
        super().__init__(api_key="test", from_email="noreply@test.markland.dev")
        self.sent: list[dict] = []
        self._fail = fail

    def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        if self._fail:
            raise EmailSendError("fake failure")
        return "email_test_id"


def _make_app(tmp_path, monkeypatch, email_client):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://test.markland.dev")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_bob', 'bob@example.com', 'Bob Q', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Plans 2026', 'c', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()
    app = create_app(conn, base_url="https://test.markland.dev", email_client=email_client)
    return app, conn


def test_accept_sends_email_to_creator(tmp_path, monkeypatch):
    ec = _RecordingEmailClient()
    app, conn = _make_app(tmp_path, monkeypatch, ec)
    r = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice",
                      level="view", base_url="https://test.markland.dev")
    token = r.url.rsplit("/", 1)[1]
    with TestClient(app) as c:
        c.post("/api/_test/login", json={"user_id": "usr_bob"})
        accept = c.post(f"/api/invites/{token}/accept")
        assert accept.status_code == 200

    assert len(ec.sent) == 1
    msg = ec.sent[0]
    assert msg["to"] == "alice@example.com"
    assert "Bob Q" in msg["html"]
    assert "Plans 2026" in msg["html"]
    assert "accepted" in msg["subject"].lower()


def test_accept_succeeds_even_when_email_fails(tmp_path, monkeypatch):
    ec = _RecordingEmailClient(fail=True)
    app, conn = _make_app(tmp_path, monkeypatch, ec)
    r = create_invite(conn, doc_id="doc_a", created_by_user_id="usr_alice",
                      level="view", base_url="https://test.markland.dev")
    token = r.url.rsplit("/", 1)[1]
    with TestClient(app) as c:
        c.post("/api/_test/login", json={"user_id": "usr_bob"})
        accept = c.post(f"/api/invites/{token}/accept")
    # Invite still accepted despite email failure.
    assert accept.status_code == 200
    assert accept.json()["doc_id"] == "doc_a"
    g = conn.execute(
        "SELECT level FROM grants WHERE doc_id = ? AND principal_id = ?",
        ("doc_a", "usr_bob"),
    ).fetchone()
    assert g["level"] == "view"
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/test_invite_accept_email.py -v`
Expected: PASS (2 tests). If the second test fails with an uncaught `EmailSendError`, revisit `_notify_creator` — all exceptions inside must be swallowed (except `EmailSendError` which we catch explicitly; broaden to `Exception` if needed).

---

## Task 12: End-to-end smoke test (sign-out → anon → magic link → accept → doc)

**Files:**
- Create: `tests/test_invite_smoke.py`

Mirrors the spec §6.3 happy path. Some overlap with Task 9; this one asserts at the redirect level, confirming an MCP-style operator can follow the full arc with nothing but HTTP.

- [ ] **Step 1: Write the test**

Create `tests/test_invite_smoke.py`:

```python
"""End-to-end spec §6.3: owner creates invite → signs out → anon opens URL →
magic-link sign-up → invite accepted → redirected to doc. Single test, full arc."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service.email import EmailClient
from markland.web.app import create_app


class _Recorder(EmailClient):
    def __init__(self):
        super().__init__(api_key="", from_email="noreply@test")
        self.sent = []

    def send(self, *, to, subject, html):
        self.sent.append({"to": to, "subject": subject, "html": html})
        return "e"


def test_invite_spec_6_3_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://test.markland.dev")
    from markland.config import reset_config
    reset_config()

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'alice@example.com', 'Alice', 0, '2026-01-01T00:00:00+00:00')"
    )
    conn.execute(
        "INSERT INTO documents (id, title, content, share_token, created_at, updated_at, "
        "is_public, is_featured, owner_id) VALUES "
        "('doc_a', 'Launch doc', 'body', 'tok_a', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00', 0, 0, 'usr_alice')"
    )
    conn.commit()

    ec = _Recorder()
    app = create_app(conn, base_url="https://test.markland.dev", email_client=ec)
    with TestClient(app) as c:
        # 1. Alice logs in and creates the invite via HTTP.
        c.post("/api/_test/login", json={"user_id": "usr_alice"})
        create = c.post(
            "/api/docs/doc_a/invites",
            json={"level": "edit", "single_use": True},
        )
        assert create.status_code == 201
        invite_url = create.json()["url"]
        token = invite_url.rsplit("/", 1)[1]

        # 2. Alice signs out; Bob visits the URL.
        c.post("/api/auth/logout")

        # 3. Anon GET: email form.
        anon_page = c.get(f"/invite/{token}")
        assert anon_page.status_code == 200
        assert "Send magic link" in anon_page.text

        # 4. Anon POSTs email form.
        n_before = len(ec.sent)
        c.post(
            "/api/auth/magic-link",
            data={"email": "bob@example.com", "return_to": f"/invite/{token}"},
        )
        assert len(ec.sent) == n_before + 1

        # 5. Extract magic-link URL from the email and follow it.
        match = re.search(r'href=["\']([^"\']*verify[^"\']*)["\']', ec.sent[-1]["html"])
        assert match
        verify = match.group(1)
        follow = c.get(verify, follow_redirects=False)
        assert follow.status_code in (302, 303)
        assert follow.headers["location"].endswith(f"/invite/{token}")

        # 6. Bob is now signed in; landing page shows the Accept button.
        landing = c.get(f"/invite/{token}")
        assert landing.status_code == 200
        assert "Accept and open document" in landing.text

        # 7. Bob accepts. Grant row is created.
        accept = c.post(f"/api/invites/{token}/accept")
        assert accept.status_code == 200
        assert accept.json() == {"doc_id": "doc_a", "level": "edit"}

    # 8. Verify grant row exists for Bob at edit level.
    bob_row = conn.execute(
        "SELECT u.id, g.level FROM users u JOIN grants g ON g.principal_id = u.id "
        "WHERE u.email = 'bob@example.com' AND g.doc_id = 'doc_a'"
    ).fetchone()
    assert bob_row is not None
    assert bob_row["level"] == "edit"

    # 9. Creator received a notification email.
    subjects = [m["subject"] for m in ec.sent]
    assert any("accepted" in s.lower() for s in subjects)

    # 10. Invite is consumed (single-use).
    inv_row = conn.execute("SELECT uses_remaining FROM invites").fetchone()
    assert inv_row["uses_remaining"] == 0
```

- [ ] **Step 2: Run the smoke test**

Run: `uv run pytest tests/test_invite_smoke.py -v`
Expected: PASS (1 test).

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: every prior test from Plans 1–4 still passes, plus ~35 new tests added in this plan.

---

## Completion criteria

- `uv run pytest tests/ -v` is green. New test files: `test_invites_migration.py`, `test_service_invites_create_resolve.py`, `test_service_invites_accept.py`, `test_service_invites_revoke_list.py`, `test_mcp_invite_tools.py`, `test_http_invite_routes.py`, `test_http_invite_page_signed_in.py`, `test_invite_signup_flow.py`, `test_http_invite_accept.py`, `test_invite_accept_email.py`, `test_invite_smoke.py`.
- Running `MARKLAND_ADMIN_TOKEN=t uv run python src/markland/run_app.py`, an owner can:
  1. `curl -XPOST -H "Cookie: <session>" https://.../api/docs/<id>/invites -d '{"level":"view","single_use":true}'` → receive a `{id, url, level, expires_at}` JSON response.
  2. `curl https://.../invite/<token>` anonymously → HTML with email form.
  3. POST email, click the magic link, land back on the invite page.
  4. POST `/api/invites/<token>/accept` → `{doc_id, level}`.
  5. `DELETE /api/invites/<id>` as the owner → 204, URL now 410.
- `markland_create_invite` and `markland_revoke_invite` are callable via MCP (both stdio and HTTP-mounted) and perform owner-check correctly.
- The invite acceptance flow sends a best-effort email to the invite creator without blocking the acceptance on email failure.
- The invite URL format is `{base_url}/invite/<urlsafe-token>`; tokens are hashed at rest (argon2id).
- Idempotent acceptance: repeat-accepting a user at equal-or-higher level does not downgrade, but still decrements `uses_remaining`.

## What this plan does NOT deliver

- **Device-flow piggyback** — sharing `?invite=<token>` on `/setup` so the Claude-Code onboarding URL both authorizes the device *and* accepts the invite in one click is Plan 6 (`2026-04-19-device-flow.md`). At the end of Plan 5, an invite still requires a browser visit to `/invite/<token>`.
- **Web UI share dialog integration** — the invite create/revoke HTTP routes exist, but the polished "Share" dialog on the doc viewer that drives them is part of Plan 10 (launch polish). Until then, the dialog shipped in Plan 3 still only supports direct grants.
- **Email templates beyond the one-liner** — richer creator-notification emails (digest, unsubscribe link) arrive in Plan 7 (`2026-04-19-email-notifications.md`).
- **Rate limiting on invite creation / acceptance** — Plan 10.
- **Audit-log rows for `invite_create` and `invite_accept`** — the spec §10.1 lists these actions, but the audit_log table isn't built until Plan 10.
- **Invite link to an email-that-doesn't-have-an-account automatic flow** — spec §6.1 "fall back to the invite-link flow" when the grantee's email isn't found is a direct-grant concern and was covered in Plan 3. This plan's invite flow is the surface that backs it.
