# Token digest lookup: design

**Date:** 2026-09-27
**Beads:** markland-tex (this change), markland-ts6 (make failed auth cheap:
mostly closed by this), markland-brf (legacy removal: phase 2, prepared here)
**Plan:** `docs/plans/2026-09-27-token-digest-lookup.md`
**Background:** `docs/incidents/2026-09-26-v236-outage.md`, `docs/FOLLOW-UPS.md`
§ "Make failed auth cheap" and § "Replace Argon2 with an indexed HMAC/SHA-256
lookup"

## Problem

Every uncached bearer resolve pays Argon2id (t=3, 64 MiB, p=4, about 0.1 CPU-s
per verify):

| Path (15 live rows, measured on main, `time.process_time`) | CPU-s |
|---|---|
| New-shape token (PK lookup + 1 verify) | 0.106 |
| Legacy-shape token (scan until match) | 1.57 |
| Unknown legacy-shape bearer (scan every row) | 1.56 |
| Forged new-shape bearer (PK miss, then full scan) | 1.61 |

Prod is one `shared-cpu-1x` VM. It gets a 6.25% baseline, and every deploy
resets its burst balance to about 50 CPU-s. The #88/#89/#92 cache limits a
*successful* resolve to one per token per 60 s. Two costs remain:

1. **Failed auth is expensive and uncapped.** Failures aren't cached, and the
   bearer resolves before the rate-limit check. An unknown or revoked bearer
   pays the full scan on every request. About 45 of them drain the
   post-deploy balance.
2. **Cold misses run Argon2 on the event loop.** After a deploy every client
   reconnects, and each token's first resolve pays Argon2 synchronously on
   the loop thread. That thread also serves `/health`. A post-boot health
   check took 4.8 s.

Bearer tokens are 256-bit random secrets, not passwords. A slow KDF adds
nothing against guessing at that entropy.

## Goals

- A token's resolve costs no Argon2 once its row has a digest. Every token
  minted after this change has one. Every older token gets one on its first
  successful resolve.
- An unknown, revoked or forged bearer costs no Argon2 once the small set of
  pre-cutoff rows is backfilled or revoked. Until then it costs one verify per
  such row, not one per live row.
- A rollback to the current prod image (built from f94320b, code-identical to
  627601c) stays safe in both directions.
- No new secret, dependency, or config.

## Non-goals

- Invites (`mk_inv_…`, `service/invites.py`). They run their own Argon2
  linear scan on unauthenticated routes. The same design applies, filed as a
  follow-up.
- Removing the resolved-token cache or shortening its TTL. The cache still
  keeps SQL off the shared connection (markland-5nk). Revisit after the sqlite
  redesign.
- Moving resolves to a threadpool (forbidden until markland-5nk lands).
- Widening the touch write's `except sqlite3.Error` guard. Draft PR #94
  documents a `SystemError` from the shared-connection race that this guard
  misses. That exposure predates this change and belongs to markland-5nk.
- Phase 2 (markland-brf): stop writing Argon2 at mint, delete fallbacks
  (b) and (c). That needs the rollback window closed and the backfill
  complete; see § Phase 2.

## Decision: keyless SHA-256, not HMAC

`FOLLOW-UPS.md` proposed `HMAC-SHA256(server_key, plaintext)`. This design uses
plain SHA-256 of the exact UTF-8 plaintext, stored as lowercase hex.

- **Why keyless is enough.** Every token format (legacy, new-shape, invite)
  carries 256 random bits from `secrets.token_urlsafe(32)`. Guessing a
  preimage costs about 2^256 whether the hash is fast or slow. Argon2's cost
  factor only protects guessable secrets.
- **What HMAC would add.** It would stop two attackers:
  - someone who can write the DB, from planting a token row
  - someone holding a DB dump, from confirming a leaked plaintext offline

  Neither is a gain here. A DB writer can already flip `users.is_admin`
  (`make_admin.py`). Today's Argon2 hash is also keyless, so offline
  confirmation is already possible with a dump.
- **What HMAC would cost.**
  - A new Fly secret, which the app and every `flyctl ssh console` admin
    script (they call `init_db` and mint tokens) would need.
  - The first config value that must fail closed at boot.
  - A key-rotation design: a key id per row or dual-key lookups.
  - A total token outage if the key is lost or mis-set, including on a
    restore from the 30-day R2 backups.
  - Key plumbing into about 100 test call sites.
- **Industry practice** (recalled, not re-verified): GitHub stores a SHA-256
  of its tokens. NIST SP 800-63B allows an approved one-way hash for look-up
  secrets of 112 bits or more.
- **Precondition, pinned by a test.** The digest is sound only for secrets of
  at least 128 random bits. `token_digest()` must never be used for device
  `user_code`s, passwords or any short code.

