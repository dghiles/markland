# Token-ID Prefix for O(1) Bearer Lookup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Bead:** `markland-9dm` (P2; deferred from PR #64 P1+P2 batch).

**Goal:** Eliminate the O(N) Argon2 verify scan in `resolve_token`.
Today, every Bearer-authenticated request iterates *all* non-revoked
tokens running an Argon2id verify per row until a match is found.
Distributed attackers submitting random Bearer tokens can stall worker
threads; legitimate auth gets slower as the user/agent base grows.

**Architecture:** Embed the token's row-id (a public, non-secret
prefix) into the plaintext token. The new shape is `mk_usr_<tokid>_<secret>`
(and `mk_agt_<tokid>_<secret>`). On `resolve_token` we parse the prefix,
fetch exactly one row by primary key, and run a single Argon2 verify.

**Tech stack:** Python `secrets`, Argon2id (existing), SQLite (existing).
No schema change required — `tokens.id` is already the primary key.

---

## Pre-work — read these first

- `src/markland/service/auth.py` —
  - `_generate_token_id()` returns `tok_<hex8>`.
  - `_generate_user_token_plaintext()` returns `mk_usr_<urlsafe32>`.
  - `_generate_agent_token_plaintext()` returns `mk_agt_<urlsafe32>`.
  - `create_user_token` and `_create_token_for_agent` mint plaintext
    independently of token_id. We will couple them.
  - `resolve_token` does the O(N) scan.
- `src/markland/db.py` — `tokens` table:
  ```sql
  CREATE TABLE IF NOT EXISTS tokens (
      id TEXT PRIMARY KEY,            -- 'tok_<hex8>'
      token_hash TEXT NOT NULL,        -- argon2id of plaintext
      label TEXT,
      principal_type TEXT NOT NULL,    -- 'user' or 'agent'
      principal_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      last_used_at TEXT,
      revoked_at TEXT
  )
  ```
- Token plaintext today is shown to the user once (via
  `agent_token_flash` cookie on the agents path; via the JSON API
  response on the user-token path) and stored only as Argon2 hash.

**Critical migration concern:** existing tokens issued before this PR
have plaintext shape `mk_usr_<urlsafe32>` (no embedded token_id).
`resolve_token` MUST keep working for them during a transition. The
plan handles this with a fallback: if the new-shape parse fails,
fall back to the legacy O(N) scan. Old tokens remain valid until
revoked or rotated; the scan is bounded by the count of legacy
tokens, which only ever decreases.

---

## Task 1 — New token plaintext shape

**Files:**
- Modify: `src/markland/service/auth.py`
- Test: `tests/test_service_auth.py`

The new plaintext format:

```
mk_usr_<token_id_short>_<secret>
mk_agt_<token_id_short>_<secret>
```

Where `<token_id_short>` is the existing `tok_<hex8>` value's hex
portion (just `<hex8>`, 16 characters). The `tok_` prefix is dropped
from the embedded form to keep total length manageable; the table
lookup adds `tok_` back.

Example:
- token_id (PK in DB): `tok_a7c3f9d2b8e6014f`
- plaintext shown to user: `mk_usr_a7c3f9d2b8e6014f_<urlsafe32>`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_service_auth.py
def test_new_user_token_plaintext_embeds_token_id():
    token_id = "tok_a7c3f9d2b8e6014f"
    plaintext = _format_user_token_plaintext(token_id, "secret_part")
    assert plaintext.startswith("mk_usr_a7c3f9d2b8e6014f_")
    assert plaintext.endswith("secret_part")

def test_parse_token_plaintext_extracts_token_id():
    plaintext = "mk_usr_a7c3f9d2b8e6014f_xyz123"
    parsed = _parse_token_plaintext(plaintext)
    assert parsed.principal_type == "user"
    assert parsed.token_id == "tok_a7c3f9d2b8e6014f"

def test_parse_legacy_token_returns_none():
    plaintext = "mk_usr_aGVsbG93b3JsZA"  # legacy: no embedded token_id
    parsed = _parse_token_plaintext(plaintext)
    assert parsed is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_service_auth.py -v -k "embeds_token_id or extracts_token_id or legacy"`
Expected: FAIL on missing helpers.

- [ ] **Step 3: Add the helpers**

In `service/auth.py`:

```python
import re
from dataclasses import dataclass

