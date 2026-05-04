# Self-Service Deletion — Design

**Date:** 2026-05-04
**Status:** Draft for review (post-brainstorm)
**Roadmap:** `docs/ROADMAP.md` "Next" lane → "Self-service deletion" (was tagged `[needs brainstorm]`)
**Related promises:**
- `docs/specs/2026-05-04-formal-privacy-policy-implementation.md` (via `docs/plans/2026-05-04-formal-privacy-policy.md`) — privacy policy commits to "Account deletion within 30 days of request" and "user_id replaced with a non-reversible token."
- Today's `/privacy` line 38 promises self-service before GA.

## Goal

Ship self-service deletion as the highest-leverage trust unlock before GA: let users delete individual documents (immediate, irreversible) and entire accounts (30-day reversible window, then irreversible) without contacting a human.

**Success criteria:**

1. From `/dashboard` or the document viewer, an owner can delete a single document with one click and one typed-confirmation, and the document, its revisions, and its grants are gone in the same transaction.
2. From `/settings/account`, a signed-in user can request account deletion, receive a magic-link confirmation email, click the link, and have their account enter a 30-day soft-delete window in the same step.
3. While in the soft-delete window, every public/shared surface treats the user's data as if it were deleted (404s, auth failures), but the data is recoverable via a single magic-link click that the user has had emailed to them.
4. After 30 days, a daily job hard-purges the user's owned data and anonymizes the `users` row to a tombstone. The audit log is preserved (append-only invariant intact); the tombstone carries no PII, so the user_id in audit rows is effectively a non-reversible token.
5. The same email address can register a fresh account post-purge, with no inherited data or grants.

## Non-goals

- **GDPR-style data export before deletion.** Separate roadmap item; the privacy policy commits to email-request export until self-service ships.
- **Recovering individually deleted documents.** Doc-delete is immediate-and-irreversible by design; the friction shape matches the stake (one doc, intentional click).
- **Bulk doc deletion** without account deletion. YAGNI.
- **Notifying grantees** when a doc they had access to is deleted. The 404 is the notification.
- **Org / team account deletion** semantics. No orgs exist yet.
- **Forensic / law-enforcement-hold** exception path. Manual ops process if it ever arises.
- **A "delete and reregister" race-condition prevention** beyond what user_id-keyed grants already give us. Email reuse is allowed; no inherited data by construction.

## Audience

| Path | Primary user | Activation moment |
|------|--------------|-------------------|
| Document deletion | Doc owner who wants to remove one document | Clicks Delete on `/dashboard` row or viewer toolbar |
| Account deletion | User leaving Markland (or testing the flow) | Visits `/settings/account` |

Both paths share the modal/typed-confirmation UI primitive; only account deletion adds the magic-link reverify step on top.

## Architecture

```
DOCUMENT DELETION (immediate, irreversible)        ACCOUNT DELETION (soft, 30-day reversible)
─────────────────────────────────────────         ──────────────────────────────────────────
User → /dashboard or viewer                        User → /settings/account
  │                                                  │
  │ "Delete this document" button                    │ "Delete my account" section
  ▼                                                  ▼
Modal: type the doc title to confirm              Modal: "Delete account" → POST /api/me/delete-request
  │                                                  ▼
  │ POST /api/d/{share_token}/delete                Email: "Confirm deletion of your
  │   (CSRF + session, owner-only)                       Markland account. Confirm:
  ▼                                                     markland.dev/account/delete?token=…"
docs.delete()                                        │
  → db.delete_document() (existing)                  │ User clicks confirm link
  → cascades: revisions + grants + bookmarks         ▼
  → audit_log.record(action="delete_doc")          GET /account/delete?token=… (form)
  → 200 / redirect                                   POST /account/delete (CSRF + token)
                                                     │
                                                     │ users.deleted_at = NOW()
                                                     │ audit_log.record("account_delete_request")
                                                     │ revoke all user + agent bearer tokens
                                                     │ invalidate session cookie
                                                     │ redirect to /goodbye
                                                     ▼
                                          ┌──── 30-day window ────┐
                                          │                       │
                                          │   User can sign in    │  Auth gate everywhere:
                                          │   via magic-link →    │  if users.deleted_at is set,
                                          │   /account/restore    │  treat as unauthenticated.
                                          │   "click to cancel"   │
                                          │                       │  Public docs from this user
                                          │   Restore = unset     │  → 404 (db.get_document
                                          │   deleted_at,         │   short-circuits when owner
                                          │   keep all data       │   is deleted).
                                          │                       │
                                          │   No-op otherwise     │  Share tokens for grantees
                                          │                       │  → 404 (same gate).
                                          └───────────────────────┘
                                                     │
                                                     │ Day 30: cron job
                                                     ▼
                                          purge_due_accounts() service
                                            - Hard-delete user-owned docs (cascades
                                              revisions, grants, bookmarks-on-them)
                                            - Hard-delete user's bookmarks
                                            - Hard-delete user's agents (cascades agent
                                              tokens)
                                            - Hard-delete user's user-tokens
                                            - Hard-delete user's pending invites
                                            - Hard-delete user's device_authorizations
                                            - **Anonymize the users row** (tombstone):
                                                email = NULL, display_name = NULL,
                                                deleted_at preserved, purged_at = NOW()
                                            - audit_log rows are LEFT UNTOUCHED
                                              (append-only triggers prevent mutation;
                                              user_id still references the now-anonymized
                                              tombstone, which carries no PII)
                                            - audit_log.record("account_purge",
                                              principal=system)
```

