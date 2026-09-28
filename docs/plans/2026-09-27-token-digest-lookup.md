# Token Digest Lookup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bearer-token resolves find their row with one indexed SHA-256 digest lookup instead of Argon2, so valid and failed auth both stop costing ~0.1–1.6 CPU-s per request on the 6.25%-baseline Fly VM.

**Architecture:** Add a nullable, uniquely-indexed `tokens.token_digest`. Mint writes it alongside the Argon2 hash, which stays for rollback safety. `resolve_token` looks up the digest first. Only rows with no digest yet fall back to Argon2: by the embedded token_id (b), or by scanning pre-cutoff legacy rows (c). Either fallback backfills the digest through the existing `last_used_at` touch statement. The in-process cache, middleware and eviction rules stay as they are.

**Tech Stack:** Python 3.12, sqlite3 (stdlib), argon2-cffi, FastAPI/Starlette, pytest, uv.

**Spec:** `docs/specs/2026-09-27-token-digest-lookup-design.md`. Read its "Decision", "Resolve order", "Lazy backfill" and "Rollback safety" sections before Task 3.

## Global Constraints

- `tokens.token_digest TEXT`: nullable, no default. Add it only through `_add_column_if_missing`, never in the `CREATE TABLE` text. Uniqueness comes only from `CREATE UNIQUE INDEX IF NOT EXISTS idx_tokens_digest ON tokens(token_digest)`.
- The digest is `hashlib.sha256(plaintext.encode("utf-8")).hexdigest()` of the exact bearer plaintext: keyless, no prefix, lowercase hex.
- Every mint keeps writing the Argon2 `token_hash = hash_token(plaintext)`. Never write a digest or a sentinel into `token_hash`, and never drop `idx_token_hash`.
- `hash_token` and `verify_token` don't change, because invites use them. Keep these names:
  - `_resolve_uncached(conn, plaintext)`, whose two-argument signature is monkeypatched by a test.
  - `_resolve_by_token_id`, `_resolve_legacy`, `_build_principal_and_touch`.
  - The new seam is `_resolve_by_digest(conn, digest)`.
- Argon2 runs only against rows with `token_digest IS NULL AND revoked_at IS NULL` whose principal is not a revoked agent (`_NOT_REVOKED_AGENT`). `revoke_agent` leaves the agent's token rows unrevoked, and those rows can never authenticate.
- The digest is written only by the existing touch statement: `UPDATE tokens SET last_used_at = ?, token_digest = COALESCE(token_digest, ?) WHERE id = ?`.
  - It runs only after a digest hit, or after a successful Argon2 verify of that exact row.
  - It stays inside the existing `try: … conn.commit() except sqlite3.Error: pass`.
  - Add no new write, commit, transaction, lock or threadpool hop to the resolve path.
- `resolve_token` stays synchronous. `_ResolvedTokenCache` (TTL 60 s, eviction rules) is unchanged, with no negative caching.
- `LEGACY_TOKEN_CUTOFF = "2026-05-10T00:00:00+00:00"`, and it applies only to fallback (c).
- No new dependencies, secrets, env vars or config values.
- Never print, log or paste a real token plaintext or digest: not in the bench, the PR, logs or prod terminal output. Synthetic tokens minted inside pytest can appear in assertion-failure output; don't paste that output anywhere public. Sentry's frame-local capture already exposes resolver locals, including `plaintext`. That exposure predates this plan; Task 8 files it as a bead.
- Timing assertions live only in `tests/bench_resolve_token.py`, which pytest does not collect. Pytest asserts counts, SQL and query plans only.
- Code ships worktree → PR → squash-merge, and the merge deploys. Merge only at a quiet time and with the user's explicit go-ahead (`docs/runbooks/admin-operations.md` § "Deploy hygiene on Fly shared-cpu").

## Review Focus

1. **Rollback-window rows.** After a rollback, the pre-digest release mints new-shape tokens with no digest, created after the cutoff. After the roll-forward they must resolve through (b) and get backfilled. Covered by Task 3's `test_rollback_window_token_resolves_and_backfills` and `test_rollback_window_agent_token_resolves_and_backfills`.
2. **Digest planting.** A caller who knows a victim's token_id presents `mk_usr_<victim id>_<own secret>`. That must return None and must not bind a digest to the victim's row. Covered by Task 3's `test_known_token_id_with_wrong_secret_cannot_plant_a_digest`. Planting through the legacy scan (c) is covered by the digest assertion in Task 4's `test_unknown_bearer_verifies_only_pre_cutoff_digestless_rows`.
3. **A forgotten client retries a revoked agent's pre-digest token.** `revoke_agent` leaves token rows unrevoked, and the touch never runs for a revoked agent, so the row can never be backfilled. It must cost no Argon2 on every retry, and must not hold the counts above 0 forever. Covered by Task 3's `test_revoked_agents_digestless_tokens_cost_no_argon2` and the revoked-agent row in Task 5's `test_token_digest_counts`.
4. **Backfill write fails** (locked DB, shared-connection race). Auth must still succeed, the row stays NULL, and the next uncached resolve retries the backfill. Covered by Task 3's `test_failed_backfill_write_does_not_block_auth_and_is_retried`.
5. **Legacy plaintext that parses as new-shape** (the CRITICAL fall-through). It must still resolve through (c) once the cutoff applies, and get backfilled. Task 3 extends `test_resolve_token_falls_through_to_legacy_on_pk_miss`, and Task 4 re-runs it under the cutoff.

Also tested, though less likely to bite: the admin-script vs app-boot `init_db` race (Task 1), and a legacy token minted just before the cutoff (Task 4).

---

## File structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/markland/db.py` | Migration helper (race-tolerant), `token_digest` column + unique index | 1 |
| `src/markland/service/auth.py` | `token_digest()`, mint dual-write, resolver (a)/(b)/(c), backfill, `LEGACY_TOKEN_CUTOFF`, `token_digest_counts()`, docstrings | 2, 3, 4, 5 |
| `src/markland/web/_request_bearer.py` | Docstring only | 3 |
| `scripts/admin/token_digest_status.py` (new) | Operator counts over `flyctl ssh console` | 5 |
| `tests/conftest.py` | Shared `argon2_verifies` fixture (class-level, self-checking) | 3 |
| `tests/test_db_users_tokens.py` | Schema, upgrade-in-place, migration race | 1 |
| `tests/test_auth_token_digest.py` (new) | Digest, mint, rollback safety, backfill, cutoff, status | 2, 3, 4, 5 |
| `tests/test_service_auth.py`, `tests/test_auth_token_cache.py`, `tests/test_auth_resolve_once_per_request.py` | Argon2-count assertions rewritten to the new contract | 3, 4 |
| `tests/bench_resolve_token.py` (new, not collected) | Before/after CPU evidence for the PR | 6 |
| `src/markland/web/templates/privacy.html`, `docs/ARCHITECTURE.md`, `docs/FOLLOW-UPS.md`, `docs/runbooks/admin-operations.md` | Copy and docs | 5, 7 |

## Before you start

- [ ] **Claim the bead and create the worktree** (from the primary worktree, which must be on `main`):

```bash
cd /Users/daveyhiles/Developer/markland
git branch --show-current            # must print: main
git pull --ff-only
bd update markland-tex --status=in_progress
git worktree add .worktrees/token-digest -b feat/token-digest-lookup
cd .worktrees/token-digest
uv sync --all-extras   # dev extra = pytest, pytest-asyncio, httpx (same as CI)
```

- [ ] **Confirm the spec and plan are on `main`.** They were committed there before execution.

Run: `test -f docs/specs/2026-09-27-token-digest-lookup-design.md && test -f docs/plans/2026-09-27-token-digest-lookup.md && echo ok`
Expected: `ok`. If not, stop: the worktree was created from a stale `main`.

- [ ] **Baseline: the auth subset is green before any change.**

Run: `uv run pytest tests/test_service_auth.py tests/test_auth_token_cache.py tests/test_auth_token_cache_revoke_failures.py tests/test_auth_resolve_once_per_request.py tests/test_db_users_tokens.py`
Expected: all pass, 0 failed.

Every command below runs from `.worktrees/token-digest`. `git rev-parse --show-toplevel` must not print the primary path.

---

### Task 1: Schema — `token_digest` column, unique index, race-tolerant migration helper

**Files:**
- Modify: `src/markland/db.py:15-20` (`_add_column_if_missing`), `src/markland/db.py:121-122` (tokens indexes)
- Test: `tests/test_db_users_tokens.py`

**Interfaces:**
- Consumes: nothing.
- Produces: the `tokens.token_digest` column (TEXT, nullable) and the unique index `idx_tokens_digest`, both present after every `init_db()`, on fresh and on upgraded DBs. `_add_column_if_missing` no longer raises when another process added the column first.

- [ ] **Step 1: Write the failing tests**

In `tests/test_db_users_tokens.py`, replace the import line `from markland.db import init_db` at the top with:

```python
import sqlite3

import pytest

from markland import db
from markland.db import init_db
```

Replace `test_tokens_table_has_expected_columns` with:

```python
def test_tokens_table_has_expected_columns(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cols = _columns(conn, "tokens")
    assert set(cols) == {
        "id",
        "token_hash",
        "token_digest",
        "label",
        "principal_type",
        "principal_id",
        "created_at",
        "last_used_at",
        "revoked_at",
    }
    assert cols["token_digest"] == "TEXT"
```

Add these after `test_tokens_has_token_hash_index`:

```python
def test_tokens_has_unique_digest_index(tmp_path):
    conn = init_db(tmp_path / "t.db")
    unique = {r[1]: r[2] for r in conn.execute("PRAGMA index_list(tokens)")}
    assert unique.get("idx_tokens_digest") == 1
    cols = [r[2] for r in conn.execute("PRAGMA index_info(idx_tokens_digest)")]
    assert cols == ["token_digest"]


def _insert_token_row(conn, token_id: str, digest: str | None) -> None:
    conn.execute(
        "INSERT INTO tokens(id, token_hash, token_digest, label, principal_type, "
        "principal_id, created_at, last_used_at, revoked_at) "
        "VALUES (?, 'h', ?, NULL, 'user', 'usr_x', '2026-09-27T00:00:00+00:00', NULL, NULL)",
        (token_id, digest),
    )


def test_token_digest_allows_many_nulls_but_no_duplicates(tmp_path):
    conn = init_db(tmp_path / "t.db")
    for i in range(3):
        _insert_token_row(conn, f"tok_null{i}", None)
    _insert_token_row(conn, "tok_a", "d" * 64)
    with pytest.raises(sqlite3.IntegrityError):
        _insert_token_row(conn, "tok_b", "d" * 64)


_PRE_DIGEST_TOKENS_DDL = """
    CREATE TABLE tokens (
        id TEXT PRIMARY KEY,
        token_hash TEXT NOT NULL,
        label TEXT,
        principal_type TEXT NOT NULL,
        principal_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        last_used_at TEXT,
        revoked_at TEXT
    )
"""


def test_init_db_upgrades_a_pre_digest_tokens_table_in_place(tmp_path):
    """Prod's tokens table predates token_digest: init_db must add the
    column and index in place, leave existing rows NULL, and stay
    idempotent across boots."""
    db_path = tmp_path / "old.db"
    old = sqlite3.connect(str(db_path))
    old.execute(_PRE_DIGEST_TOKENS_DDL)
    old.execute(
        "INSERT INTO tokens VALUES ('tok_old', 'h', 'l', 'user', 'usr_x', "
        "'2026-01-01T00:00:00+00:00', NULL, NULL)"
    )
    old.commit()
    old.close()

    init_db(db_path).close()
    conn = init_db(db_path)  # second boot: no-op, must not raise

    assert "token_digest" in _columns(conn, "tokens")
    assert "idx_tokens_digest" in _indexes(conn, "tokens")
    row = conn.execute(
        "SELECT token_hash, token_digest FROM tokens WHERE id = 'tok_old'"
    ).fetchone()
    assert row == ("h", None)


def test_add_column_if_missing_tolerates_losing_a_concurrent_add(tmp_path, monkeypatch):
    """Admin scripts run init_db over `flyctl ssh console`. If one adds a
    column between our PRAGMA check and our ALTER, the boot must not crash."""
    conn = init_db(tmp_path / "t.db")
    monkeypatch.setattr(db, "_column_exists", lambda *args: False)  # lost the race
    db._add_column_if_missing(
        conn, "users", "session_epoch", "INTEGER NOT NULL DEFAULT 0"
    )
    assert "session_epoch" in _columns(conn, "users")


def test_add_column_if_missing_still_raises_other_errors(tmp_path):
    conn = init_db(tmp_path / "t.db")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        db._add_column_if_missing(conn, "no_such_table", "x", "TEXT")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_db_users_tokens.py`
Expected: these fail:
- `test_tokens_table_has_expected_columns` (the set has no `token_digest`)
- `test_tokens_has_unique_digest_index` (`None != 1`)
- `test_token_digest_allows_many_nulls_but_no_duplicates` (`OperationalError: table tokens has no column named token_digest`)
- `test_init_db_upgrades_a_pre_digest_tokens_table_in_place`
- `test_add_column_if_missing_tolerates_losing_a_concurrent_add` (`OperationalError: duplicate column name: session_epoch`)