_TOKEN_ID_HEX_LEN = 16  # secrets.token_hex(8) = 16 hex chars
_TOKEN_PARSE_RE = re.compile(
    r"^mk_(usr|agt)_([0-9a-f]{16})_(.+)$"
)

@dataclass(frozen=True)
class ParsedToken:
    principal_type: Literal["user", "agent"]
    token_id: str  # full 'tok_<hex>' form
    secret_part: str

def _format_user_token_plaintext(token_id: str, secret_part: str) -> str:
    """Combine token_id + secret_part into the user-facing plaintext."""
    short = token_id.removeprefix("tok_")
    return f"mk_usr_{short}_{secret_part}"

def _format_agent_token_plaintext(token_id: str, secret_part: str) -> str:
    short = token_id.removeprefix("tok_")
    return f"mk_agt_{short}_{secret_part}"

def _parse_token_plaintext(plaintext: str) -> ParsedToken | None:
    """Return ParsedToken if plaintext is the new shape; None for legacy.

    None signals "fall back to O(N) scan."
    """
    if not plaintext:
        return None
    m = _TOKEN_PARSE_RE.match(plaintext)
    if not m:
        return None
    type_short, hex_part, secret_part = m.groups()
    return ParsedToken(
        principal_type="user" if type_short == "usr" else "agent",
        token_id=f"tok_{hex_part}",
        secret_part=secret_part,
    )

def _generate_user_token_plaintext() -> str:
    """Mint a fresh user token. Returns (token_id, plaintext)."""
    raise NotImplementedError("Use _mint_user_token_plaintext_with_id instead.")

def _mint_user_token_plaintext_with_id() -> tuple[str, str]:
    token_id = _generate_token_id()
    secret_part = secrets.token_urlsafe(32)
    plaintext = _format_user_token_plaintext(token_id, secret_part)
    return token_id, plaintext

def _mint_agent_token_plaintext_with_id() -> tuple[str, str]:
    token_id = _generate_token_id()
    secret_part = secrets.token_urlsafe(32)
    plaintext = _format_agent_token_plaintext(token_id, secret_part)
    return token_id, plaintext
```

(The old single-arg `_generate_user_token_plaintext` is replaced by
the two-tuple-returning mint helper. Update its callers in step 4.)

- [ ] **Step 4: Update `create_user_token` and `_create_token_for_agent`**

```diff
 def create_user_token(conn, *, user_id, label):
-    plaintext = _generate_user_token_plaintext()
-    token_id = _generate_token_id()
+    token_id, plaintext = _mint_user_token_plaintext_with_id()
     hashed = hash_token(plaintext)
     ...
```

Same shape for `_create_token_for_agent`.

- [ ] **Step 5: Run targeted tests**

Run: `.venv/bin/pytest tests/test_service_auth.py -v -k "embeds_token_id or extracts_token_id or legacy or create_user_token or _create_token_for_agent"`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/auth.py tests/test_service_auth.py
git commit -m "feat(auth): embed token_id in plaintext for O(1) lookup (markland-9dm)"
```

---

## Task 2 — Fast path in `resolve_token` with legacy fallback