The cache key is already `sha256(plaintext).digest()`. The stored digest is the
same value in hex. That is harmless: the cache never leaves the process.

**Constant-time compare: not added.** The lookup is an indexed SQL equality on
`sha256(attacker input)`. A timing leak there reveals bytes of stored digests.
Those give no preimage, so they can't yield a credential. This is the
selector/verifier argument. What's left distinguishes valid from invalid,
which the HTTP status already reveals.

This is the one decision the user should confirm before execution.

## Design

### Schema (`src/markland/db.py`)

- Add `token_digest TEXT` to `tokens` through `_add_column_if_missing`: nullable,
  no default. It is not in the `CREATE TABLE` text, so fresh and upgraded DBs
  take one code path, as `users.session_epoch` does.
- Add `CREATE UNIQUE INDEX IF NOT EXISTS idx_tokens_digest ON tokens(token_digest)`.
  SQLite rejects `ADD COLUMN … UNIQUE` and `ADD COLUMN … NOT NULL` without a
  default, so uniqueness lives in the index. NULLs are distinct in a UNIQUE
  index, so any number of un-backfilled rows coexist.
- Keep `token_hash TEXT NOT NULL` and `idx_token_hash` as they are. The index
  is unused, since salted hashes can't be looked up by equality. Dropping it
  is phase-2 cleanup.
- `_add_column_if_missing` tolerates `duplicate column name`. An admin script
  over ssh can run `init_db` while the app boots, and both can see the column
  missing. Without this the loser crashes. That's only a restart, but it is
  avoidable.

### Digest (`src/markland/service/auth.py`)

```python
def token_digest(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
```

This is the exact bearer string, prefix included, after `_request_bearer`'s
`.strip()`. `hash_token` and `verify_token` are unchanged, because invites
depend on their Argon2 semantics.

### Mint

`create_user_token` and `_create_token_for_agent` write `token_digest` **and**
keep writing the Argon2 `token_hash`. The current release authenticates only
through `verify_token(plaintext, token_hash)`, so dropping the Argon2 write
would lock every new token out after a rollback. That costs about 0.1 CPU-s per
mint, which is rare and runs in sync routes on the threadpool. Signatures and
return values don't change, and all eight mint callers pick this up with no
edits.

### Resolve order

`resolve_token` (cache first, unchanged) → `_resolve_uncached(conn, plaintext)`:

- **(a) Digest.** `SELECT id, principal_type, principal_id FROM tokens WHERE
  token_digest = ? AND revoked_at IS NULL`, served by `idx_tokens_digest`.
  On a hit, `_build_principal_and_touch`. No Argon2.
- **(b) New-shape fallback.** If the plaintext parses, `SELECT … WHERE id = ?
  AND revoked_at IS NULL AND token_digest IS NULL`. Type cross-check, then one
  Argon2 verify. This covers new-shape rows minted before this release **and**
  rows an older release mints during a rollback window. It has no date bound,
  on purpose.
- **(c) Legacy fallback.** `SELECT … WHERE revoked_at IS NULL AND token_digest
  IS NULL AND created_at < LEGACY_TOKEN_CUTOFF`. Argon2-verify each row until
  one matches.

**Invariant:** Argon2 only ever runs against rows with `token_digest IS NULL`
whose principal is not a revoked agent.
- A row whose digest is set and differs cannot be this token, so excluding it
  is exact, not a heuristic.
- `revoke_agent` sets only `agents.revoked_at` and leaves the agent's token rows
  unrevoked. A revoked agent's token can never authenticate:
  `_build_principal_and_touch` returns None before the touch, so it also can
  never be backfilled.

Without the second exclusion, a forgotten client retrying such a token would
pay Argon2 on every request, forever, and hold the counts above 0. Both (b)
and (c) add the `_NOT_REVOKED_AGENT` predicate
(`NOT EXISTS (SELECT 1 FROM agents a WHERE t.principal_type = 'agent' AND
a.id = t.principal_id AND a.revoked_at IS NOT NULL)`). It changes no auth
outcome.