`test_add_column_if_missing_still_raises_other_errors` passes already. It guards against the fix swallowing too much.

- [ ] **Step 3: Implement**

In `src/markland/db.py`, replace `_add_column_if_missing` (lines 15-20):

```python
def _add_column_if_missing(
    conn: sqlite3.Connection, table: str, column: str, col_def: str
) -> None:
    if _column_exists(conn, table, column):
        return
    try:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_def}")
    except sqlite3.OperationalError as exc:
        # Admin scripts run init_db over `flyctl ssh console`; one that adds
        # the column between our check and our ALTER is not an error.
        if "duplicate column name" not in str(exc):
            raise
    conn.commit()
```

In `init_db`, directly after these two existing lines:

```python
    conn.execute("CREATE INDEX IF NOT EXISTS idx_token_hash ON tokens(token_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tokens_principal ON tokens(principal_id)")
```

insert:

```python
    # markland-tex (2026-09-27): indexed SHA-256 lookup digest, see
    # service/auth.py:token_digest. Nullable forever: legacy rows, and rows
    # an older release mints during a rollback, get it on their first
    # successful resolve. Uniqueness lives in the index because SQLite
    # rejects ADD COLUMN ... UNIQUE; NULLs are distinct in it.
    _add_column_if_missing(conn, "tokens", "token_digest", "TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_tokens_digest ON tokens(token_digest)"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_db_users_tokens.py tests/test_db.py tests/test_db_schema.py tests/test_invites_migration.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/markland/db.py tests/test_db_users_tokens.py
git commit -m "feat(db): add indexed tokens.token_digest; tolerate concurrent ADD COLUMN (markland-tex)"
```

---

### Task 2: `token_digest()` and mint dual-write (rollback-safe)

**Files:**
- Modify: `src/markland/service/auth.py` — add `token_digest` after `verify_token` (after line 187); `create_user_token` (lines 339-366); `_create_token_for_agent` (lines 369-394)
- Create: `tests/test_auth_token_digest.py`

**Interfaces:**
- Consumes: the `tokens.token_digest` column from Task 1.
- Produces:
  - `token_digest(plaintext: str) -> str`, the 64-char lowercase hex SHA-256 of the UTF-8 plaintext.
  - Every row minted by `create_user_token` and `_create_token_for_agent` has `token_digest = token_digest(plaintext)` **and** an Argon2 `token_hash`.
  - The signatures and `(token_id, plaintext)` return values are unchanged.
  - The test module's helpers `_insert_as_previous_release(...)`, `_digest_of(conn, token_id)`, and the constants `PRE_CUTOFF` / `POST_CUTOFF`, all used by Tasks 3-5.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_auth_token_digest.py`:

```python
"""Indexed digest lookup for bearer tokens (markland-tex).

Every token minted now carries token_digest = SHA-256(plaintext). Rows
written before that get it on their first successful resolve:
- legacy tokens
- new-shape tokens minted before the digest release
- tokens an older release mints during a rollback

Argon2 runs only against rows with no digest.
Spec: docs/specs/2026-09-27-token-digest-lookup-design.md.
"""

from __future__ import annotations

import base64
import hashlib
import re
import runpy
import secrets
import sqlite3
from pathlib import Path

import pytest

from markland.config import reset_config
from markland.db import init_db
from markland.service import auth
from markland.service.agents import create_agent, revoke_agent
from markland.service.auth import (
    _parse_token_plaintext,
    create_agent_token,
    create_user_token,
    hash_token,
    resolve_token,
    token_digest,
    verify_token,
)
from markland.service.users import create_user

PRE_CUTOFF = "2026-01-01T00:00:00+00:00"
POST_CUTOFF = "2026-09-01T00:00:00+00:00"


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


def _insert_as_previous_release(
    conn, *, token_id: str, plaintext: str, principal_type: str,
    principal_id: str, created_at: str,
) -> None:
    """Write a tokens row exactly as the pre-digest release (627601c) does:
    its explicit column list, no token_digest."""
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'prev', ?, ?, ?, NULL, NULL)",
        (token_id, hash_token(plaintext), principal_type, principal_id, created_at),
    )
    conn.commit()


def _digest_of(conn, token_id: str) -> str | None:
    return conn.execute(
        "SELECT token_digest FROM tokens WHERE id = ?", (token_id,)
    ).fetchone()[0]


# --- the digest itself --------------------------------------------------------


def test_token_digest_is_sha256_hex_of_the_exact_plaintext():
    plaintext = "mk_usr_0123456789abcdef_" + secrets.token_urlsafe(32)
    expected = hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
    assert token_digest(plaintext) == expected
    assert re.fullmatch(r"[0-9a-f]{64}", token_digest(plaintext))
    assert token_digest(plaintext) != token_digest(plaintext + " ")


def test_minted_secrets_carry_at_least_256_random_bits():
    """token_digest is a fast hash, sound only for high-entropy secrets.
    If a mint ever shortens its secret, this must fail before the digest
    becomes guessable."""
    for mint in (
        auth._mint_user_token_plaintext_with_id,
        auth._mint_agent_token_plaintext_with_id,
    ):
        _, plaintext = mint()
        secret = _parse_token_plaintext(plaintext).secret_part
        raw = base64.urlsafe_b64decode(secret + "=" * (-len(secret) % 4))
        assert len(raw) >= 32


# --- mint: digest plus Argon2 (rollback safety) ---------------------------------


def _hash_and_digest(conn, token_id: str) -> tuple[str, str | None]:
    return conn.execute(
        "SELECT token_hash, token_digest FROM tokens WHERE id = ?", (token_id,)
    ).fetchone()


def test_user_token_mint_writes_digest_and_argon2_hash(conn):
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="t")
    token_hash, digest = _hash_and_digest(conn, token_id)
    assert digest == token_digest(plaintext)
    # What the pre-digest release's resolver needs after a rollback: an
    # Argon2 hash, and the row id embedded in the plaintext.
    assert token_hash.startswith("$argon2id$")
    assert verify_token(plaintext, token_hash)
    assert _parse_token_plaintext(plaintext).token_id == token_id


def test_agent_token_mint_writes_digest_and_argon2_hash(conn):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )
    token_hash, digest = _hash_and_digest(conn, token_id)
    assert digest == token_digest(plaintext)
    assert token_hash.startswith("$argon2id$")
    assert verify_token(plaintext, token_hash)
    assert _parse_token_plaintext(plaintext).token_id == token_id


def test_previous_release_sql_still_runs_on_the_migrated_schema(conn):
    """After a rollback, the pre-digest release runs these statements
    (auth.py @ 627601c, verbatim) against a DB that has token_digest."""
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    conn.execute(
        """
        INSERT INTO tokens (
            id, token_hash, label, principal_type, principal_id,
            created_at, last_used_at, revoked_at
        ) VALUES (?, ?, ?, 'user', ?, ?, NULL, NULL)
        """,
        ("tok_olduser", hash_token("mk_usr_x"), "l", u.id, POST_CUTOFF),
    )
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, ?, 'agent', ?, ?, NULL, NULL)",
        ("tok_oldagent", hash_token("mk_agt_x"), "l", agent.id, POST_CUTOFF),
    )
    row = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE id = ? AND revoked_at IS NULL
        """,
        ("tok_olduser",),
    ).fetchone()
    assert row is not None
    conn.execute(
        "UPDATE tokens SET last_used_at = ? WHERE id = ?", (POST_CUTOFF, "tok_olduser")
    )
    conn.commit()
    assert _digest_of(conn, "tok_olduser") is None
    assert _digest_of(conn, "tok_oldagent") is None
```

Some imports (`runpy`, `sqlite3`, `Path`, `reset_config`, `resolve_token`, `revoke_agent`) are used by tests appended in Tasks 3-5. CI runs no linter.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_auth_token_digest.py`
Expected: FAIL at collection with `ImportError: cannot import name 'token_digest' from 'markland.service.auth'`.

- [ ] **Step 3: Implement**

In `src/markland/service/auth.py`, directly after `verify_token` (which ends at line 187), add:

```python
def token_digest(plaintext: str) -> str:
    """Indexed lookup digest for a bearer token: SHA-256 hex of the plaintext.

    A fast hash is enough only because every token this module mints has
    256 random bits (``secrets.token_urlsafe(32)``), so no preimage can be
    guessed. Never use it for short or user-chosen secrets (device
    user_codes, passwords): those need a slow KDF. Never log it, and never
    accept it as a credential.
    """
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
```

Replace the body of `create_user_token` from the docstring through `conn.commit()` (lines 345-360) with:

```python
    """Create a new user token. Returns (token_id, plaintext).

    The plaintext is shown to the user ONCE and never persisted — only its
    Argon2 hash and its SHA-256 lookup digest.
    """
    token_id, plaintext = _mint_user_token_plaintext_with_id()
    # Keep the Argon2 hash: the pre-digest release authenticates only
    # through it, so a rollback must still find one (markland-tex).
    hashed = hash_token(plaintext)
    conn.execute(
        """
        INSERT INTO tokens (
            id, token_hash, token_digest, label, principal_type, principal_id,
            created_at, last_used_at, revoked_at
        ) VALUES (?, ?, ?, ?, 'user', ?, ?, NULL, NULL)
        """,
        (token_id, hashed, token_digest(plaintext), label, user_id, _now()),
    )
    conn.commit()
```

In `_create_token_for_agent`, replace this statement (lines 382-387):

```python
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, ?, 'agent', ?, ?, NULL, NULL)",
        (token_id, hash_token(plaintext), (label or "").strip(), agent_id, _now()),
    )