## Data model changes

### `users` table — two new columns

| Column | Type | Default | Meaning |
|--------|------|--------:|---------|
| `deleted_at` | TIMESTAMP | NULL | Set on confirmation; row is in soft-delete window. Auth gate treats deleted_at-set rows as unauthenticated. |
| `purged_at` | TIMESTAMP | NULL | Set when the cron has hard-deleted owned data and anonymized the row. After this, the row is a tombstone and `email`/`display_name` are NULL. |

State machine: `(deleted_at, purged_at)` ∈ {`(NULL, NULL)` active, `(set, NULL)` soft-deleted, `(set, set)` tombstoned}. The `(NULL, set)` state is invalid by construction.

### `account_deletion_tokens` table — new

Single-use, scoped tokens for the confirm and restore actions. Schema:

```sql
CREATE TABLE IF NOT EXISTS account_deletion_tokens (
  token        TEXT PRIMARY KEY,        -- argon2id-hashed
  user_id      TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose      TEXT NOT NULL CHECK (purpose IN ('confirm', 'restore')),
  created_at   TIMESTAMP NOT NULL,
  expires_at   TIMESTAMP NOT NULL,
  consumed_at  TIMESTAMP NULL
);
```

Plaintext tokens are returned by `request_account_deletion` to be embedded in the magic-link email; only the hash hits storage. Confirm-token expiry: 24 hours (longer than magic-link sign-in because users may not check email immediately for high-stakes actions). Restore-token expiry: 30 days (the full window).

Could piggyback on the existing `magic_links` table by adding a `purpose` column; chose a separate table to keep the auth-token schema focused. Implementation plan can revisit if the duplication smells.

### `audit_log` — unchanged