**CRITICAL fall-through, preserved.** A legacy plaintext whose secret starts
with 16 lowercase hex chars plus `_` parses as new-shape (about 3.6e-12 per
token, 2^-38; the old docstring's 2.3e-12 is corrected). Then (b) misses and
(c) must still run. Legacy rows are all pre-cutoff, so (c) still finds it.
`test_resolve_token_falls_through_to_legacy_on_pk_miss` stays and also asserts
the backfill.

### `LEGACY_TOKEN_CUTOFF = "2026-05-10T00:00:00+00:00"`

Legacy-shape tokens can only have been minted before markland-9dm (#69)
reached prod. Evidence gathered 2026-09-27:

- #69 merged as 488711b on 2026-05-04T15:37Z. Its CI deploy run ran
  15:37:42–15:38:29Z and succeeded. The old image kept serving, and could
  still mint a legacy token, until that machine update completed.
- All 19 later deploy runs through 2026-05-10 descend from 488711b
  (`git merge-base --is-ancestor`). A review found that every successful
  deploy since, through 2026-09-27, does too.
- The legacy generators raise `NotImplementedError` from that commit on.
- Fly's release list only goes back to 2026-05-30, so it can't confirm this
  independently.

The cutoff is set about five days late on purpose. A late cutoff only adds a
few new-shape rows to (c)'s set, and (b) serves them anyway. An early cutoff
would silently lock a legacy token out. Two tests pin this:
- the constant: `LEGACY_TOKEN_CUTOFF >= "2026-05-04T16:00:00+00:00"`. That is
  the end of the deploy run plus margin for boot and clock skew.
- the resolver's behavior: a legacy row dated just before that floor still
  resolves through (c).

`created_at` is always `datetime.now(timezone.utc).isoformat()`, so the string
comparison is chronological.

### Lazy backfill

The digest is written by the existing touch statement, not a new one:

```sql
UPDATE tokens SET last_used_at = ?, token_digest = COALESCE(token_digest, ?) WHERE id = ?
```

This runs inside the existing `try: execute; commit / except sqlite3.Error: pass`.

- **No new write site.** It adds no new commit, transaction window, lock or
  threadpool hop on the shared connection (markland-5nk).
- **Once per TTL.** It runs at most once per token per cache TTL, like
  `last_used_at`. On path (a), `COALESCE` makes it a no-op for the digest.
- **Never blocks auth.** A failed write doesn't block auth. The row stays
  NULL, and the next uncached resolve (after the 60 s TTL) retries through
  (b) or (c).
- **Anti-planting.** The digest is written **only** for the row whose Argon2
  verify just succeeded. A PK hit or a type match alone never writes it.
  Otherwise `mk_usr_<victim_id>_<attacker_secret>` would bind the attacker's
  digest to the victim's row, and the attacker would then authenticate as
  the victim through (a).
- **Revoked rows are never verified or backfilled.** Every fallback filters on
  `revoked_at IS NULL` and excludes revoked agents' rows. Even if one got
  through, `_build_principal_and_touch` returns before the touch for a
  revoked agent.
- **One write, not two.** A test traces the resolve and asserts exactly one
  UPDATE, which carries both `last_used_at` and `token_digest`.
- **UNIQUE collisions are swallowed.** A collision is an `IntegrityError`
  (a `sqlite3.Error`), and in practice only a duplicate-plaintext bug
  could cause one.

### Cache and middleware

Unchanged. Revocation still works through `revoked_at IS NULL` in every query,
and the eviction rules stand. `_request_bearer.py` gets a docstring update only.

### Operator visibility

`token_digest_counts(conn) -> dict[str, int]` (in `auth.py`) and
`scripts/admin/token_digest_status.py` report three counts:

- `live`: non-revoked tokens whose agent, if any, isn't revoked
- `without_digest`: each costs one Argon2 verify on its next successful resolve
- `legacy_scan`: live, NULL digest, pre-cutoff. These are the rows every
  failed auth still verifies.

`legacy_scan == 0` means failed auth costs no Argon2, which closes
markland-ts6. `without_digest == 0` is the gate for phase 2.

## Cost model

| Path | Before | At deploy | Steady state |
|---|---|---|---|
| Valid token, digest set | 0.1 (new-shape) to 1.6 (legacy) CPU-s | about 10 µs | about 10 µs |
| Valid token, first resolve after deploy | same | 1 verify (new-shape); up to \|L\| verifies (legacy) | n/a |
| Unknown or revoked bearer | N verifies (all live rows) | \|L\| verifies | 0 |
| Forged `mk_usr_<existing id>_x` | 1 + N | 1 if that row has no digest, plus \|L\| | 0 |

N is the number of live rows (about 15). L is the set of live pre-cutoff rows
with a NULL digest. The known legacy tokens are the operator's Claude Code
token and the bot token, so |L| is expected to be about 2. The plan's release
task measures it before merge (the Fly SSH tunnel was unavailable while this
was written).

## Rollback safety

The current prod image is built from f94320b, the last code deploy. Its code
is identical to 627601c: the two commits after it touch only beads. That is
the rollback target, and the plan records its Fly release and image ref
before merge. Never roll back to a pre-#90 release. Those images lack the
resolved-token cache and the per-request memo, so a rollback to one brings
back the outage's ~1 CPU-s per legacy request.

That image against a migrated DB:

- **Unknown column and index are ignored.** Every INSERT and SELECT names its
  columns, and nothing selects `*` from tokens.
- **Old `init_db` is a no-op.** Its `CREATE … IF NOT EXISTS` statements don't
  touch the new column or index. It has no DROP or rebuild.
- **New tokens still authenticate on old code.** They carry an Argon2
  `token_hash` and an embedded `token_id`, so the old fast path (PK lookup +
  verify) works. Tests pin both.
- **Rollback-window tokens work after roll-forward.** Tokens the old release
  mints during a rollback have a NULL digest and `created_at` after the
  cutoff. After roll-forward they resolve through (b) and backfill. Tests pin
  this with rows written by the old release's exact INSERT.
- **No SQLite version skew.** Both images pin the same `python:3.12-slim`
  digest, so there is no file-format skew.

The rollback itself is still a machine update: it resets the burst balance
and triggers a reconnect storm. The runbook's "don't roll back first" advice
stands.

## Residual risks

- **Dormant pre-cutoff tokens.** A token that is never presented stays
  NULL, so every failed auth keeps verifying it until markland-brf revokes it.
  `token_digest_status.py` shows the count.
- **Dormant post-cutoff new-shape tokens** keep (b) reachable for their id: a
  forged bearer with that id costs one verify per request. Token ids are shown
  only to their owner. Phase 2 closes this.
- **The touch/backfill write shares the shared-connection race.** It is the
  same statement as today's `last_used_at` write, so it adds no new exposure
  and fixes none.
- **Test coupling.** `FlakyCommitConn`'s rowcount-misread flag applies to the
  next `UPDATE`. A resolve that backfills after the flag is set would consume
  it. Today's tests set the flag only after warm resolves.
- **Merge conflict.** Draft PR #94 (markland-5nk) also edits `db.py`. Expect a
  trivial conflict.
- **Sentry frame locals (pre-existing).** `PrincipalMiddleware` doesn't catch
  resolve exceptions, and sentry-sdk captures frame locals by default. Its
  scrubber misses the names `plaintext` and `header`, so a resolver exception
  already sends the bearer plaintext to Sentry. The new `digest` local rides
  along. Out of scope here; filed as a P2 bead at release.
- **Deleted users.** A digest-less token whose user row is gone can never be
  backfilled either. No user-deletion path exists today, so these rows aren't
  excluded. Add the same kind of predicate if deletion ships.
- **Changing the digest function later** (to HMAC, or adding a prefix) makes
  every stored digest silently stale. Stale non-NULL digests are excluded from
  (b) and (c), so those tokens would fail. Any change needs a new column or a
  version marker.

## Phase 2 (markland-brf, separate PR)

When `without_digest == 0`, or at a fixed date covering the rollback horizon
plus the 30-day R2 retention:

1. Revoke the NULL-digest rows that remain, with an audit entry.
2. Delete (b), (c) and the fall-through test.
3. Stop calling `hash_token` at mint; write `''` to satisfy NOT NULL
   (`verify_token` returns False on it).
4. Update `privacy.html`.
5. Later, drop `idx_token_hash`.

## Public copy

`privacy.html` lines 32 and 161 say tokens are "stored as Argon2 hashes" and
"Argon2id-hashed". Tokens are now stored as one-way hashes, both Argon2 and
SHA-256. The copy becomes "one-way hashes" / "hashed bearer tokens", and "Last
updated" is bumped. Under the policy's own definition (line 181), this is not
a material change. `security.html` ("hashed at rest") stays accurate.

## Testing strategy

- **Argon2 is counted at the class level.** Patch `PasswordHasher.verify`
  with `autospec=True, side_effect=PasswordHasher.verify`; the instance has
  `__slots__` and can't be patched. The count holds even if the code bypasses
  `verify_token`.
- **Positive controls.** Every `== 0` assertion is paired with a positive
  control in the same test, so a mis-wired spy can't pass vacuously.
- **Rows written as the previous release writes them.** A helper uses
  627601c's exact INSERT column list and covers legacy, pre-deploy new-shape,
  and rollback-window rows.
- **Existing count tests are rewritten to the new contract, not deleted.**
  Tests that meant "a fresh resolve happened" count `_resolve_uncached` calls.
- **New seams for the hook-based tests.** The revoke-race test hooks
  `_build_principal_and_touch`; the transient-error test hooks
  `_resolve_by_digest`.
- **The index is proven with `EXPLAIN QUERY PLAN`**, deterministically and
  with no timing.
- **Timing stays out of pytest.** `tests/bench_resolve_token.py` isn't
  collected; it runs on main and on the branch, and its output goes in the
  PR.