```

with:

```python
    # Argon2 hash kept for rollback safety, as in create_user_token.
    conn.execute(
        "INSERT INTO tokens(id, token_hash, token_digest, label, principal_type, "
        "principal_id, created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, ?, ?, 'agent', ?, ?, NULL, NULL)",
        (
            token_id, hash_token(plaintext), token_digest(plaintext),
            (label or "").strip(), agent_id, _now(),
        ),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_auth_token_digest.py tests/test_service_auth.py tests/test_auth_token_cache.py tests/test_auth_token_cache_revoke_failures.py tests/test_auth_resolve_once_per_request.py tests/test_auth_agent_tokens.py tests/test_device_flow_service.py`
Expected: all pass. The resolver is untouched, so the existing count tests still hold.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/auth.py tests/test_auth_token_digest.py
git commit -m "feat(auth): write a SHA-256 lookup digest at mint, keep the Argon2 hash (markland-tex)"
```

---

### Task 3: Digest lookup, NULL-only Argon2 fallbacks, lazy backfill

**Files:**
- Modify: `src/markland/service/auth.py`:
  - module docstring (lines 1-26)
  - `ParsedToken`, `_parse_token_plaintext` and `_mint_user_token_plaintext_with_id` docstrings (lines 92-145)
  - cache comment (first paragraph, lines 192-196)
  - `resolve_token` docstring (lines 421-452)
  - `_resolve_uncached` (467-479); add `_DIGEST_LOOKUP_SQL` and `_resolve_by_digest` after it
  - `_resolve_by_token_id` (482-514)
  - `_resolve_legacy` (517-540)
  - `_build_principal_and_touch` (543-611)
- Modify: `src/markland/web/_request_bearer.py:5-10` (docstring)
- Modify: `tests/conftest.py` (add the `argon2_verifies` fixture)
- Modify: `tests/test_auth_token_digest.py` (append)
- Modify: `tests/test_service_auth.py`, `tests/test_auth_token_cache.py`, `tests/test_auth_resolve_once_per_request.py` (count assertions that break by design)

Line numbers are as of `main` 627601c. Task 2 shifted `auth.py` by roughly 15 lines, so find blocks by their text.

**Interfaces:**
- Consumes: `token_digest(plaintext) -> str` and the minted digests from Task 2; the column and index from Task 1.
- Produces:
  - `_resolve_by_digest(conn, digest: str) -> Principal | None`, the seam tests patch.
  - `_DIGEST_LOOKUP_SQL: str`.
  - `_NOT_REVOKED_AGENT: str`, an SQL predicate over the tokens table aliased `t`. Tasks 4 and 5 reuse it.
  - `_build_principal_and_touch(conn, token_id, principal_type, principal_id, digest)`: new 5th positional parameter, `digest: str`.
  - `_resolve_by_token_id(conn, parsed, plaintext, digest)` and `_resolve_legacy(conn, plaintext, digest)`.
  - `_resolve_uncached(conn, plaintext)`: signature unchanged.
  - The `argon2_verifies` pytest fixture in `tests/conftest.py`.

- [ ] **Step 1: Add the shared Argon2 counter fixture**

In `tests/conftest.py`, replace the import block:

```python
import pytest

from markland.service.auth import invalidate_token_cache
from tests._mcp_harness import MCPHarness
```

with:

```python
from unittest.mock import patch

import pytest
from argon2 import PasswordHasher

from markland.service.auth import hash_token, invalidate_token_cache, verify_token
from tests._mcp_harness import MCPHarness
```

and add after the `_fresh_token_cache` fixture:

```python
_SPY_CHECK_HASH: str | None = None


@pytest.fixture
def argon2_verifies():
    """Count every Argon2 verify, however the code under test reaches it.

    Patched on the class: argon2's PasswordHasher uses __slots__, so the
    instance (auth._hasher) can't be patched. Before yielding, one verify
    through markland.service.auth must register, so an `== 0` assertion
    can never pass just because the patch missed.
    """
    global _SPY_CHECK_HASH
    if _SPY_CHECK_HASH is None:
        _SPY_CHECK_HASH = hash_token("spy-check")
    with patch.object(
        PasswordHasher, "verify", autospec=True, side_effect=PasswordHasher.verify
    ) as spy:
        assert verify_token("spy-check", _SPY_CHECK_HASH)
        assert spy.call_count == 1, "Argon2 spy is not wired"
        spy.reset_mock()
        yield spy
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_auth_token_digest.py`:

```python
# --- (a) digest path ------------------------------------------------------------


def test_minted_tokens_resolve_by_digest_with_no_argon2(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    _, user_plaintext = create_user_token(conn, user_id=u.id, label="t")
    agent = create_agent(conn, u.id, "scribe")
    _, agent_plaintext = create_agent_token(
        conn, agent_id=agent.id, owner_user_id=u.id, label="t"
    )

    p = resolve_token(conn, user_plaintext)
    assert p is not None and p.principal_id == u.id
    a = resolve_token(conn, agent_plaintext)
    assert a is not None and a.principal_type == "agent" and a.user_id == u.id
    assert argon2_verifies.call_count == 0


def test_digest_lookup_is_served_by_the_unique_index(conn):
    plan = conn.execute(
        "EXPLAIN QUERY PLAN " + auth._DIGEST_LOOKUP_SQL, ("0" * 64,)
    ).fetchall()
    details = [row[3] for row in plan]
    assert any("SEARCH" in d and "idx_tokens_digest" in d for d in details), details


def test_digest_resolve_never_scans_the_tokens_table(conn):
    """The constant being indexed is not enough: the statements a digest-hit
    resolve actually runs must not scan tokens (the trace callback passes
    expanded SQL, so each can be EXPLAINed as-is)."""
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert resolve_token(conn, plaintext) is not None
    finally:
        conn.set_trace_callback(None)
    selects = [
        s for s in statements
        if s.lstrip().upper().startswith("SELECT") and "tokens" in s
    ]
    assert selects
    for s in selects:
        details = [r[3] for r in conn.execute("EXPLAIN QUERY PLAN " + s)]
        assert not any(d.startswith("SCAN") for d in details), (s, details)


def test_revoked_minted_token_costs_no_argon2(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="other")  # live, has a digest
    token_id, plaintext = create_user_token(conn, user_id=u.id, label="t")
    assert auth.revoke_token(conn, token_id=token_id, user_id=u.id)
    assert resolve_token(conn, plaintext) is None
    assert argon2_verifies.call_count == 0


# --- (b)/(c) fallbacks backfill the digest ---------------------------------------


def test_rollback_window_token_resolves_and_backfills(conn, argon2_verifies):
    """A new-shape token minted by the pre-digest release during a rollback
    (post-cutoff, no digest) must keep working after the roll-forward."""
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )

    assert resolve_token(conn, plaintext).principal_id == u.id
    assert argon2_verifies.call_count == 1  # (b): one verify
    assert _digest_of(conn, token_id) == token_digest(plaintext)

    auth.invalidate_token_cache()
    assert resolve_token(conn, plaintext).principal_id == u.id
    assert argon2_verifies.call_count == 1  # now a digest hit


def test_rollback_window_agent_token_resolves_and_backfills(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, plaintext = auth._mint_agent_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="agent", principal_id=agent.id, created_at=POST_CUTOFF,
    )

    p = resolve_token(conn, plaintext)
    assert p is not None and p.principal_id == agent.id
    assert _digest_of(conn, token_id) == token_digest(plaintext)

    auth.invalidate_token_cache()
    assert resolve_token(conn, plaintext) == p
    assert argon2_verifies.call_count == 1


def test_legacy_token_resolves_and_backfills(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    for i in range(3):
        create_user_token(conn, user_id=u.id, label=f"t{i}")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext=legacy,
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )

    assert resolve_token(conn, legacy).principal_id == u.id
    assert argon2_verifies.call_count == 1  # only the digest-less row is verified
    assert _digest_of(conn, "tok_legacy") == token_digest(legacy)

    auth.invalidate_token_cache()
    assert resolve_token(conn, legacy).principal_id == u.id
    assert argon2_verifies.call_count == 1


def test_known_token_id_with_wrong_secret_cannot_plant_a_digest(conn):
    """Knowing a victim's token_id must not let a caller bind their own
    digest to the victim's row: only a successful Argon2 verify of that
    row may write it."""
    u = create_user(conn, email="victim@x", display_name="V")
    token_id, victim = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=victim,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    short_id = token_id.removeprefix("tok_")
    attacker = f"mk_usr_{short_id}_{secrets.token_urlsafe(32)}"

    assert resolve_token(conn, attacker) is None
    assert _digest_of(conn, token_id) is None

    assert resolve_token(conn, victim).principal_id == u.id
    assert _digest_of(conn, token_id) == token_digest(victim)
    auth.invalidate_token_cache()
    assert resolve_token(conn, attacker) is None


def test_revoked_digestless_rows_are_never_verified_or_backfilled(
    conn, argon2_verifies
):
    u = create_user(conn, email="a@x", display_name="A")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext=legacy,
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    token_id, new_shape = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=new_shape,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    conn.execute("UPDATE tokens SET revoked_at = ?", (POST_CUTOFF,))
    conn.commit()

    assert resolve_token(conn, legacy) is None
    assert resolve_token(conn, new_shape) is None
    assert argon2_verifies.call_count == 0
    assert _digest_of(conn, "tok_legacy") is None
    assert _digest_of(conn, token_id) is None


def test_revoked_agents_digestless_tokens_cost_no_argon2(conn, argon2_verifies):
    """revoke_agent leaves the agent's token rows unrevoked, and a row with no
    digest can never be backfilled once its agent is revoked (the touch never
    runs). A forgotten client retrying such a token must not pay Argon2 on
    every request, and an unknown bearer must not pay for these rows either."""
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, plaintext = auth._mint_agent_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="agent", principal_id=agent.id, created_at=POST_CUTOFF,
    )
    legacy = "mk_agt_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy_agent", plaintext=legacy,
        principal_type="agent", principal_id=agent.id, created_at=PRE_CUTOFF,
    )
    revoke_agent(conn, agent.id, owner_user_id=u.id)

    for _ in range(2):
        assert resolve_token(conn, plaintext) is None
        assert resolve_token(conn, legacy) is None
        assert resolve_token(conn, "mk_usr_" + secrets.token_urlsafe(32)) is None
    assert argon2_verifies.call_count == 0


class _FailBackfillOnce(sqlite3.Connection):
    """Makes the next touch/backfill statement fail, as a locked DB or the
    shared-connection race (markland-5nk) can."""

    armed = False

    def execute(self, sql, *args):
        if _FailBackfillOnce.armed and "COALESCE(token_digest" in sql:
            _FailBackfillOnce.armed = False
            raise sqlite3.OperationalError("database is locked")
        return super().execute(sql, *args)


def test_failed_backfill_write_does_not_block_auth_and_is_retried(
    tmp_path, monkeypatch, argon2_verifies
):
    real_connect = sqlite3.connect
    monkeypatch.setattr(
        sqlite3, "connect",
        lambda *a, **kw: real_connect(*a, **{**kw, "factory": _FailBackfillOnce}),
    )
    _FailBackfillOnce.armed = False
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )

    _FailBackfillOnce.armed = True
    assert resolve_token(conn, plaintext).principal_id == u.id  # auth still succeeds
    assert _FailBackfillOnce.armed is False  # the backfill write was attempted
    assert _digest_of(conn, token_id) is None

    auth.invalidate_token_cache()  # stands in for the 60 s TTL expiring
    assert resolve_token(conn, plaintext).principal_id == u.id
    assert _digest_of(conn, token_id) == token_digest(plaintext)
    assert argon2_verifies.call_count == 2  # one verify per uncached resolve until backfilled
    conn.close()


def test_backfill_is_folded_into_the_one_touch_write(conn):
    """The backfill must not add a second write or commit on the shared
    connection (markland-5nk): it rides the existing last_used_at UPDATE."""
    u = create_user(conn, email="a@x", display_name="A")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    statements: list[str] = []
    conn.set_trace_callback(statements.append)
    try:
        assert resolve_token(conn, plaintext) is not None
    finally:
        conn.set_trace_callback(None)
    updates = [s for s in statements if s.lstrip().upper().startswith("UPDATE")]
    assert len(updates) == 1, updates
    assert "last_used_at" in updates[0] and "token_digest" in updates[0]
    assert _digest_of(conn, token_id) == token_digest(plaintext)
```

In `tests/test_service_auth.py`:
- Add `token_digest,` to the `from markland.service.auth import (...)` list, after `revoke_token,`.
- In `test_resolve_token_falls_through_to_legacy_on_pk_miss`, replace the final three lines:

```python
    p = resolve_token(conn, legacy_plaintext)
    assert p is not None
    assert p.principal_id == "usr_dan"
```

with:

```python
    p = resolve_token(conn, legacy_plaintext)
    assert p is not None
    assert p.principal_id == "usr_dan"
    # ...and the row it verified now carries its digest (markland-tex).
    digest = conn.execute(
        "SELECT token_digest FROM tokens WHERE id = ?", (legacy_id,)
    ).fetchone()[0]
    assert digest == token_digest(legacy_plaintext)
```

Also change `~2.3e-12` in that test's docstring to `~3.6e-12 (2^-38)`.

- [ ] **Step 3: Run the new tests to verify they fail**

Run: `uv run pytest tests/test_auth_token_digest.py tests/test_service_auth.py::test_resolve_token_falls_through_to_legacy_on_pk_miss`
Expected failures:
- `test_minted_tokens_resolve_by_digest_with_no_argon2`: count 2, since today's fast path verifies each token.
- `test_digest_lookup_is_served_by_the_unique_index`: `AttributeError: … '_DIGEST_LOOKUP_SQL'`.
- `test_revoked_minted_token_costs_no_argon2`: count 1, because the legacy scan verifies the other live row.
- The two rollback-window tests and the planting test: `_digest_of` is `None`.
- `test_legacy_token_resolves_and_backfills`: `4 != 1`. Today's scan verifies every live row.
- `test_revoked_agents_digestless_tokens_cost_no_argon2`: a nonzero count. Today's fast path and scan both verify the revoked agent's rows.
- `test_failed_backfill_write_does_not_block_auth_and_is_retried`: `assert _FailBackfillOnce.armed is False` fails, because today's touch SQL has no `COALESCE(token_digest`.
- `test_backfill_is_folded_into_the_one_touch_write`: the one UPDATE has no `token_digest`.
- The fall-through test: its digest is `None`.

Two tests pass already and guard the new code:
- `test_revoked_digestless_rows_are_never_verified_or_backfilled`: revoked rows are filtered today.
- `test_digest_resolve_never_scans_the_tokens_table`: today's PK lookup is an index search too.

- [ ] **Step 4: Implement the resolver**

In `src/markland/service/auth.py`, replace `_resolve_uncached`, `_resolve_by_token_id`, `_resolve_legacy` and `_build_principal_and_touch` (from `def _resolve_uncached(` down to the `return None` that closes `_build_principal_and_touch`, just before `def revoke_token(`) with:

```python
def _resolve_uncached(
    conn: sqlite3.Connection, plaintext: str
) -> Principal | None:
    """Digest lookup, then the Argon2 fallbacks. See :func:`resolve_token`."""
    digest = token_digest(plaintext)
    result = _resolve_by_digest(conn, digest)
    if result is not None:
        return result
    parsed = _parse_token_plaintext(plaintext)
    if parsed is not None:
        result = _resolve_by_token_id(conn, parsed, plaintext, digest)
        if result is not None:
            return result
        # (b) missed (no digest-less row at that id, type mismatch, or
        # verify mismatch). Fall through to (c) — see CRITICAL note above.

    return _resolve_legacy(conn, plaintext, digest)


# Tokens of a revoked agent can never authenticate (_build_principal_and_touch
# returns None for them), and revoke_agent leaves the token rows themselves
# unrevoked. Never spend Argon2 on them. Use with the tokens table aliased `t`.
_NOT_REVOKED_AGENT = (
    "NOT EXISTS (SELECT 1 FROM agents a WHERE t.principal_type = 'agent' "
    "AND a.id = t.principal_id AND a.revoked_at IS NOT NULL)"
)

# A constant so a test can EXPLAIN it: it must stay a unique-index search.
_DIGEST_LOOKUP_SQL = (
    "SELECT id, principal_type, principal_id FROM tokens "
    "WHERE token_digest = ? AND revoked_at IS NULL"
)


def _resolve_by_digest(
    conn: sqlite3.Connection, digest: str
) -> Principal | None:
    """(a): one lookup on the unique ``idx_tokens_digest``. No Argon2."""
    row = conn.execute(_DIGEST_LOOKUP_SQL, (digest,)).fetchone()
    if row is None:
        return None
    token_id, principal_type, principal_id = row
    return _build_principal_and_touch(
        conn, token_id, principal_type, principal_id, digest
    )


def _resolve_by_token_id(
    conn: sqlite3.Connection,
    parsed: ParsedToken,
    plaintext: str,
    digest: str,
) -> Principal | None:
    """(b): the embedded token_id's row, only while it has no digest.

    Type cross-check, one Argon2 verify, then backfill. Returns ``None`` on
    PK miss / digest already set / revoked agent / type mismatch / verify
    mismatch / dangling user.

    Caller MUST treat ``None`` as "fall through to legacy", not "auth
    failed." See :func:`resolve_token` for the rationale.
    """
    row = conn.execute(
        f"""
        SELECT t.id, t.token_hash, t.principal_type, t.principal_id
        FROM tokens t
        WHERE t.id = ? AND t.revoked_at IS NULL AND t.token_digest IS NULL
          AND {_NOT_REVOKED_AGENT}
        """,
        (parsed.token_id,),
    ).fetchone()
    if row is None:
        return None
    token_id, token_hash, principal_type, principal_id = row
    # Cross-check type BEFORE running argon2 — saves the expensive verify
    # on a forged-prefix attack against an existing row of the wrong type.
    if principal_type != parsed.principal_type:
        return None
    if not verify_token(plaintext, token_hash):
        return None
    return _build_principal_and_touch(
        conn, token_id, principal_type, principal_id, digest
    )


def _resolve_legacy(
    conn: sqlite3.Connection, plaintext: str, digest: str
) -> Principal | None:
    """(c): Argon2-verify each live row that has no digest yet.

    Legacy tokens (issued before the token-id prefix migration) have no
    embedded token_id, so the only way to find their row is to verify each
    candidate. New-shape tokens that miss (b) also fall through here (see
    :func:`resolve_token`). A row with a digest is never a candidate: a
    set, different digest means a different token.
    """
    rows = conn.execute(
        f"""
        SELECT t.id, t.token_hash, t.principal_type, t.principal_id
        FROM tokens t
        WHERE t.revoked_at IS NULL AND t.token_digest IS NULL
          AND {_NOT_REVOKED_AGENT}
        """
    ).fetchall()
    for token_id, token_hash, principal_type, principal_id in rows:
        if verify_token(plaintext, token_hash):
            return _build_principal_and_touch(
                conn, token_id, principal_type, principal_id, digest
            )
    return None


def _build_principal_and_touch(
    conn: sqlite3.Connection,
    token_id: str,
    principal_type: str,
    principal_id: str,
    digest: str,
) -> Principal | None:
    """Build the Principal, then best-effort touch the token row.

    The touch sets ``last_used_at`` and backfills ``token_digest`` when the
    row has none (``COALESCE`` keeps an existing digest). Callers pass a row
    that just matched, either by a digest hit or by a successful Argon2
    verify of that exact row. Never pass one that matched only by PK or
    type: a caller who knows a token_id could then bind their own digest
    to someone else's row. Failure to write must NOT block auth: the row
    keeps no digest, and the next uncached resolve retries.
    """
    if principal_type == "user":
        user_row = conn.execute(
            "SELECT id, display_name, is_admin FROM users WHERE id = ?",
            (principal_id,),
        ).fetchone()
        if user_row is None:
            return None
        try:
            conn.execute(
                "UPDATE tokens SET last_used_at = ?, "
                "token_digest = COALESCE(token_digest, ?) WHERE id = ?",
                (_now(), digest, token_id),
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
    if principal_type == "agent":
        agent_row = conn.execute(
            "SELECT id, owner_type, owner_id, display_name, revoked_at "
            "FROM agents WHERE id = ?",
            (principal_id,),
        ).fetchone()
        if agent_row is None:
            return None
        (
            agent_id,
            agent_owner_type,
            agent_owner_id,
            agent_display_name,
            agent_revoked_at,
        ) = agent_row
        if agent_revoked_at is not None:
            return None
        try:
            conn.execute(
                "UPDATE tokens SET last_used_at = ?, "
                "token_digest = COALESCE(token_digest, ?) WHERE id = ?",
                (_now(), digest, token_id),
            )
            conn.commit()
        except sqlite3.Error:
            pass
        owner_user_id = (
            agent_owner_id if agent_owner_type == "user" else None
        )
        return Principal(
            principal_id=agent_id,
            principal_type="agent",
            display_name=agent_display_name,
            is_admin=False,
            user_id=owner_user_id,
        )
    return None
```

- [ ] **Step 5: Run the new tests to verify they pass**

Run: `uv run pytest tests/test_auth_token_digest.py tests/test_service_auth.py::test_resolve_token_falls_through_to_legacy_on_pk_miss`
Expected: all pass.

- [ ] **Step 6: Confirm which existing tests break by design**

Run: `uv run pytest tests/test_service_auth.py tests/test_auth_token_cache.py tests/test_auth_resolve_once_per_request.py tests/test_auth_token_cache_revoke_failures.py`
Expected: exactly these 14 fail. Each asserted the old Argon2 cost, or hooked `verify_token`, which the digest path no longer calls.
- `test_service_auth.py::test_resolve_token_argon2_verify_call_count_for_new_shape`
- `test_auth_token_cache.py`:
  - `test_second_resolve_is_a_cache_hit_with_zero_verifies`
  - `test_legacy_token_costs_one_scan_per_ttl_not_per_resolve`
  - `test_failed_resolve_is_not_cached`
  - `test_invalidate_token_cache_forces_fresh_resolution`
  - `test_revoke_racing_an_in_flight_resolve_does_not_repopulate_cache`
  - `test_warm_resolve_from_many_threads_never_touches_argon2`
- `test_auth_resolve_once_per_request.py`:
  - `test_invalid_bearer_on_protected_path_costs_one_scan`
  - `test_valid_bearer_on_protected_path_costs_one_verify`
  - `test_bearer_on_unprotected_path_resolves_once`
  - `test_principal_middleware_without_rate_limit_in_front`
  - `test_transient_error_in_rate_limit_resolve_is_retried_not_memoized`
  - `test_repeat_requests_hit_the_cache`
  - `test_legacy_token_costs_one_scan_per_ttl_across_requests`

If any other test fails, stop and investigate. It is not part of this contract change.

- [ ] **Step 7: Rewrite `tests/test_service_auth.py`'s count test**

Remove the now-unused `from unittest.mock import patch` import. Replace `test_resolve_token_argon2_verify_call_count_for_new_shape` with:

```python
def test_resolve_token_new_shape_makes_no_argon2_verify(tmp_path, argon2_verifies):
    """A minted token resolves through the indexed digest lookup: zero
    Argon2 verifies, however many tokens exist. (Rows with no digest yet
    still pay Argon2 — see tests/test_auth_token_digest.py.)"""
    conn = init_db(tmp_path / "t.db")
    u = create_user(conn, email="carol@x", display_name="Carol")
    plaintexts = [
        create_user_token(conn, user_id=u.id, label=f"t{i}")[1] for i in range(5)
    ]
    p = resolve_token(conn, plaintexts[3])
    assert p is not None
    assert argon2_verifies.call_count == 0
```

Replace the docstring of `test_resolve_token_type_mismatch_returns_none` with:

```python
    """Forge mk_usr_<id>_<secret> for a token_id whose row is type=agent.

    The agent row was minted with a digest, so neither Argon2 fallback
    considers it, and the forged digest matches nothing. Result must be
    None. (The type cross-check itself, on a row with no digest yet, is
    covered in tests/test_auth_token_digest.py.)
    """
```

- [ ] **Step 8: Rewrite `tests/test_auth_token_cache.py`**

Replace the module docstring with:

```python
"""Tests for the in-process cache of successful token resolutions.

Why this exists: on 2026-09-26 a post-deploy reconnect burst paid an
Argon2id scan (~1 CPU-s) on every request until the Fly burst balance ran
out. Resolves now use an indexed digest lookup (markland-tex). A cache hit
still costs no SQL on the shared connection and no last_used_at write, and
a token with no digest yet still pays Argon2 on its first resolve.
"""
```

In the `from markland.service.auth import (...)` block, delete the `verify_token,` line.

Replace the `verify_spy` fixture with:

```python
@pytest.fixture
def uncached_spy():
    """Counts fresh (non-cache) resolutions."""
    with patch(
        "markland.service.auth._resolve_uncached", wraps=auth._resolve_uncached
    ) as spy:
        yield spy
```

Replace `test_second_resolve_is_a_cache_hit_with_zero_verifies` with:

```python
def test_second_resolve_is_a_cache_hit(conn, uncached_spy):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")

    first = resolve_token(conn, plaintext)
    assert first is not None
    assert uncached_spy.call_count == 1

    second = resolve_token(conn, plaintext)
    assert second == first
    assert uncached_spy.call_count == 1  # cache hit: no fresh resolve
```

Replace `test_legacy_token_costs_one_scan_per_ttl_not_per_resolve` with:

```python
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
```

Replace `test_failed_resolve_is_not_cached` with:

```python
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
```

Replace `test_invalidate_token_cache_forces_fresh_resolution` with:

```python
def test_invalidate_token_cache_forces_fresh_resolution(conn, uncached_spy):
    u = create_user(conn, email="a@x", display_name="A")
    _, plaintext = create_user_token(conn, user_id=u.id, label="t")
    resolve_token(conn, plaintext)
    auth.invalidate_token_cache()
    resolve_token(conn, plaintext)
    assert uncached_spy.call_count == 2
```

Replace `test_revoke_racing_an_in_flight_resolve_does_not_repopulate_cache` with:

```python
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
```

Replace `test_warm_resolve_from_many_threads_never_touches_argon2` with:

```python
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
```

- [ ] **Step 9: Rewrite `tests/test_auth_resolve_once_per_request.py`**

In the `from markland.service.auth import (...)` block, delete the `verify_token,` line.

Replace the `verify_spy` fixture with:

```python
@pytest.fixture
def uncached_spy():
    """Counts fresh (non-cache) resolutions."""
    with patch(
        "markland.service.auth._resolve_uncached", wraps=auth._resolve_uncached
    ) as spy:
        yield spy
```

Replace `test_invalid_bearer_on_protected_path_costs_one_scan` with:

```python
def test_invalid_bearer_on_protected_path_costs_one_scan(env, argon2_verifies, scan_spy):
    """Before: RateLimit scanned, found nothing, then PrincipalMiddleware
    scanned again — 2N argon2 verifies per 401. Now only digest-less rows
    are ever verified, and still only once per request."""
    conn, client = env
    for i in range(3):
        create_user_token(conn, user_id="usr_alice", label=f"t{i}")
    _insert_legacy_token(conn, user_id="usr_alice", token_id="tok_legacy")

    r = client.get("/admin/metrics", headers=_bearer("mk_usr_not_a_real_token"))
    assert r.status_code == 401
    assert scan_spy.call_count == 1
    assert argon2_verifies.call_count == 1  # the legacy row, once — not twice
```

Replace `test_valid_bearer_on_protected_path_costs_one_verify` with:

```python
def test_valid_bearer_on_protected_path_resolves_once_without_argon2(
    env, uncached_spy, argon2_verifies
):
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    r = client.get("/admin/metrics", headers=_bearer(token))
    assert r.status_code == 403  # authenticated, not an admin
    assert uncached_spy.call_count == 1
    assert argon2_verifies.call_count == 0
```

Replace `test_bearer_on_unprotected_path_resolves_once` with:

```python
def test_bearer_on_unprotected_path_resolves_once(env, uncached_spy):
    """Only RateLimitMiddleware sees this request's bearer."""
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    assert client.get("/health", headers=_bearer(token)).status_code == 200
    assert uncached_spy.call_count == 1
```

In `test_principal_middleware_without_rate_limit_in_front`, change the signature to `(tmp_path, uncached_spy)`. Replace `assert verify_spy.call_count == 1` with `assert uncached_spy.call_count == 1`. Replace `assert verify_spy.call_count == 2  # one row scanned once` with `assert uncached_spy.call_count == 2  # the bad bearer, resolved once`.

Replace `test_transient_error_in_rate_limit_resolve_is_retried_not_memoized` with:

```python
def test_transient_error_in_rate_limit_resolve_is_retried_not_memoized(env):
    """An exception is not a verdict: PrincipalMiddleware retries instead of
    turning a transient DB error into a 401."""
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    real_lookup = auth._resolve_by_digest
    calls = []

    def flaky_lookup(c, digest):
        calls.append(1)
        if len(calls) == 1:
            raise sqlite3.InterfaceError("simulated")
        return real_lookup(c, digest)

    with patch("markland.service.auth._resolve_by_digest", side_effect=flaky_lookup):
        r = client.get("/admin/metrics", headers=_bearer(token))
    assert r.status_code == 403  # authenticated on the retry
    assert len(calls) == 2
```

Replace `test_repeat_requests_hit_the_cache` with:

```python
def test_repeat_requests_hit_the_cache(env, uncached_spy):
    conn, client = env
    _, token = create_user_token(conn, user_id="usr_alice", label="t")
    for _ in range(5):
        assert client.get("/admin/metrics", headers=_bearer(token)).status_code == 403
    assert uncached_spy.call_count == 1
```

Replace `test_legacy_token_costs_one_scan_per_ttl_across_requests` with:

```python
def test_legacy_token_scans_once_then_resolves_by_digest(
    env, argon2_verifies, scan_spy, clock
):
    conn, client = env
    for i in range(4):
        create_user_token(conn, user_id="usr_alice", label=f"t{i}")
    legacy = _insert_legacy_token(conn, user_id="usr_alice", token_id="tok_legacy")

    for _ in range(5):
        assert client.get("/admin/metrics", headers=_bearer(legacy)).status_code == 403
    assert scan_spy.call_count == 1
    assert argon2_verifies.call_count == 1  # only the digest-less row

    clock.advance(auth.TOKEN_CACHE_TTL_S + 1)
    assert client.get("/admin/metrics", headers=_bearer(legacy)).status_code == 403
    assert scan_spy.call_count == 1  # backfilled: a digest hit, no scan
    assert argon2_verifies.call_count == 1
```

- [ ] **Step 10: Run the auth subset to verify it passes**

Run: `uv run pytest tests/test_auth_token_digest.py tests/test_service_auth.py tests/test_auth_token_cache.py tests/test_auth_token_cache_revoke_failures.py tests/test_auth_resolve_once_per_request.py tests/test_auth_agent_tokens.py tests/test_db_users_tokens.py`
Expected: all pass.

- [ ] **Step 11: Update the docstrings that describe the resolver**

In `src/markland/service/auth.py`, replace the module docstring (lines 1-26) with:

```python
"""Token hashing, principal resolution, and per-user token lifecycle.

Token plaintext format (post-markland-9dm)
------------------------------------------

New tokens embed their row-id as a public, non-secret prefix::

    mk_usr_<token_id_hex>_<random_secret>      # user tokens
    mk_agt_<token_id_hex>_<random_secret>      # agent tokens

Where ``<token_id_hex>`` is the ``tok_<hex>`` row-id with the ``tok_``
prefix dropped (16 hex chars). The DB primary key is the full
``tok_<hex>`` form; the parser re-attaches the prefix.

Legacy tokens (issued before markland-9dm, PR #69) have shape
``mk_usr_<urlsafe32>`` with no embedded token_id.

Lookup (markland-tex)
---------------------

Every row minted now stores ``token_digest`` (SHA-256 of the plaintext,
uniquely indexed), and ``resolve_token`` finds a token with one indexed
lookup and no Argon2. A row written before that has no digest until its
first successful resolve. That resolve falls back to Argon2 (by the
embedded token_id, or for legacy tokens by a scan) and backfills the
digest. The Argon2 ``token_hash`` is still written at mint, so a rollback
to the pre-digest release keeps working. See the ``resolve_token``
docstring.
"""
```

Replace the first paragraph of the "Resolved-token cache" comment:

```python
# Every authenticated request resolves its bearer token, and every resolve
# costs Argon2id verifies (~0.1 CPU-s each): one for a new-shape token, one
# per non-revoked row for a legacy-shape token. On 2026-09-26 a post-deploy
# reconnect burst paid that on every request until the Fly shared-cpu burst
# balance ran out. So successful resolutions are cached in-process:
```

with:

```python
# Every authenticated request resolves its bearer token. On 2026-09-26 a
# post-deploy reconnect burst paid an Argon2id scan (~1 CPU-s) on every
# request until the Fly shared-cpu burst balance ran out. Resolves now use
# an indexed digest lookup (markland-tex), and a row with no digest yet
# pays Argon2 once. Successful resolutions are cached in-process:
```

Replace the `resolve_token` docstring (everything between `def resolve_token(...) -> Principal | None:` and `if not plaintext:`) with:

```python
    """Resolve a Bearer token plaintext to a Principal.

    (a) Digest path: one lookup on ``tokens.token_digest`` (SHA-256 of the
        plaintext, uniquely indexed). No Argon2. Every token minted since
        markland-tex has a digest, and every older one gets it on its first
        successful resolve below.

    Rows with no digest yet (``token_digest IS NULL``) fall back to Argon2,
    and only those rows are ever Argon2-verified: a row whose digest is set
    and differs cannot be this token.

    (b) New-shape fallback: parse the embedded ``token_id``, fetch that row
        if it has no digest, cross-check ``principal_type``, run one Argon2
        verify. Covers new-shape tokens minted before the digest release,
        and any minted by an older release during a rollback.

    (c) Legacy fallback: Argon2-verify each live row that has no digest
        yet. Legacy-shape tokens (no embedded token_id) can only be found
        this way.

    A successful (b) or (c) writes the digest onto the row it verified,
    folded into the ``last_used_at`` touch. It never writes on a PK or type
    match alone: that would let a caller who knows a token_id bind their
    own digest to someone else's row.

    CRITICAL — fall through from (b) to (c) on ANY miss:
        The parser regex matches new-shape tokens AND any legacy plaintext
        whose secret happens to start with 16 lowercase hex chars + ``_``
        (~3.6e-12 per token, 2^-38). Then (b) misses, and we MUST continue
        to (c) — otherwise that legacy token silently stops working. An
        attacker with a leaked legacy plaintext could also engineer the
        shape, so the fall-through closes a grief vector too.

        See ``test_resolve_token_falls_through_to_legacy_on_pk_miss``
        for the regression guard.

    Caching: a successful result is cached for ``TOKEN_CACHE_TTL_S``; a
    repeat within the TTL skips all of the above (no SQL, no Argon2, no
    ``last_used_at`` write). ``None`` is never cached. See the
    "Resolved-token cache" section for invalidation rules.
    """
```

Three more docstrings still describe the old resolver:
- In the `ParsedToken` docstring, replace:

```
    A successful parse does NOT imply the token is valid — the resolver
    must still PK-lookup the row, cross-check ``principal_type``, and
    Argon2-verify the plaintext against the stored hash. See
    ``resolve_token`` for the fall-through-on-miss contract.
```

with:

```
    A successful parse does NOT imply the token is valid — the resolver
    still requires a digest hit, or (for a row with no digest yet) a type
    cross-check and an Argon2 verify. See ``resolve_token`` for the
    fall-through-on-miss contract.
```

- In `_parse_token_plaintext`, replace `None signals "fall back to O(N) scan."` with `None means legacy shape: only the digest lookup or fallback (c) can find it.`
- In `_mint_user_token_plaintext_with_id`, replace `its public prefix, enabling O(1) lookup in ``resolve_token``.` with `its public prefix, which fallback (b) uses for rows with no digest yet.`

In `src/markland/web/_request_bearer.py`, replace these docstring lines:

```
needs the same answer to gate the request. A resolve of an unknown or
legacy-shape token is a full Argon2id scan of the tokens table, so the
outcome is memoized in ``request.state``, which wraps the per-request
``scope["state"]`` dict that every BaseHTTPMiddleware layer shares. The
memo includes an explicit invalid verdict, so a bad token is scanned
once per request instead of twice.
```

with:

```
needs the same answer to gate the request. A resolve is SQL on the shared
connection plus, while any row still lacks its lookup digest, Argon2
verifies (markland-tex). So the outcome is memoized in ``request.state``,
which wraps the per-request ``scope["state"]`` dict that every
BaseHTTPMiddleware layer shares. The memo includes an explicit invalid
verdict, so a bad token is resolved once per request instead of twice.
```

- [ ] **Step 12: Run the full suite**

Run: `uv run pytest tests/`
Expected: the last line reads `1360 passed`: 1338 on main plus 22 new (5 from Task 1, 5 from Task 2, 12 from Task 3).

- [ ] **Step 13: Commit**

```bash
git add src/markland/service/auth.py src/markland/web/_request_bearer.py tests/conftest.py \
  tests/test_auth_token_digest.py tests/test_service_auth.py tests/test_auth_token_cache.py \
  tests/test_auth_resolve_once_per_request.py
git commit -m "feat(auth): resolve tokens by indexed digest; Argon2 only for digest-less rows, with lazy backfill (markland-tex)"
```

---

### Task 4: Bound the legacy scan by `LEGACY_TOKEN_CUTOFF` (failed auth becomes cheap)

**Files:**
- Modify: `src/markland/service/auth.py`:
  - add `LEGACY_TOKEN_CUTOFF` after `_TOKEN_PARSE_RE` (line 87 on main, about line 90 after Task 3; find it by text)
  - `_resolve_legacy` query and docstring
  - the `resolve_token` docstring's (c) paragraph
- Modify: `tests/test_auth_token_digest.py` (append), `tests/test_auth_resolve_once_per_request.py` (append)

**Interfaces:**
- Consumes: `_resolve_legacy(conn, plaintext, digest)` from Task 3; the test helpers from Task 2; `argon2_verifies` from Task 3.
- Consumes also: `_NOT_REVOKED_AGENT` from Task 3.
- Produces: the module constant `LEGACY_TOKEN_CUTOFF: str = "2026-05-10T00:00:00+00:00"`, which Task 5's `token_digest_counts` uses.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_token_digest.py`:

```python
# --- (c) is bounded by LEGACY_TOKEN_CUTOFF: failed auth is cheap ------------------


def test_legacy_cutoff_is_not_before_the_markland_9dm_deploy():
    """Legacy-shape tokens were minted until #69 (488711b) was live. Its
    deploy run ran 15:37:42-15:38:29Z on 2026-05-04, and the old image
    served legacy mints until the machine update completed. The 16:00
    floor adds margin for boot and clock skew. A cutoff earlier than that
    would silently lock out a legacy token; later is safe."""
    assert auth.LEGACY_TOKEN_CUTOFF >= "2026-05-04T16:00:00+00:00"


def test_legacy_token_minted_just_before_the_floor_still_resolves(conn):
    """Pins the cutoff's behavior, not just the constant: the last possible
    legacy token must still be found by (c) and backfilled."""
    u = create_user(conn, email="a@x", display_name="A")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_lastlegacy", plaintext=legacy,
        principal_type="user", principal_id=u.id,
        created_at="2026-05-04T15:59:59.999999+00:00",
    )
    assert resolve_token(conn, legacy).principal_id == u.id
    assert _digest_of(conn, "tok_lastlegacy") == token_digest(legacy)


def _insert_dormant_new_shape(conn, user_id: str) -> str:
    """A new-shape token not presented since the digest release."""
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=user_id, created_at=POST_CUTOFF,
    )
    return token_id


def test_unknown_bearer_verifies_only_pre_cutoff_digestless_rows(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="minted")  # has a digest
    for _ in range(3):
        _insert_dormant_new_shape(conn, u.id)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext="mk_usr_" + secrets.token_urlsafe(32),
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )

    assert resolve_token(conn, "mk_usr_" + secrets.token_urlsafe(32)) is None
    assert argon2_verifies.call_count == 1  # tok_legacy only
    assert _digest_of(conn, "tok_legacy") is None  # a failed verify never writes a digest


def test_failed_auth_costs_no_argon2_once_pre_cutoff_rows_are_backfilled(
    conn, argon2_verifies
):
    u = create_user(conn, email="a@x", display_name="A")
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext=legacy,
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    assert resolve_token(conn, legacy) is not None  # backfills tok_legacy
    _insert_dormant_new_shape(conn, u.id)
    token_id, _ = create_user_token(conn, user_id=u.id, label="t")
    argon2_verifies.reset_mock()

    bogus = [
        "mk_usr_" + secrets.token_urlsafe(32),                   # unknown legacy-shape
        "mk_agt_" + secrets.token_urlsafe(32),
        "mk_usr_deadbeefdeadbeef_" + secrets.token_urlsafe(32),  # unknown token_id
        f"mk_usr_{token_id.removeprefix('tok_')}_wrong",         # known id, wrong secret
    ]
    for plaintext in bogus:
        assert resolve_token(conn, plaintext) is None
    assert argon2_verifies.call_count == 0


def test_type_mismatch_on_a_digestless_row_skips_argon2(conn, argon2_verifies):
    u = create_user(conn, email="a@x", display_name="A")
    agent = create_agent(conn, u.id, "scribe")
    token_id, agent_plaintext = auth._mint_agent_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=agent_plaintext,
        principal_type="agent", principal_id=agent.id, created_at=POST_CUTOFF,
    )
    secret = _parse_token_plaintext(agent_plaintext).secret_part
    forged = f"mk_usr_{token_id.removeprefix('tok_')}_{secret}"

    assert resolve_token(conn, forged) is None
    assert argon2_verifies.call_count == 0  # type check first; (c) skips post-cutoff
    assert _digest_of(conn, token_id) is None
    assert resolve_token(conn, agent_plaintext) is not None  # the real token still works
```

Append to `tests/test_auth_resolve_once_per_request.py`:

```python
# --- failed auth is cheap (markland-ts6) ------------------------------------------


def test_failed_auth_over_http_costs_no_argon2_without_pre_cutoff_rows(
    env, argon2_verifies, uncached_spy
):
    """The bearer resolves before the rate-limit check, so a failed auth
    must be cheap on its own. With no pre-cutoff digest-less rows, a burst
    of bad bearers is all 401s, one resolve each, and zero Argon2 — even
    while a new-shape token is still waiting for its backfill."""
    conn, client = env
    for i in range(3):
        create_user_token(conn, user_id="usr_alice", label=f"t{i}")
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'dormant', 'user', 'usr_alice', "
        "'2026-09-01T00:00:00+00:00', NULL, NULL)",
        (token_id, hash_token(plaintext)),
    )
    conn.commit()

    bad = [
        "mk_usr_" + secrets.token_urlsafe(32),
        "mk_usr_deadbeefdeadbeef_" + secrets.token_urlsafe(32),
    ] * 10
    for token in bad:
        r = client.get("/admin/metrics", headers=_bearer(token))
        assert r.status_code == 401
    assert uncached_spy.call_count == len(bad)
    assert argon2_verifies.call_count == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_auth_token_digest.py tests/test_auth_resolve_once_per_request.py`
Expected failures:
- `test_legacy_cutoff_is_not_before_the_markland_9dm_deploy` (`AttributeError: … 'LEGACY_TOKEN_CUTOFF'`)
- `test_unknown_bearer_verifies_only_pre_cutoff_digestless_rows` (4 != 1)
- `test_failed_auth_costs_no_argon2_once_pre_cutoff_rows_are_backfilled` (4 != 0)
- `test_type_mismatch_on_a_digestless_row_skips_argon2` (1 != 0)
- `test_failed_auth_over_http_costs_no_argon2_without_pre_cutoff_rows` (20 != 0)

`test_legacy_token_minted_just_before_the_floor_still_resolves` passes already. It guards the cutoff query against an early date.

- [ ] **Step 3: Implement**

In `src/markland/service/auth.py`, directly after the line `_TOKEN_PARSE_RE = re.compile(r"^mk_(usr|agt)_([0-9a-f]{16})_(.+)$")`, add:

```python

# Legacy-shape tokens (no embedded token_id) were minted until markland-9dm
# (#69, 488711b) went live: its deploy run ran 15:37:42-15:38:29Z on
# 2026-05-04, and every later deploy descends from it. Fallback (c) scans
# only rows created before this, so an unknown bearer never pays Argon2 for
# new-shape rows. Deliberately days late: a late cutoff only adds new-shape
# rows to the scan, while an early one would lock a legacy token out.
# Compared as a string: created_at is always
# datetime.now(timezone.utc).isoformat().
LEGACY_TOKEN_CUTOFF = "2026-05-10T00:00:00+00:00"
```

Replace `_resolve_legacy`'s docstring and query:

```python
    """(c): Argon2-verify each live row that has no digest yet.

    Legacy tokens (issued before the token-id prefix migration) have no
    embedded token_id, so the only way to find their row is to verify each
    candidate. New-shape tokens that miss (b) also fall through here (see
    :func:`resolve_token`). A row with a digest is never a candidate: a
    set, different digest means a different token.
    """
    rows = conn.execute(
        f"""
        SELECT t.id, t.token_hash, t.principal_type, t.principal_id
        FROM tokens t
        WHERE t.revoked_at IS NULL AND t.token_digest IS NULL
          AND {_NOT_REVOKED_AGENT}
        """
    ).fetchall()
```

with:

```python
    """(c): Argon2-verify each live, digest-less row from before the cutoff.

    Legacy tokens (issued before the token-id prefix migration) have no
    embedded token_id, so the only way to find their row is to verify each
    candidate, and they can only be older than ``LEGACY_TOKEN_CUTOFF``.
    New-shape tokens that miss (b) also fall through here (see
    :func:`resolve_token`). A row with a digest is never a candidate: a
    set, different digest means a different token.
    """
    rows = conn.execute(
        f"""
        SELECT t.id, t.token_hash, t.principal_type, t.principal_id
        FROM tokens t
        WHERE t.revoked_at IS NULL AND t.token_digest IS NULL
          AND t.created_at < ? AND {_NOT_REVOKED_AGENT}
        """,
        (LEGACY_TOKEN_CUTOFF,),
    ).fetchall()
```

In the `resolve_token` docstring, replace:

```
    (c) Legacy fallback: Argon2-verify each live row that has no digest
        yet. Legacy-shape tokens (no embedded token_id) can only be found
        this way.
```

with:

```
    (c) Legacy fallback: Argon2-verify each live, digest-less row created
        before ``LEGACY_TOKEN_CUTOFF``. Legacy-shape tokens (no embedded
        token_id) can only be that old. An unknown bearer pays for these
        rows only, so failed auth costs no Argon2 once they are backfilled
        or revoked.
```

- [ ] **Step 4: Run the tests to verify they pass, including the CRITICAL fall-through under the cutoff**

Run: `uv run pytest tests/test_auth_token_digest.py tests/test_auth_resolve_once_per_request.py tests/test_service_auth.py tests/test_auth_token_cache.py tests/test_auth_token_cache_revoke_failures.py`
Expected: all pass. `test_resolve_token_falls_through_to_legacy_on_pk_miss` must be among the passes. Its row is dated 2026-01-01, before the cutoff.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/auth.py tests/test_auth_token_digest.py tests/test_auth_resolve_once_per_request.py
git commit -m "feat(auth): bound the legacy Argon2 scan to pre-cutoff digest-less rows (markland-tex, markland-ts6)"
```

---

### Task 5: Operator visibility — `token_digest_counts` and `token_digest_status.py`

**Files:**
- Modify: `src/markland/service/auth.py` (add `token_digest_counts` after `list_tokens`, at the end of the file)
- Create: `scripts/admin/token_digest_status.py`
- Modify: `tests/test_auth_token_digest.py` (append)
- Modify: `docs/runbooks/admin-operations.md` (the scripts table in § "Admin scripts"; § "Post-deploy verification")

**Interfaces:**
- Consumes: `LEGACY_TOKEN_CUTOFF` from Task 4; `_NOT_REVOKED_AGENT` from Task 3; the test helpers from Task 2.
- Produces: `token_digest_counts(conn) -> dict[str, int]` with keys `"live"`, `"without_digest"` and `"legacy_scan"`, and the script `scripts/admin/token_digest_status.py`. Task 8 runs the script after deploy.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_auth_token_digest.py`:

```python
# --- operator status ------------------------------------------------------------


def test_token_digest_counts(conn):
    u = create_user(conn, email="a@x", display_name="A")
    create_user_token(conn, user_id=u.id, label="minted")
    _insert_as_previous_release(
        conn, token_id="tok_legacy", plaintext="mk_usr_" + secrets.token_urlsafe(32),
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    token_id, plaintext = auth._mint_user_token_plaintext_with_id()
    _insert_as_previous_release(
        conn, token_id=token_id, plaintext=plaintext,
        principal_type="user", principal_id=u.id, created_at=POST_CUTOFF,
    )
    _insert_as_previous_release(
        conn, token_id="tok_revoked", plaintext="mk_usr_" + secrets.token_urlsafe(32),
        principal_type="user", principal_id=u.id, created_at=PRE_CUTOFF,
    )
    conn.execute(
        "UPDATE tokens SET revoked_at = ? WHERE id = 'tok_revoked'", (POST_CUTOFF,)
    )
    conn.commit()
    agent = create_agent(conn, u.id, "gone")
    _insert_as_previous_release(
        conn, token_id="tok_deadagent", plaintext="mk_agt_" + secrets.token_urlsafe(32),
        principal_type="agent", principal_id=agent.id, created_at=PRE_CUTOFF,
    )
    revoke_agent(conn, agent.id, owner_user_id=u.id)  # its token can never resolve

    assert auth.token_digest_counts(conn) == {
        "live": 3, "without_digest": 2, "legacy_scan": 1,
    }
    assert resolve_token(conn, plaintext) is not None  # backfills the new-shape row
    assert auth.token_digest_counts(conn) == {
        "live": 3, "without_digest": 1, "legacy_scan": 1,
    }


def test_token_digest_counts_on_an_empty_table(conn):
    assert auth.token_digest_counts(conn) == {
        "live": 0, "without_digest": 0, "legacy_scan": 0,
    }


def test_token_digest_status_script_prints_counts_only(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    reset_config()
    try:
        c = init_db(tmp_path / "markland.db")
        u = create_user(c, email="a@x", display_name="A")
        _, plaintext = create_user_token(c, user_id=u.id, label="t")
        c.close()
        capsys.readouterr()  # drop the token_create metric line
        script = Path(__file__).resolve().parents[1] / "scripts/admin/token_digest_status.py"
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(str(script), run_name="__main__")
        assert exit_info.value.code == 0
    finally:
        reset_config()
    out = capsys.readouterr().out
    assert re.search(r"live tokens:\s+1\b", out)
    assert re.search(r"without a digest yet:\s+0\b", out)
    assert re.search(r"scanned by every failed auth:\s+0\b", out)
    assert plaintext not in out
    assert token_digest(plaintext) not in out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_auth_token_digest.py -k "counts or status_script"`
Expected:
- The two counts tests fail with `AttributeError: module 'markland.service.auth' has no attribute 'token_digest_counts'`.
- The script test fails because the script file doesn't exist (`FileNotFoundError`, or runpy's "can't find '__main__' module").