The append-only triggers (`audit_log_no_update`, `audit_log_no_delete` from PR #49) stay intact. The privacy policy's promise that "user_id is replaced with a non-reversible token" is honored at the *referent* level: the tombstone row in `users` carries no PII, so the user_id stops mapping to a real person at purge time, even though the foreign-key value is preserved in audit rows.

## Components

### `src/markland/service/account_deletion.py` (new)

```python
def request_account_deletion(
    conn: sqlite3.Connection, user_id: str, *, now: datetime | None = None
) -> str:
    """Issue a confirmation token. Idempotent: returns the existing
    unconsumed token if one is still valid, otherwise mints a new one.
    Returns plaintext for the email body."""

def confirm_account_deletion(
    conn: sqlite3.Connection, token_plaintext: str, *, now: datetime | None = None
) -> str | None:
    """Verify token, set users.deleted_at = NOW, revoke all bearer
    tokens for user + their agents. Returns the user_id on success;
    None on bad/expired/consumed/already-deleted."""

def restore_account(
    conn: sqlite3.Connection, user_id: str, *, now: datetime | None = None
) -> bool:
    """Unset users.deleted_at if still inside the 30-day window and
    not already purged. Returns True if restored, False if too late."""

def purge_due_accounts(
    conn: sqlite3.Connection, *, now: datetime | None = None
) -> int:
    """Find users.deleted_at < now - 30d AND purged_at IS NULL; cascade
    delete owned data; anonymize the row; record audit. Returns count."""
```

### HTTP routes

Modify `src/markland/web/identity_routes.py`:

- `POST /api/me/delete-request` — session-required, CSRF-required. Calls `request_account_deletion`, sends email via existing `EmailDispatcher`. Returns 204.
- `GET /settings/account` — new settings page; renders the "Delete account" panel + a typed-confirmation modal trigger. Session-required.

Modify or add `src/markland/web/account_deletion_routes.py` (new module to keep `identity_routes` from growing further):

- `GET /account/delete?token=…` — public route, serves a "Confirm account deletion" page that POSTs to the next route. Issues a CSRF token bound to the session cookie if present (anonymous in the email-on-different-device case — the token in the URL is the auth).
- `POST /account/delete` — public, requires the URL token. Calls `confirm_account_deletion`. On success: clears session cookie, redirects to `/goodbye`.
- `GET /goodbye` — public landing: "Your Markland account has been scheduled for deletion. Check your email for a cancel link if you change your mind."
- `GET /account/restore?token=…` — public; verifies the token, calls `restore_account`, redirects to `/dashboard` with a flash.

### Document deletion UI

Modify:

- `src/markland/web/templates/dashboard.html` — add a Delete button to each owned-doc row. Wired to a small modal: "Type the doc title to confirm." Submits `DELETE /api/d/{share_token}` (or `POST /api/d/{share_token}/delete` if the existing service expects POST — implementation plan verifies).
- `src/markland/web/templates/viewer.html` — same modal, owner-only (`{% if is_owner %}` conditional).

The doc-delete API surface already exists (`docs.delete` in `src/markland/service/docs.py:670`, `db.delete_document` in `src/markland/db.py:515` cascading to grants + revisions). No service-layer change needed; just UI.

### Auth gate

Modify `src/markland/service/auth.py` and `src/markland/web/principal_middleware.py`:

- All principal-resolution paths early-return "unauthenticated" when `users.deleted_at IS NOT NULL`. One predicate guards bearer-token auth, session-cookie auth, and the MCP `whoami` resolution.
- `db.get_document` (or its caller in `service/docs.py`) returns None when the owner is in deleted-not-purged state. Public-doc URLs and share-token URLs both flow through this; one change point gates both.

### Email template

Create:

- `src/markland/web/templates/emails/account_delete_confirm.txt` — text body with confirm link, cancel link (placeholder until `deleted_at` is set, then becomes meaningful), and 30-day timeline.
- `src/markland/web/templates/emails/account_delete_confirm.html` — HTML version (existing email pattern in `service/email.py`).

### Cron

Add a daily background task to the existing in-process scheduler pattern (matches `service/presence.py` GC):

- `src/markland/service/scheduler.py` (or wherever the presence GC is registered) — register `purge_due_accounts` to run at 03:00 UTC daily.
- A safety-net script `scripts/admin/purge_deleted_accounts.py` for the operator to invoke manually if the in-process scheduler ever misses runs.

## Soft-delete window semantics

Frozen-from-the-outside, the instant deletion is confirmed:

- All public docs owned by the user → 404
- All share-token resolutions for grants involving the user → 404
- All bearer tokens (user-tokens AND agent-tokens owned by them) → revoked at confirm-time
- Session cookie → cleared on the confirm response
- `markland_whoami` → `unauthenticated`
- The only working surface for the deleted user: sign in via magic-link (the standard `/login` flow), which lands on `/account/restore?token=…` (link delivered in the original confirmation email and a follow-up "your data will be purged in 7 days" email if such reminders are added later — out of scope for v1).

The 30-day window is purely a regret buffer for the deleting user. Everyone else's experience is "the account is gone today."

## Audit-log handling

Append-only invariant preserved (the PR #49 triggers stay in place). The privacy-policy promise is honored as follows:

| Privacy policy text | Implementation |
|---|---|
| "Account deletion ... removes ... magic-link records and any agent tokens you created" | Cron hard-deletes `magic_links`/`magic_link_consumed` rows for the user; agent rows + their tokens are hard-deleted via cascade. |
| "Audit-log entries about your account are retained, but the user_id is replaced with a non-reversible token" | `audit_log` rows are unchanged. The user_id in those rows remains a foreign key to `users`. After purge, the `users` row exists but has `email = NULL, display_name = NULL` — it is a tombstone, so the user_id no longer reverses to a real person. The token *is* the user_id; it has been "replaced with a non-reversible token" in the sense that it now resolves to nothing identifiable. |

This is a defensible reading of the policy that doesn't require violating the append-only invariant. The implementation plan should add a one-paragraph clarification to the privacy policy if counsel later thinks a stricter reading is required.

## Email reuse

Permitted. Once an account is purged (`purged_at` set, `email = NULL`), the original email address is fully released. A fresh registration with the same email creates a new user_id with no inherited data:

- Grants are keyed on user_id (not email), so a re-registration cannot inherit access to docs that were shared with the old account.
- Audit rows referring to the old user_id continue to point at the (now-tombstoned) original row, not the new one.
- Magic-link tokens issued to the new account are unrelated to anything tied to the old user_id.

## Confirmation UX details

**Document deletion** — typed-confirmation. Modal asks the user to type the document title verbatim before the Delete button activates. Justified divergence from the magic-link pattern: doc loss is a single-doc, small-stakes action with a typo-prone foot-gun (clicking Delete on the wrong row), and typed-confirmation is the lowest-friction guard.

**Account deletion** — magic-link reverify. Two reasons over typed-confirmation:

1. *Consistent with the auth model.* No passwords; magic-link is the only "you are who you say you are" primitive.
2. *Stronger against session-cookie theft.* Until `markland-bul` (server-side session revocation epoch) ships, a stolen cookie could trigger typed-confirmation deletion. Magic-link reverify forces the attacker to also have email access.

The cancel-deletion link in the same email gives the user a built-in cool-down and recovery affordance.

## Testing

Pure-Python pytest, mirroring existing patterns. No browser/E2E.

**Service-level** (`tests/test_service_account_deletion.py` — new):

- `request_account_deletion`: issues token; idempotent within window; persists with expected expiry.
- `confirm_account_deletion`: sets `deleted_at`; revokes bearer tokens for user + agents; rejects expired/invalid/already-used tokens; returns user_id on success.
- `restore_account`: unsets `deleted_at` within window; rejects after `purged_at`.
- `purge_due_accounts`: finds rows past 30 days; cascades documents/agents/tokens/bookmarks/invites/device_authorizations; anonymizes the users row; leaves audit_log untouched.

**Auth-gate** (extend `tests/test_principal_middleware.py`, `tests/test_auth.py`):

- Bearer token whose owner has `deleted_at` set → unauthenticated.
- Session cookie for a deleted user → unauthenticated.
- Public doc lookup short-circuits to None when owner is deleted.
- Share-token grants short-circuit when grantee is deleted.

**Route-level** (extend `tests/test_identity_routes.py`, add `tests/test_account_deletion_routes.py`):

- `POST /api/me/delete-request` requires session + CSRF; sends email; returns 204.
- `GET /account/delete?token=…` serves the form; rejects bad tokens.
- `POST /account/delete` confirms deletion; clears session; redirects to `/goodbye`.
- `GET /account/restore?token=…` within window restores; after purge 404s.
- `GET /settings/account` renders for signed-in users; 401 for anon.

**Doc-delete UI** (extend `tests/test_dashboard_*.py`, `tests/test_viewer.py`):

- `/dashboard` shows Delete button only on owned docs (not shared/bookmarked).
- Viewer shows Delete only when `is_owner`.

**Cron** (`tests/test_purge_cron.py` — new):

- Unit test: seeded DB, call `purge_due_accounts`, assert cascade.
- Boundary: account at 29d 23h stays; at 30d 1h goes.

## Sequencing

Three independently-mergeable phases:

1. **Phase 1 — Document deletion UI.** Surfaces the existing API on `/dashboard` and the viewer with typed-confirmation. Smallest, ships first; no schema changes.
2. **Phase 2 — Account deletion soft-delete.** Schema migrations (`users.deleted_at`, `users.purged_at`, `account_deletion_tokens` table). Service module. Routes. Email template. Auth gate. `/settings/account` page. Manually-invoked purge for testing; no cron yet.
3. **Phase 3 — Cron.** Wire `purge_due_accounts` into the in-process scheduler at 03:00 UTC daily. Add the manual-invocation script for ops fallback.

The plan should reflect this so an executor can ship Phase 1 alone if Phase 2 stalls in review, etc.

## Open follow-ups (not blocking)

- **GDPR-style export endpoint** (`GET /api/me/export`) — separate roadmap item; the privacy policy commits to email-request export until self-service ships.
- **"Your data is being purged in 7 days" reminder email** — out of scope for v1; revisit if support gets "I forgot I clicked delete" tickets.
- **Counsel review** of the audit-log anonymization interpretation — if a stricter reading of the privacy policy is required, add a clarifying paragraph.
- **Telemetry** — funnel events (`delete_request`, `delete_confirm`, `restore`, `purge`) once the metrics_events table lands.