**Files:**
- Modify: `src/markland/service/auth.py`
- Test: `tests/test_service_auth.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_resolve_token_uses_id_prefix_for_new_shape(tmp_path):
    """New-shape tokens hit the table by PK and run argon2 verify exactly once."""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    insert_user(conn, "usr_alice")
    _, plaintext = _mint_user_token_plaintext_with_id()
    # ... seed the row using the same token_id as plaintext encodes ...
    # use create_user_token(conn, user_id="usr_alice", label="x") so it's wired correctly
    p = resolve_token(conn, plaintext)
    assert p.principal_id == "usr_alice"

def test_resolve_token_returns_none_when_id_prefix_does_not_exist(tmp_path):
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    # Forge a plaintext whose token_id is not in the DB.
    forged = "mk_usr_deadbeefdeadbeef_xxxxxxxxxxxxxxxx"
    assert resolve_token(conn, forged) is None

def test_resolve_token_legacy_format_still_works(tmp_path):
    """Tokens minted before this PR (no embedded token_id) still work."""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    insert_user(conn, "usr_bob")
    legacy_plaintext = "mk_usr_" + secrets.token_urlsafe(32)
    legacy_id = "tok_legacy00000000"
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, created_at) "
        "VALUES (?, ?, 'legacy', 'user', 'usr_bob', '2026-01-01T00:00:00+00:00')",
        (legacy_id, hash_token(legacy_plaintext)),
    )
    conn.commit()
    p = resolve_token(conn, legacy_plaintext)
    assert p.principal_id == "usr_bob"

def test_resolve_token_argon2_verify_call_count_for_new_shape(tmp_path, mocker):
    """Confirms O(1): exactly ONE argon2 verify call regardless of #tokens."""
    conn = sqlite3.connect(":memory:")
    init_db(conn)
    insert_user(conn, "usr_carol")
    # Mint 50 tokens for usr_carol.
    plaintexts = []
    for i in range(50):
        _tok_id, plaintext = create_user_token(conn, user_id="usr_carol", label=f"t{i}")
        plaintexts.append(plaintext)
    # Spy on verify.
    spy = mocker.spy(markland.service.auth, "verify_token")
    resolve_token(conn, plaintexts[42])
    assert spy.call_count == 1
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/pytest tests/test_service_auth.py -v -k "id_prefix or argon2_verify_call_count"`
Expected: FAIL — `resolve_token` still does O(N) scan.

- [ ] **Step 3: Implement the fast path**

```python
def resolve_token(conn: sqlite3.Connection, plaintext: str) -> Principal | None:
    """Resolve a Bearer token plaintext to a Principal.

    Fast path (new-shape tokens): parse the token_id prefix, fetch exactly
    one row by PK, run one Argon2 verify.

    Legacy path (old-shape tokens, no embedded token_id): scan all
    non-revoked rows. This bounds at the count of pre-migration tokens,
    which only decreases over time.
    """
    if not plaintext:
        return None

    parsed = _parse_token_plaintext(plaintext)
    if parsed is not None:
        return _resolve_by_token_id(conn, parsed, plaintext)

    return _resolve_legacy(conn, plaintext)


def _resolve_by_token_id(
    conn: sqlite3.Connection, parsed: ParsedToken, plaintext: str
) -> Principal | None:
    row = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE id = ? AND revoked_at IS NULL
        """,
        (parsed.token_id,),
    ).fetchone()
    if row is None:
        return None
    token_id, token_hash, principal_type, principal_id = row
    if not verify_token(plaintext, token_hash):
        return None
    if principal_type != parsed.principal_type:
        # type mismatch between embedded prefix and DB row — corrupted; reject.
        return None
    return _build_principal_and_touch(
        conn, token_id, principal_type, principal_id
    )


def _resolve_legacy(conn: sqlite3.Connection, plaintext: str) -> Principal | None:
    """The pre-markland-9dm O(N) path. Kept for legacy plaintexts only."""
    rows = conn.execute(
        """
        SELECT id, token_hash, principal_type, principal_id
        FROM tokens
        WHERE revoked_at IS NULL
        """
    ).fetchall()
    for token_id, token_hash, principal_type, principal_id in rows:
        if verify_token(plaintext, token_hash):
            return _build_principal_and_touch(
                conn, token_id, principal_type, principal_id
            )
    return None


def _build_principal_and_touch(
    conn: sqlite3.Connection,
    token_id: str,
    principal_type: str,
    principal_id: str,
) -> Principal | None:
    """Build the Principal object and best-effort update last_used_at.

    Refactored out of the existing resolve_token body unchanged.
    """
    # ... move the existing user/agent branch (UPDATE last_used_at + return Principal)
    # from the current resolve_token() into this helper. No behaviour change.
```

- [ ] **Step 4: Run tests to verify passing**

Run: `.venv/bin/pytest tests/test_service_auth.py -v -k "resolve_token or id_prefix or legacy or argon2_verify"`
Expected: PASS, including the call-count test asserting exactly one
verify on a 50-token user.

- [ ] **Step 5: Run full suite**