- [ ] **Step 3: Implement**

Append to `src/markland/service/auth.py`:

```python


def token_digest_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """How far the digest backfill has got (scripts/admin/token_digest_status.py).

    - ``live``: non-revoked tokens whose agent, if any, isn't revoked.
    - ``without_digest``: live tokens not backfilled yet. Each still costs
      one Argon2 verify on its next successful resolve.
    - ``legacy_scan``: live, no digest, created before LEGACY_TOKEN_CUTOFF.
      Every failed auth still Argon2-verifies each of these rows; 0 means
      failed auth costs no Argon2 (markland-ts6).
    """
    row = conn.execute(
        f"""
        SELECT
            COUNT(*),
            COALESCE(SUM(t.token_digest IS NULL), 0),
            COALESCE(SUM(t.token_digest IS NULL AND t.created_at < ?), 0)
        FROM tokens t
        WHERE t.revoked_at IS NULL AND {_NOT_REVOKED_AGENT}
        """,
        (LEGACY_TOKEN_CUTOFF,),
    ).fetchone()
    return {"live": row[0], "without_digest": row[1], "legacy_scan": row[2]}
```

Create `scripts/admin/token_digest_status.py`:

```python
"""Report how far the token-digest backfill has got (markland-tex).

A token gets its indexed SHA-256 lookup digest at mint, or on its first
successful resolve after the digest release. Until then, resolving it
costs one Argon2 verify, and every failed auth still Argon2-verifies the
pre-cutoff rows without one. Prints counts only, never token material.

Usage:
    /app/.venv/bin/python scripts/admin/token_digest_status.py

Run via:
    flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/token_digest_status.py"
"""

from __future__ import annotations

from markland.config import get_config
from markland.db import init_db
from markland.service.auth import token_digest_counts


def main() -> int:
    conn = init_db(get_config().db_path)
    counts = token_digest_counts(conn)
    print(f"live tokens:                    {counts['live']}")
    print(f"  without a digest yet:         {counts['without_digest']}")
    print(f"  scanned by every failed auth: {counts['legacy_scan']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

In `docs/runbooks/admin-operations.md`, in the "Available scripts" table, add this row after the `list_admin_tokens.py` row:

```markdown
| `token_digest_status.py` | Count live tokens still without a lookup digest, and how many every failed auth still Argon2-verifies (markland-tex). |
```

In § "Post-deploy verification", replace `` (`mk_usr_<16 hex>_…`, which takes the O(1) path), never a loop.`` with `` (`mk_usr_<16 hex>_…`: at most one Argon2 verify, then a digest lookup), never a loop.``

In the same section, after the paragraph ending "…check the throttle metric a couple of minutes later instead of probing again.", add:

````markdown
After a deploy that touches auth, check the token-digest backfill once,
about 10 minutes after clients have reconnected. It prints counts only, with
no token material. Like every admin script it opens the DB through
`init_db`, which is a no-op on an already-migrated DB:

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/token_digest_status.py"
```

- `without a digest yet` falls as clients reconnect. Each token's first
  resolve after the digest release pays one Argon2 verify and backfills
  the digest.
- `scanned by every failed auth` is how many Argon2 verifies an unknown or
  revoked bearer costs. Once it reads 0, failed auth costs no Argon2.
````

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_auth_token_digest.py`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/auth.py scripts/admin/token_digest_status.py tests/test_auth_token_digest.py docs/runbooks/admin-operations.md
git commit -m "feat(admin): token_digest_status.py reports digest backfill progress (markland-tex)"
```

---

### Task 6: Before/after benchmark (PR evidence, not collected by pytest)

**Files:**
- Create: `tests/bench_resolve_token.py`

**Interfaces:**
- Consumes only APIs that exist on both `main` and the branch: `init_db`, `create_user`, `create_agent`, `create_user_token`, `create_agent_token`, `revoke_token`, `hash_token`, `resolve_token`, `invalidate_token_cache`. The same file therefore produces the "before" and "after" numbers.
- Produces: a table on stdout. Exit 1 if a path that should be Argon2-free made a verify or took more than 5 ms CPU. That is expected on `main`.

- [ ] **Step 1: Write the benchmark**

Create `tests/bench_resolve_token.py`:

```python
"""Before/after CPU cost of resolve_token (markland-tex). Not collected by pytest.

Run on the branch, then against main's code, and paste both outputs into
the PR:

    uv run python -m tests.bench_resolve_token             # branch (worktree)
    (cd /Users/daveyhiles/Developer/markland && \
     uv run --no-sync python .worktrees/token-digest/tests/bench_resolve_token.py)   # main

Measures time.process_time(): CPU seconds, which is what Fly's shared-cpu
quota throttles. Argon2 runs on 4 threads, so wall time under-reports it.
The table is prod-shaped: 9 user + 5 agent tokens minted by the app, 1
legacy-shape token (written as the pre-digest release wrote it,
pre-cutoff), and 1 revoked token.

Exits 1 if a path marked "digest-only" makes an Argon2 verify or takes
more than CPU_BOUND_S of CPU. On main that is expected: every path pays
Argon2 there.
"""

from __future__ import annotations

import contextlib
import io
import secrets
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher

from markland.db import init_db
from markland.service import auth
from markland.service.agents import create_agent
from markland.service.users import create_user

ITERATIONS = 10  # on main each legacy-path resolve costs ~1.5 CPU-s
CPU_BOUND_S = 0.005  # ~20x under one Argon2 verify
LEGACY_ID = "tok_benchlegacy0000"
BURST_BALANCE_S = 50.0  # CPU-s Fly grants after a deploy
BASELINE_SHARE = 0.0625  # shared-cpu-1x baseline once the balance is spent


def _has_digest_column(conn) -> bool:
    return any(r[1] == "token_digest" for r in conn.execute("PRAGMA table_info(tokens)"))


def _setup(db_path: Path):
    conn = init_db(db_path)
    with contextlib.redirect_stdout(io.StringIO()):  # metrics.emit prints JSON lines
        user = create_user(conn, email="bench@x", display_name="Bench")
        minted = [
            auth.create_user_token(conn, user_id=user.id, label=f"u{i}")
            for i in range(9)
        ]
        agent = create_agent(conn, user.id, "bench-agent")
        for i in range(5):
            auth.create_agent_token(
                conn, agent_id=agent.id, owner_user_id=user.id, label=f"a{i}"
            )
        revoked_id, revoked = auth.create_user_token(conn, user_id=user.id, label="rev")
        auth.revoke_token(conn, token_id=revoked_id, user_id=user.id)
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'legacy', 'user', ?, '2026-01-01T00:00:00+00:00', NULL, NULL)",
        (LEGACY_ID, auth.hash_token(legacy), user.id),
    )
    conn.commit()
    return conn, minted, legacy, revoked


def _measure(conn, plaintext: str, before=None) -> tuple[float, int]:
    cpu: list[float] = []
    verifies: list[int] = []
    for _ in range(ITERATIONS):
        if before is not None:
            before()
        auth.invalidate_token_cache()
        with patch.object(
            PasswordHasher, "verify", autospec=True, side_effect=PasswordHasher.verify
        ) as spy:
            t0 = time.process_time()
            auth.resolve_token(conn, plaintext)
            cpu.append(time.process_time() - t0)
        verifies.append(spy.call_count)
    return statistics.median(cpu), max(verifies)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        conn, minted, legacy, revoked = _setup(Path(tmp) / "bench.db")
        has_digest = _has_digest_column(conn)
        (existing_id, _) = minted[0]
        short_id = existing_id.removeprefix("tok_")

        def reset_legacy_digest():
            if has_digest:
                conn.execute("UPDATE tokens SET token_digest = NULL WHERE id = ?", (LEGACY_ID,))
                conn.commit()

        def reset_all_digests():
            if has_digest:
                conn.execute("UPDATE tokens SET token_digest = NULL")
                conn.commit()

        # (label, plaintext, before-hook, digest-only?) — order matters: the
        # steady-state rows run after the legacy row has been backfilled.
        scenarios = [
            ("new-shape valid", minted[3][1], None, True),
            ("legacy, first resolve (pays the scan)", legacy, reset_legacy_digest, False),
            ("legacy, repeat resolve", legacy, None, True),
            ("unknown legacy-shape bearer", "mk_usr_" + secrets.token_urlsafe(32), None, True),
            ("forged: existing id, wrong secret", f"mk_usr_{short_id}_{secrets.token_urlsafe(32)}", None, True),
            ("forged: unknown id", "mk_usr_deadbeefdeadbeef_" + secrets.token_urlsafe(32), None, True),
            ("revoked token", revoked, None, True),
            ("unknown bearer, deploy moment (no digests yet)", "mk_usr_" + secrets.token_urlsafe(32), reset_all_digests, False),
        ]

        print(f"digest column present: {has_digest}; {ITERATIONS} cache-cold resolves each")
        print(f"{'scenario':<50} {'median CPU-s':>12} {'argon2':>6} {'per 50 s bank':>13} {'wall @6.25%':>11}")
        failures = []
        for label, plaintext, before, digest_only in scenarios:
            cpu, verifies = _measure(conn, plaintext, before)
            per_bank = BURST_BALANCE_S / cpu if cpu > 0 else float("inf")
            print(
                f"{label:<50} {cpu:>12.5f} {verifies:>6} {per_bank:>13.0f} "
                f"{cpu / BASELINE_SHARE:>10.3f}s"
            )
            if digest_only and (verifies > 0 or cpu > CPU_BOUND_S):
                failures.append(label)
        conn.close()

    if failures:
        print("\nFAIL (expected on main): not digest-only: " + "; ".join(failures))
        return 1
    print("\nOK: every digest-only path made 0 Argon2 verifies under the CPU bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Confirm pytest does not collect it**

Run: `uv run pytest tests/ --collect-only -q 2>/dev/null | grep -c bench_resolve_token`
Expected: `0`.

- [ ] **Step 3: Run it on the branch**

Run: `uv run python -m tests.bench_resolve_token > /tmp/bench-branch.txt; echo "exit=$?"; cat /tmp/bench-branch.txt`
Expected:
- Exit 0 and the final line `OK: …`.
- Every digest-only row shows `argon2 0` and a median well under 0.005.
- "legacy, first resolve" shows `argon2 1`.
- "deploy moment" shows `argon2 1`: only the pre-cutoff legacy row is scanned.

- [ ] **Step 4: Run it against main's code**

Run: `(cd /Users/daveyhiles/Developer/markland && git branch --show-current && uv run --no-sync python .worktrees/token-digest/tests/bench_resolve_token.py > /tmp/bench-main.txt; echo "exit=$?"; cat /tmp/bench-main.txt)`

`--no-sync` leaves the primary checkout's venv untouched.
Expected:
- The first line prints `main`, and it reports `digest column present: False`.
- The rows show Argon2 on every path: about 0.1 CPU-s for new-shape, and about 1.5 CPU-s for legacy, unknown and forged.
- It exits 1 with `FAIL (expected on main)`.
- The numbers match the baseline in the spec's Problem table to within about 30%.

- [ ] **Step 5: Commit**

```bash
git add tests/bench_resolve_token.py
git commit -m "test(bench): before/after CPU benchmark for resolve_token (markland-tex)"
```

---

### Task 7: Public copy and project docs

**Files:**
- Modify: `src/markland/web/templates/privacy.html:10, 32, 161`
- Modify: `docs/ARCHITECTURE.md:37-41, 149-153`
- Modify: `docs/FOLLOW-UPS.md` (four entries in the 2026-09-26 outage section)

**Interfaces:**
- Consumes: the shipped behavior from Tasks 1-5.
- Produces: accurate public and internal descriptions. No code.

- [ ] **Step 1: Update `privacy.html`**

- Line 10: replace `Last updated: 2026-05-04` with `Last updated: 2026-09-27`. If the PR merges on a later date, use that date instead.
- Line 32: replace `Agent bearer tokens are stored as Argon2 hashes; we never see or retain plaintext tokens after issuance.` with `Agent bearer tokens are stored only as one-way hashes; we never see or retain plaintext tokens after issuance.`
- Line 161: replace `Argon2id-hashed bearer tokens` with `hashed bearer tokens`.

- [ ] **Step 2: Update `docs/ARCHITECTURE.md`**

Replace:

```
  on authorize. Per-user API tokens (`mk_usr_…`) and per-agent tokens (`mk_agt_…`)
  are argon2id-hashed and minted from `/settings/tokens` / `/settings/agents`.
  Token plaintext embeds the row's primary key (`mk_usr_<16hex>_<urlsafe32>`)
  so `resolve_token` does an O(1) PK lookup + single argon2 verify, with a
  legacy O(N) fallback for tokens minted before PR #69. Cookie posture:
```

with:

```
  on authorize. Per-user API tokens (`mk_usr_…`) and per-agent tokens (`mk_agt_…`)
  are minted from `/settings/tokens` / `/settings/agents` and stored as a
  uniquely-indexed SHA-256 lookup digest plus an argon2id hash (kept so a
  rollback still authenticates). `resolve_token` is one indexed digest lookup
  with no argon2. A row written before the digest (markland-tex) falls back
  to argon2 once and has its digest backfilled. The fallback goes by the
  embedded primary key in `mk_usr_<16hex>_<urlsafe32>`, or, for legacy
  pre-PR #69 tokens, by a scan of pre-cutoff rows. Cookie posture:
```

Replace:

```
- `tokens` — argon2id-hashed API tokens for users (`mk_usr_…`) and agents
  (`mk_agt_…`), keyed by `(principal_type, principal_id)`. Plaintext shape
  `mk_<usr|agt>_<16hex>_<urlsafe32>` embeds the row's primary key for O(1)
  resolution; legacy `mk_<usr|agt>_<urlsafe32>` plaintexts (pre-PR #69) still
  authenticate via fallback scan.
```

with:

```
- `tokens` — API tokens for users (`mk_usr_…`) and agents (`mk_agt_…`), keyed
  by `(principal_type, principal_id)`. `token_digest` (SHA-256, unique index
  `idx_tokens_digest`) is the lookup key; `token_hash` (argon2id) is kept for
  rollback and for rows not yet backfilled. Plaintext shape
  `mk_<usr|agt>_<16hex>_<urlsafe32>` embeds the row's primary key; legacy
  `mk_<usr|agt>_<urlsafe32>` plaintexts (pre-PR #69) authenticate via a scan
  of pre-cutoff digest-less rows until their first resolve backfills them.
  `scripts/admin/token_digest_status.py` reports backfill progress.
```

- [ ] **Step 3: Update `docs/FOLLOW-UPS.md`**

Replace the "Make failed auth cheap" entry:

```
- **Make failed auth cheap.** A bearer that doesn't resolve (unknown, revoked,
  or a new-shape token that falls through) still pays the full Argon2 scan,
  ~1 CPU-s. Failures aren't cached, and the bearer resolves before the
  rate-limit check, so a 429 doesn't cap the cost. About 45 failed-auth requests
  in the minute after a deploy would drain the ~50 s balance. The likeliest
  source is a forgotten client retrying a revoked token after the legacy
  rotation below.
```

with:

```
- **Make failed auth cheap.** Mostly done by the digest lookup (markland-tex,
  2026-09-27). A bearer that doesn't resolve now pays Argon2 only for live
  rows that were created before `LEGACY_TOKEN_CUTOFF` and have no digest yet:
  the un-rotated legacy tokens. Once those are backfilled or revoked, it pays
  nothing. `scripts/admin/token_digest_status.py` shows the count as
  "scanned by every failed auth". Close markland-ts6 when it reads 0.
```

Replace the first two lines of the "Argon2 still runs on the event loop on a cache miss" entry:

```
- **Argon2 still runs on the event loop on a cache miss.** Don't move resolves
  to a threadpool until the sqlite redesign lands. With concurrent resolves on
```

with:

```
- **Argon2 still runs on the event loop on a cache miss** of a row with no
  digest yet (its first resolve after markland-tex; then it has one). Don't
  move resolves to a threadpool until the sqlite redesign lands. With
  concurrent resolves on
```

In the same entry, replace these two lines:

```
  user's id, a false `is_admin`) for up to 60 s. The HMAC lookup below removes
  most of this cost anyway.
```

with:

```
  user's id, a false `is_admin`) for up to 60 s. The digest lookup
  (markland-tex) removed most of this cost.
```

In the "Rotate legacy tokens, then remove the legacy O(N) path." entry, replace these two lines:

```
  the proxy). Then delete `_resolve_legacy` and the fall-through. Keep the
  fall-through's regression test until the path is gone.