Run: `.venv/bin/pytest -q --tb=short`
Expected: full pass.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/auth.py tests/test_service_auth.py
git commit -m "feat(auth): O(1) resolve_token via embedded token_id prefix (markland-9dm)"
```

---

## Task 3 — Confirm no other callers depend on the old plaintext format

**Files:**
- Search: `grep -rn "mk_usr_\|mk_agt_" src/ tests/ scripts/`
- Modify any caller that splits/parses the plaintext outside of
  `service/auth.py`.

The plaintext format is mostly opaque to callers — it's shown to the
user once and validated on Bearer-auth requests via `resolve_token`.
Some places (admin scripts, tests) might string-split plaintexts.

- [ ] **Step 1: Run the grep.**

```bash
grep -rn "mk_usr_\|mk_agt_" src/ tests/ scripts/
```

For each hit:
- If it's in `service/auth.py` — already updated.
- If it's in `tests/` — likely a test fixture; verify the new format
  works or update the fixture.
- If it's in `scripts/` (e.g. provisioning helpers) — probably builds
  a plaintext; route it through the new `_mint_user_token_plaintext_with_id`.
- If it's in user-facing strings (templates, docstrings) — update the
  format example.

- [ ] **Step 2: Update each as needed; commit per logical chunk.**

---

## Task 4 — Document the migration

**Files:**
- Modify: docstring of `resolve_token` and the module-level docstring.
- Add: a note in `docs/runbooks/` or `docs/ARCHITECTURE.md` describing
  the legacy-fallback behaviour and when it can be removed.

The legacy fallback can be removed once we're confident no
pre-migration tokens remain. Rough criteria: 90 days post-deploy AND
admin queries `SELECT COUNT(*) FROM tokens WHERE revoked_at IS NULL
AND created_at < '<deploy-date>'` returns < some small threshold (e.g.
< 5).

- [ ] **Step 1: Add the note.**

- [ ] **Step 2: Commit.**

```bash
git add src/markland/service/auth.py docs/
git commit -m "docs(auth): document token-id prefix and legacy fallback (markland-9dm)"
```

---

## Self-review checklist

- [ ] New tokens are minted with the embedded `tok_<hex>` prefix (verify with a one-shot `python -c "from markland.service.auth import _mint_user_token_plaintext_with_id; print(_mint_user_token_plaintext_with_id())"`).
- [ ] New tokens authenticate via the fast path (single argon2 verify; spy test confirms).
- [ ] Legacy tokens still authenticate (legacy-fallback test passes).
- [ ] No regressions in any existing token-using test (full suite green).
- [ ] No SQL string interpolation; only `?` placeholders.
- [ ] No tokens or plaintexts logged anywhere.
- [ ] Token plaintext length is reasonable (< 80 chars). Verify: `mk_usr_` (7) + 16 hex + `_` (1) + ~43 urlsafe = ~67 chars.
- [ ] No collision risk: `secrets.token_hex(8)` = 64 bits → ~1-in-4-billion collision over a million tokens. Acceptable; document the bound.

---

## PR checklist

```bash
git push -u origin feat/token-id-prefix-lookup
gh pr create --base main --title "feat(auth): O(1) Bearer token resolve via embedded token_id (markland-9dm)" --body "$(cat <<'EOF'
## Summary
Eliminate the O(N) Argon2 verify scan in `resolve_token`. New tokens
embed their row-id as a public, non-secret prefix; lookup goes by PK.
Legacy tokens (issued before this PR) continue to work via fallback.

Closes markland-9dm (P2; deferred from PR #64 batch).

## New plaintext format
`mk_usr_<token_id_hex>_<random_secret>` (and `mk_agt_…`).
Existing tokens are unchanged and authenticate via the legacy O(N)
fallback path.

## Performance
Verified with a 50-token user: exactly 1 argon2 verify per resolve
(was 50). DoS lever from PR #64 review removed.

## Test plan
- [x] Unit tests on parser + minter
- [x] Resolve-by-id tests (happy path, missing-id 404, type-mismatch reject)
- [x] Legacy fallback test (pre-PR plaintext shape still works)
- [x] argon2-verify call-count test (asserts O(1))
- [x] Full suite green

## Migration
- Fresh deploys: all new tokens use the new shape.
- Existing deploys: legacy tokens remain valid; new mintings use the
  new shape. Fallback path can be removed in ~90 days when legacy
  count drops near zero.
EOF
)"
```

Stop after PR is opened. Do NOT merge.