```

with:

```
  the proxy). Then delete `_resolve_legacy` and the fall-through. Keep the
  fall-through's regression test until the path is gone. The digest lookup
  (markland-tex) already skips Argon2 for backfilled rows. What remains is
  phase 2, in `docs/specs/2026-09-27-token-digest-lookup-design.md` § Phase 2.
  It starts when `token_digest_status.py` shows `without a digest yet: 0`, or
  at a fixed date past the rollback horizon plus R2's 30-day retention:
  - revoke the remaining digest-less rows
  - delete fallbacks (b) and (c)
  - stop writing Argon2 at mint
  - update `privacy.html`
```

Keep the two-space indent on every line, so the sub-bullets nest under this entry instead of becoming new top-level entries.

Replace the "Replace Argon2 with an indexed HMAC/SHA-256 lookup for API tokens" entry (from its `- **Replace Argon2` line through `rotates before adopting.`) with:

```
- **~~Replace Argon2 with an indexed HMAC/SHA-256 lookup for API tokens.~~**
  Shipped 2026-09-27 as a keyless SHA-256 digest (markland-tex). The decision
  and its reasoning are in `docs/specs/2026-09-27-token-digest-lookup-design.md`.
  Still open: invites (`service/invites.py`) run their own Argon2 linear scan
  on unauthenticated routes, and the same design applies (see the beads
  follow-up filed at release).
```

- [ ] **Step 4: Run the page tests**

Run: `uv run pytest tests/test_trust_pages.py tests/test_seo_batch_3.py`
Expected: all pass. These cover the privacy page's "Last updated" line and its word-count floor.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/templates/privacy.html docs/ARCHITECTURE.md docs/FOLLOW-UPS.md
git commit -m "docs: describe the token digest lookup; privacy copy says one-way hashes (markland-tex)"
```

---

### Task 8: Verify, open the PR, release, close out

**Files:**
- No code. Beads state (`.beads/issues.jsonl`) is updated from the primary worktree.

**Interfaces:**
- Consumes: everything above; `/tmp/bench-branch.txt` and `/tmp/bench-main.txt` from Task 6.
- Produces: an open PR with CI green; after the user-approved merge, the deploy verified and beads updated.

- [ ] **Step 1: Full suite**

Run: `uv run pytest tests/`
Expected: the last line reads `1369 passed`, with 0 failed. That is 1338 on main plus 31 new tests: 5 in Task 1, 5 in Task 2, 12 in Task 3, 6 in Task 4 and 3 in Task 5. If the total differs, find out why before continuing.

- [ ] **Step 2: Record the rollback target and size the Argon2 fallback in prod (read-only, before merging)**

These are read-only commands that return counts, dates and release metadata only. Neither restarts anything, so neither touches the burst balance.

```bash
export FLY_API_TOKEN=$(grep -A1 'access_token' ~/.fly/config.yml | head -1 | sed 's/.*access_token: *//')
flyctl releases -a markland --image | head -3
flyctl ssh console -a markland -C "/app/.venv/bin/python -c '
import sqlite3
from markland.config import get_config
c = sqlite3.connect(\"file:\" + str(get_config().db_path) + \"?mode=ro\", uri=True)
q = \"SELECT COUNT(*), SUM(t.created_at < ?), SUM(t.created_at < ? AND t.last_used_at >= ?) FROM tokens t WHERE t.revoked_at IS NULL AND NOT EXISTS (SELECT 1 FROM agents a WHERE t.principal_type = ? AND a.id = t.principal_id AND a.revoked_at IS NOT NULL)\"
print(c.execute(q, (\"2026-05-10T00:00:00+00:00\", \"2026-05-10T00:00:00+00:00\", \"2026-08-28\", \"agent\")).fetchone())
'"
```

Expected from `flyctl releases`: the current release, built from f94320b, the last code deploy. It is code-identical to 627601c. Record its version and image ref as the rollback target.

Expected from the query: a tuple `(live, pre_cutoff, pre_cutoff_used_last_30d)`.
- `pre_cutoff` is |L|, the Argon2 verifies each failed auth costs right after deploy. Expect about 2: the operator's Claude Code token and the bot token.
- If `pre_cutoff` is more than 5, stop and ask the user whether to rotate legacy tokens first (markland-brf).
- Record the tuple for the PR body.
- If the Fly SSH tunnel times out, retry once. If it still fails, note "not measured" in the PR and continue.

- [ ] **Step 3: Push and open the PR**

```bash
git push -u origin feat/token-digest-lookup
gh pr create --base main --head feat/token-digest-lookup \
  --title "feat(auth): indexed SHA-256 digest lookup for bearer tokens (markland-tex)" \
  --body-file /tmp/pr-body.md
```

Write `/tmp/pr-body.md` first, with these sections. Paste the two bench outputs verbatim; they contain no token material.

```markdown
## What

Bearer tokens resolve by one indexed SHA-256 lookup (`tokens.token_digest`, unique index) instead of Argon2. Rows with no digest yet fall back to Argon2 once and are backfilled via the existing `last_used_at` touch. Spec: `docs/specs/2026-09-27-token-digest-lookup-design.md`. Plan: `docs/plans/2026-09-27-token-digest-lookup.md`.

## Why

After a deploy, every uncached resolve paid 0.1–1.6 CPU-s of Argon2 on a 6.25%-baseline VM, and failed auth paid a full scan on every request (2026-09-26 outage; markland-tex, markland-ts6).

## Decision: keyless SHA-256, not HMAC

All token formats carry 256 random bits. See the spec § Decision.

## Benchmark (`tests/bench_resolve_token.py`, CPU-s via process_time)

**main**
<paste /tmp/bench-main.txt>

**branch**
<paste /tmp/bench-branch.txt>

## Prod sizing (read-only, pre-merge)

live / pre-cutoff / pre-cutoff used in the last 30 days: <tuple from Step 2>

## Rollback safety

- The column is nullable, and the old release's INSERT and SELECT statements still run (tested).
- New mints still carry an Argon2 `token_hash` and an embedded `token_id`, so the old fast path authenticates them (tested).
- Tokens minted during a rollback resolve through fallback (b) after the roll-forward (tested).
- **Rollback target:** <vNNN and image ref from Step 2>, built from f94320b (code-identical to 627601c).
  - Roll back only to that image: `flyctl deploy -a markland --image <ref> --strategy immediate`.
  - Never roll back to a pre-#90 release, which lacks the token cache and brings back ~1 CPU-s per legacy request.
  - Roll back only after reconnect traffic subsides (runbook § If prod is slow after a deploy, step 3).

## Deploy

This merge deploys. Merge at a quiet time with MCP clients disconnected and the bot paused (runbook § Deploy hygiene). Post-deploy, in this order:
1. CPU balance and throttle, read from Fly's metrics API. This sends no traffic to the app.
2. One `/health` probe.
3. Reconnect clients, wait about 10 minutes, then run `scripts/admin/token_digest_status.py` once.

## Test plan

- [x] `uv run pytest tests/` — 1369 passed, 0 failed
- [x] bench on main and on the branch (above)
- [ ] post-deploy `token_digest_status.py`: `without a digest yet` falls as clients reconnect
```

Append the PR attribution lines your harness requires to the end of the body.

- [ ] **Step 4: Wait for CI**

Run: `gh pr checks --watch`
Expected: `Test` passes. If it fails, fix it on the branch and push again. Never bypass the check.

- [ ] **Step 5: Merge only with the user's go-ahead, at a quiet time**

Ask the user to confirm. Remind them of the runbook: disconnect MCP clients, pause the bot, check it's quiet. Then:

```bash
gh pr merge --squash --delete-branch
```

- [ ] **Step 6: Post-deploy verification (per the runbook, no probe loops)**

A green "Deploy to Fly" run doesn't mean the balance held: the observe step only warns. Check the CPU budget first, from Fly's metrics store, before sending the app anything:

```bash
gh run list --branch main --limit 3          # wait for "Deploy to Fly" on the merge commit to finish
gh run view <deploy-run-id> --log | grep -iE 'balance|throttle|warn'
for q in 'fly_instance_cpu_balance{app="markland"}' 'rate(fly_instance_cpu_throttle{app="markland"}[1m])'; do
  curl -sS -G https://api.fly.io/prometheus/personal/api/v1/query \
    -H "Authorization: FlyV1 $(flyctl auth token 2>/dev/null | tail -1)" \
    --data-urlencode "query=$q"; echo
done
```

If the throttle reads above about 50, or the balance is sliding toward 0, stop. Send no probe and don't SSH in; follow the runbook § "If prod is slow after a deploy".

If it looks healthy, send one probe:

```bash
curl -sS --max-time 90 -o /dev/null -w '%{http_code} %{time_total}s\n' https://markland.dev/health
```

Expected: `200`.

Then reconnect your MCP clients and unpause the bot. Wait about 10 minutes, then run once:

```bash
flyctl ssh console -a markland -C "/app/.venv/bin/python scripts/admin/token_digest_status.py"
flyctl ssh console -a markland -C "/app/.venv/bin/python -c '
import sqlite3
from datetime import datetime, timedelta, timezone
from markland.config import get_config
c = sqlite3.connect(\"file:\" + str(get_config().db_path) + \"?mode=ro\", uri=True)
since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
for r in c.execute(\"SELECT id, created_at, last_used_at FROM tokens WHERE revoked_at IS NULL AND token_digest IS NULL AND last_used_at >= ? ORDER BY last_used_at DESC\", (since,)):
    print(r)
'"
```

Expected:
- `live tokens` equals Step 2's `live`.
- `without a digest yet` has dropped well below it.
- `scanned by every failed auth` is at or below Step 2's `pre_cutoff`, ideally 0.

The second command lists token ids that were active in the last 24 hours but still have no digest. It prints ids and timestamps only, which are not secret. A token owned by a client that has since reconnected (your Claude Code, the bot) should not appear. If one does, it is either locked out or failing its backfill: investigate before closing out.

- [ ] **Step 7: Beads and docs close-out (from the primary worktree, on `main`)**

```bash
cd /Users/daveyhiles/Developer/markland
git branch --show-current   # must print: main
git pull --ff-only
bd close markland-tex --reason="Shipped in PR #<n>: indexed SHA-256 digest lookup, lazy backfill, cutoff-bounded legacy scan"
bd update markland-ts6 --notes="Mostly closed by markland-tex (#<n>): failed auth costs Argon2 only for live pre-cutoff digest-less rows. Close when scripts/admin/token_digest_status.py shows 'scanned by every failed auth: 0' (post-deploy reading: <value>)."
bd update markland-brf --notes="Phase 2 of markland-tex: gate is token_digest_status.py 'without a digest yet: 0' (or fixed date past rollback horizon + 30-day R2 retention). Steps: docs/specs/2026-09-27-token-digest-lookup-design.md § Phase 2."
bd create --title="Invites: indexed digest lookup instead of the Argon2 linear scan" --type=task --priority=3 \
  --description="service/invites.py resolve_invite Argon2-scans every live invite on unauthenticated routes (/invite/<token>, POST /api/invites/<token>/accept). mk_inv_ tokens are 256-bit, so the markland-tex design applies: invites.token_digest + unique index, digest at create, lazy backfill. See docs/specs/2026-09-27-token-digest-lookup-design.md."
bd create --title="Sentry: resolver frame locals carry bearer plaintext/digest" --type=bug --priority=2 \
  --description="PrincipalMiddleware (web/principal_middleware.py) does not catch resolve exceptions, and sentry-sdk's include_local_variables defaults to True, so an exception in resolve_token sends frame locals. EventScrubber only scrubs denylisted names ('token' is listed; 'plaintext', 'header', 'digest' are not), so the bearer plaintext in service/auth.py and web/_request_bearer.py reaches Sentry. Predates markland-tex. Fix: sentry_sdk.init(include_local_variables=False), or scrub frame vars named plaintext/header/digest in log_scrubbing.scrub_sentry_event."
bd sync
git push
```

Replace `<n>` with the PR number, and `<value>` with Step 6's reading. If the ts6 count already reads 0, close it instead: `bd close markland-ts6 --reason="…"`.

Leave the worktree in place. Removing it is the human's call (CLAUDE.md § Multi-agent dispatch).

---

## Self-review notes (plan author)

- **Spec coverage.** Each spec section maps to a task:
  - schema → 1
  - digest and mint dual-write → 2
  - resolve order (a)/(b), backfill, anti-planting, cache unchanged → 3
  - `LEGACY_TOKEN_CUTOFF` and failed-auth cost → 4
  - operator visibility → 5
  - cost-model evidence → 6
  - public copy, docs, phase-2 handoff → 7
  - rollback-safety evidence, release, beads → 2 and 8
- **Out of scope, per the spec.** The invites follow-up is filed in Task 8. Cache removal, the threadpool move and widening the `except` guard stay out.
- **Name consistency.** These names are the same in every task that uses them:
  - `token_digest`, `_resolve_by_digest(conn, digest)`, `_DIGEST_LOOKUP_SQL`, `_NOT_REVOKED_AGENT`
  - `_build_principal_and_touch(conn, token_id, principal_type, principal_id, digest)`
  - `_resolve_by_token_id(conn, parsed, plaintext, digest)`, `_resolve_legacy(conn, plaintext, digest)`
  - `LEGACY_TOKEN_CUTOFF`, `token_digest_counts` → `{"live", "without_digest", "legacy_scan"}`
  - `argon2_verifies`, `uncached_spy`, `_insert_as_previous_release`, `_digest_of`, `PRE_CUTOFF`, `POST_CUTOFF`
