# Multi-agent Auth, Sharing, and Hosted Launch — Design

**Date:** 2026-04-19
**Status:** Draft for review
**Scope:** Transition Markland from a local-only stdio tool into a hosted, multi-principal service with user and agent identities, per-doc sharing, optimistic-concurrency conflict handling, and presence signaling.

## 1. Goals and positioning context

Markland's positioning is **a shared knowledge surface where humans and agents are equal editors.** Today's implementation — local SQLite, local stdio MCP server, no identity — can't support that positioning. This spec covers the auth, sharing, and infrastructure work that turns Markland into a hosted service where multiple principals (users and agents, including across owners) can safely read and edit the same docs.

### What launch enables

A principal can sign up, generate tokens for their MCP clients, register agents, publish docs, grant view or edit access to other users or agents (by email or agent ID), create invite links, receive email notifications on grants, and resolve conflicts through optimistic versioning with revision history.

### What launch does not include

- Real-time collaborative editing (no CRDTs, no OT)
- A WYSIWYG editor
- OAuth / service-agent product surface (data model supports it; no user-facing flow)
- Organizations, teams, or workspaces
- Comments, reactions, webhooks, offline mode, billing

## 2. Locked decisions (anchors for every section that follows)

| Decision | Choice |
|---|---|
| Deployment model | Hosted service at a URL |
| Primary transport | Remote MCP (streamable-http). Stdio proxy is a deferred expansion. |
| Principals | Users and agents. User-owned agents inherit their owner's grants. Service-owned agents exist in the data model; not user-facing at launch. |
| Auth mechanism | API tokens (argon2id-hashed). OAuth deferred until a real service partner appears. |
| Sharing | Per-doc grants targeting user (by email) or agent (by ID). Levels: `view`, `edit`. Invite links supported. Per-principal revocation. |
| Conflict handling | Optimistic concurrency via monotonic `version`. Revisions table as a safety net. No CRDT, no locking. |
| Coordination signal | Advisory presence (`reading`, `editing`) with TTL. Not enforced. |
| Teams / orgs | Deferred. Not at launch. |

## 3. Principals and accounts

Two kinds of principals can hold permissions:

### User
A human with an account.
- `user_id` (opaque, `usr_<hex>`)
- `email` (unique, used for invites and magic-link login)
- `display_name`
- Owns a set of agents and a set of docs.

### Agent
A non-human actor that calls the API on behalf of a user or a service.
- `agent_id` (opaque, sharable, `agt_<hex>`). Public identifier — pasted like an email address.
- `display_name` (appears in audit logs)
- `owner_type`: `user` | `service`
- `owner_id`: FK to `users.id` (user-owned) or service identifier like `svc_openclaw` (service-owned)

**Inheritance rule:** user-owned agents automatically inherit grants made to their owner. Service-owned agents do not inherit; they receive access only via direct grants.

### Service identities at launch
Service-owned agents are stored in the schema but not exposed through any user-facing flow. Admins create them by hand in early days. OAuth and a service-registration surface arrive when the first real integration partner materializes.

### Admin
"Admin" at launch is a boolean `is_admin` column on `users`, default false. The operator sets their own user's flag to true manually via SQL after first signup. Admins can feature public docs (`markland_feature`), create service-owned agents, and read the audit log. No admin UI at launch — direct DB for operator tasks. Admin promotion via UI is deferred.

## 4. Authentication and tokens

### Token types
Bearer tokens carried as `Authorization: Bearer <token>`:

- **User tokens:** `mk_usr_<random>`. Created by a user on `/settings/tokens`. Act as the user.
- **Agent tokens:** `mk_agt_<random>`. Created by a user on `/settings/agents/<id>/tokens` (user-owned) or by admin (service-owned). Act as the agent. Inherit owner's grants for user-owned agents.

Tokens are ≥32 bytes of random entropy, stored hashed (**argon2id**), never retrievable in plaintext after creation.

### Token lifecycle
- **Create:** full token shown once; hash persisted.
- **List:** label, `created_at`, `last_used_at` displayed; never the raw token.
- **Revoke:** hash deleted; all subsequent requests 401.
- **No expiry at launch.** Tokens live until revoked. Expiry and rotation are a later decision.

### Request flow
1. Request presents `Authorization: Bearer …`.
2. Markland hashes the presented token, looks it up in `tokens`.
3. Token row resolves to a principal (user or agent).
4. Principal is attached to the request for all permission checks.
5. `last_used_at` updated asynchronously (never blocks the request).

### Scope
Tokens are unscoped within their principal — an agent token can do anything the agent can do. Read-only access is expressed via grant level (`view`), not token scopes.

### 4.1 Device flow for CLI / MCP-client onboarding

A second entry point for obtaining a user token, designed for the "paste a URL into Claude Code and be set up" experience. Same pattern as GitHub CLI, Vercel, `npm login`.

**Flow**

1. User pastes `https://markland.dev/setup` (optionally with `?invite=<token>`) into Claude Code.
2. Claude Code fetches the URL, receives a runbook, and executes it:
   1. `POST /api/auth/device-start` → `{device_code, user_code: "ABCD-1234", verification_url, poll_interval, expires_in}`
   2. Shows the user: *"Visit https://markland.dev/device and enter code ABCD-1234."*
   3. Polls `POST /api/auth/device-poll {device_code}` every `poll_interval` seconds.
3. User visits the URL in a browser:
   - Signs up via magic link if new, else logs in.
   - Enters `user_code` on `/device`.
   - If the starting URL included `?invite=<token>`, the authorization screen names the grant ("This will give you edit access to Bob's doc *<title>*") so consent covers both acts in one click.
   - Confirms.
4. Next `device-poll` returns `{status: "authorized", access_token}`.
5. Claude Code installs the MCP server. Prefer `claude mcp add markland https://markland.dev/mcp --header "Authorization=Bearer <token>"` when the CLI is available; fall back to editing `~/.mcp.json` directly.
6. User restarts Claude Code; `markland_*` tools are live.

**Security constraints**
- `user_code` is 8 characters from a reduced alphabet (no ambiguous glyphs — no `0`/`O`, `1`/`I`/`l`). Displayed with a hyphen (`ABCD-1234`) for readability.
- Device-start rate-limited per IP.
- Poll rate-limited per `device_code`; exceeding the limit returns `slow_down`.
- Codes expire after 10 minutes.
- Authorization requires a logged-in session; the user always sees who/what they're authorizing.
- Single-use: once `status` transitions to `authorized`, the code is consumed on first successful poll.

**Runbook endpoint**
`GET /setup` returns prose + shell snippets that Claude Code executes. The runbook references the device-flow endpoints and the invite-token parameter if present. Documented behavior, not a black box.

**MCP-client-install detail**
Claude Code's `claude mcp add` handles JSON merging and config-path differences across versions. Other clients (Cursor, VS Code MCP) have their own install paths — launch targets Claude Code's happy path; other clients are documented but not runbook-automated at launch.

## 5. Authorization — grants, levels, inheritance

### Grant model
A `grants` row says "principal P has level L on doc D":

| Column | Type | Notes |
|---|---|---|
| doc_id | text | FK to documents.id |
| principal_id | text | `usr_…` or `agt_…` |
| principal_type | text | `user` \| `agent` |
| level | text | `view` \| `edit` |
| granted_by | text | principal_id of granter |
| granted_at | text | ISO8601 UTC |

Primary key: `(doc_id, principal_id)`. Re-granting upserts (upgrades/downgrades level). Index `idx_grants_principal` on `(principal_id, doc_id)` powers "shared with me."

### Levels
- **view** — read doc via API and viewer.
- **edit** — view + update content/title.
- **owner** — implicit, stored on the doc itself (`documents.owner_id`). Can do everything, plus manage grants, delete, change visibility, transfer ownership. One owner per doc at launch.

### Permission resolution
For principal P and action A on doc D, check in order:

1. Is P the owner? → allow anything.
2. Direct grant `(D, P)` present? → use its level.
3. Is P a user-owned agent and a grant `(D, P.owner)` exists? → inherit that level.
4. Is the doc public and the action is view? → allow.
5. Is a valid `share_token` present and the action is view? → allow.
6. Otherwise deny.

Rule (3) implements "user-owned agents inherit." Service-owned agents skip it.

### Share tokens unchanged
Today's `share_token` primitive (public read links) is preserved. It grants view-only access to anyone-with-the-link and is independent of the grant system.

### Intentional non-features
- No group/team principals
- No time-limited grants (revoke is the only expiry)
- No action-level grants beyond view/edit
- No folder/workspace propagation
- No deny rules — grants are allow-only

## 6. Sharing flows

Three ways to grant access, all producing a `grants` row.

### 6.1 Grant to an existing Markland user
1. Owner opens doc → Share → types `alice@example.com` → picks `view`/`edit`.
2. Server looks up Alice by email.
3. If found: insert `grants (doc_id, alice.user_id, 'user', level, granted_by=owner, granted_at=now)`.
4. Alice sees the doc in "Shared with me" on next load.
5. Email sent to Alice: *"Bob shared <title> with you — <view|edit> access."*
6. If no Alice account exists, fall back to the invite-link flow (§6.3) automatically.

### 6.2 Grant by agent ID
1. Owner opens doc → Share → pastes `agt_openclaw_7f2a` (or picks from "known agents" — agents previously granted access to any of the owner's docs) → picks level.
2. Server looks up the agent; agent must exist.
3. Insert `grants (doc_id, agent_id, 'agent', level, …)`.
4. Agent can immediately act on the doc.
5. Email to agent's owner (if user-owned): *"Bob granted your agent <agent name> <level> access to <title>."*
6. Service-owned agents receive no email (no owning human to notify at launch).

### 6.3 Invite link
1. Owner opens doc → Share → Create invite link → picks level, single-use vs reusable, optional expiry.
2. Server creates an `invites` row and returns `https://markland.dev/invite/inv_<random>`.
3. Owner delivers the link manually (no Markland-sent email at creation — delivery channel is owner's choice).
4. Recipient visits the link.
   - Signed in: one-click Accept → grant row for their user → redirect to doc.
   - Not signed in: sign up via magic link → accept → grant → doc.
5. Single-use invites decrement `uses_remaining` on accept; revoked invites 410.

### 6.4 Revocation
- Per-principal: owner views grants list, clicks X, grant row deleted — that principal loses access on the next request.
- Per-invite: owner revokes unused invites in the same dialog.
- No email on revoke (low value, noisy).

### 6.5 MCP tools for sharing
Sharing is a first-class agent operation (your agent can say "share this with Alice"):

| Tool | Purpose |
|---|---|
| `markland_grant(doc_id, principal, level)` | `principal` is an email or `agt_…` id; upserts grant. Owner only. |
| `markland_revoke(doc_id, principal)` | Removes grant. Owner only. |
| `markland_list_grants(doc_id)` | Returns current grants. Requires edit or owner. |
| `markland_create_invite(doc_id, level, single_use=True, expires_in_days=None)` | Returns invite URL. Owner only. |
| `markland_revoke_invite(invite_id)` | Kills an unused invite. Owner only. |

### 6.6 Web UI surface at launch
- Share dialog on the doc viewer covering all three paths.
- "Shared with me" section on the user dashboard.
- `/settings/agents` — register agents, view/rotate agent tokens.
- `/settings/tokens` — manage user tokens.

No activity feed, share history, or notification center at launch.

## 7. Email notifications

Transactional email via **Resend** (Python SDK, 3K/mo free tier, `notifications@markland.dev`, from-name "Markland").

| Trigger | Recipient | Content |
|---|---|---|
| User grant created | Grantee (user) | "Bob shared <title> with you — <level> access. Open: <link>" |
| User grant level changed | Grantee | "Bob changed your access to <title> to <level>." |
| Agent grant created (user-owned agent) | Agent's owning user | "Bob granted your agent <agent name> <level> access to <title>." |
| Agent grant created (service-owned agent) | — | No email. |
| Invite accepted | Invite creator | "Alice accepted your invite to <title>." (optional, low-priority; include if cheap) |
| Magic-link login | User | "Your Markland login link (expires in 15 minutes)." |
| Grant revoked | — | No email. |
| Token/agent revoked | — | No email. |

Email sending is best-effort: failure to send never fails the grant. Retries via a lightweight in-process queue with jittered backoff.

## 8. Conflicts and versioning

Markland is **not** a real-time collaborative editor. Writes are coordinated via optimistic concurrency, and every write preserves the previous state for recovery.

### 8.1 Optimistic version counter
`documents.version INTEGER NOT NULL DEFAULT 1`, monotonic, incremented on every successful update.

- `markland_get` and `GET /api/docs/{id}` return the current `version`.
- `markland_update` requires `if_version`. On mismatch, return a `conflict` error containing the current `version` and current content. Callers re-read, reconcile, retry.
- HTTP equivalent: `ETag` header on GET, `If-Match` on PATCH.

Conflicts are the caller's responsibility to resolve. For agents, read-merge-retry is a natural loop; for humans, the web UI surfaces the conflict with both versions.

### 8.2 Revisions table
Every successful update writes the *previous* state to `revisions` before overwriting:

| Column | Type | Notes |
|---|---|---|
| id | integer PK autoincrement | |
| doc_id | text | FK |
| version | integer | the version being preserved (pre-update) |
| title | text | |
| content | text | |
| principal_id | text | who wrote the version being preserved |
| principal_type | text | user \| agent |
| created_at | text | |

No UI surface at launch. Preserved so a future `markland_history(doc_id)` tool can restore. Retention cap: 50 most recent revisions per doc (older revisions dropped on write). Acceptable storage cost given typical markdown size.

### 8.3 Excluded from launch
- Real-time collab (CRDT/OT)
- Three-way auto-merge
- WYSIWYG editor
- Diff viewer / revision UI

## 9. Presence signaling

Advisory, non-enforcing coordination primitive. Agents announce they're reading or editing; other agents can choose to wait. **Does not lock.** Conflict safety still comes from §8.

### 9.1 Presence table

| Column | Type | Notes |
|---|---|---|
| doc_id | text | FK |
| principal_id | text | |
| principal_type | text | user \| agent |
| status | text | `reading` \| `editing` |
| note | text NULL | freeform ("working on section 3") |
| updated_at | text | |
| expires_at | text | `updated_at + 10 min` |

Primary key: `(doc_id, principal_id)`. Stale rows (past `expires_at`) filtered on read and garbage-collected in a periodic job.

### 9.2 Tools and API

| Tool | Purpose |
|---|---|
| `markland_set_status(doc_id, status, note=None)` | Upsert this principal's presence; refreshes `expires_at`. |
| `markland_clear_status(doc_id)` | Remove this principal's presence row. |

`markland_get(doc_id)` response gains `active_principals: [{principal_id, display_name, status, note, updated_at}, …]`, filtered to non-expired rows.

### 9.3 "Done" state
Not an explicit state. An agent finishing work clears the row (or lets it expire). Keeps the state space to `reading | editing | absent`. A richer "announcement" primitive (activity events) can arrive later if needed.

### 9.4 Heartbeat
Agents are expected to re-call `markland_set_status` every ~5 minutes to stay visible. If an agent crashes, the row expires after 10 minutes. No server-to-agent ping.

## 10. Data model changes

### 10.1 New tables

**`users`**
| Column | Type | Notes |
|---|---|---|
| id | text PK | `usr_<hex>` |
| email | text UNIQUE NOT NULL | |
| display_name | text | |
| is_admin | integer NOT NULL DEFAULT 0 | see §3 "Admin" |
| created_at | text NOT NULL | |

**`agents`**
| Column | Type | Notes |
|---|---|---|
| id | text PK | `agt_<hex>` |
| display_name | text NOT NULL | |
| owner_type | text NOT NULL | `user` \| `service` |
| owner_id | text NOT NULL | FK to `users.id` or service identifier |
| created_at | text NOT NULL | |
| revoked_at | text NULL | soft-delete; revoked agents 401 |

**`tokens`**
| Column | Type | Notes |
|---|---|---|
| id | text PK | `tok_<hex>` |
| token_hash | text NOT NULL | argon2id |
| label | text | human-readable |
| principal_type | text NOT NULL | `user` \| `agent` |
| principal_id | text NOT NULL | |
| created_at | text NOT NULL | |
| last_used_at | text NULL | async-updated |
| revoked_at | text NULL | |

Index: `idx_token_hash` on `token_hash`.

**`grants`** — see §5.

**`invites`**
| Column | Type | Notes |
|---|---|---|
| id | text PK | `inv_<hex>` |
| token_hash | text UNIQUE NOT NULL | |
| doc_id | text NOT NULL | FK |
| level | text NOT NULL | `view` \| `edit` |
| single_use | integer NOT NULL | 0/1 |
| uses_remaining | integer NOT NULL | |
| created_by | text NOT NULL | principal_id |
| created_at | text NOT NULL | |
| expires_at | text NULL | |
| revoked_at | text NULL | |

**`revisions`** — see §8.2.

**`presence`** — see §9.1.

**`device_authorizations`** — see §4.1.

| Column | Type | Notes |
|---|---|---|
| device_code | text PK | opaque, ≥40 bytes of entropy |
| user_code | text UNIQUE NOT NULL | 8 chars, reduced alphabet |
| status | text NOT NULL | `pending` \| `authorized` \| `expired` \| `denied` |
| user_id | text NULL | set on authorize |
| invite_token | text NULL | optional piggyback from `?invite=…` |
| created_at | text NOT NULL | |
| expires_at | text NOT NULL | `created_at + 10 min` |
| polled_last | text NULL | rate-limit hint |
| authorized_at | text NULL | |

Index: `idx_device_user_code` on `user_code` for the `/device` page lookup.

**`audit_log`**
| Column | Type | Notes |
|---|---|---|
| id | integer PK autoincrement | |
| doc_id | text NULL | |
| action | text NOT NULL | `publish` \| `update` \| `delete` \| `grant` \| `revoke` \| `invite_create` \| `invite_accept` |
| principal_id | text NOT NULL | |
| principal_type | text NOT NULL | |
| metadata | text | JSON blob, action-specific |
| created_at | text NOT NULL | |

### 10.2 Changes to `documents`

Add:
- `owner_id text` — FK to `users.id`. Required once migration lands.
- `version integer NOT NULL DEFAULT 1`.

Preserved unchanged: `id`, `title`, `content`, `share_token`, `created_at`, `updated_at`, `is_public`, `is_featured`.

### 10.3 Migration from local-only

**No automated migration.** The hosted deployment starts with a fresh DB. The existing local stdio version keeps working for anyone still running it; it is not upgraded in place. A scripted export tool is built only if a user with a non-trivial local library asks for it post-launch.

### 10.4 Storage choice

SQLite on a Fly volume with WAL mode. Handles the expected write volume for the first ~100 users with headroom. Migrate to Postgres when write contention or backup requirements demand it.

## 11. Infrastructure — launch stack

Target scale: ~100 users. Single-region, single-deployable, ~$7–12/mo.

| Concern | Choice | When to change |
|---|---|---|
| App runtime | Fly.io app, `shared-cpu-1x`, 1 GB RAM | Multi-region required, or sustained >80% CPU |
| Web framework | FastAPI + FastMCP (existing) | Only if FastMCP HTTP transport regresses |
| DB | SQLite on 3 GB Fly volume, WAL mode | Write contention visible, or volume near 80% |
| DB replication / backup | Litestream → Cloudflare R2 | Moving to Postgres |
| Email | Resend | Volume exceeds Resend business tier |
| Web login | Magic links via signed single-use token → session cookie | Users ask for SSO |
| Session storage | Signed cookies (itsdangerous) carrying `user_id` + expiry | Per-session revocation needed |
| API token auth | Argon2id-hashed bearer tokens (§4) | — |
| Secrets | Fly secrets | — |
| Domain + TLS | Cloudflare DNS → Fly; auto-managed TLS | — |
| Error tracking | Sentry (free tier) | Exceeds free tier |
| Logs | Fly built-in + JSON stdout | Retention/volume grows |
| Metrics | Fly dashboard | Need custom business metrics |
| Rate limiting | Per-token in-process token bucket; defaults 60/min user, 120/min agent | Distributed limiting needed |
| CI / deploy | GitHub Actions → `fly deploy` on push to `main` | More environments required |
| Staging | None at launch | Paying customers / SLA expectations |

### Explicit non-goals for infrastructure at launch

- No Kubernetes, Terraform, or multi-region
- No Redis / queue (background work via `asyncio.create_task` or threads)
- No object storage for docs themselves — markdown stays in SQLite rows
- No CDN — FastAPI serves HTML + inline CSS directly at this traffic level
- No feature flags — fast deploys + git revert is the rollback strategy

### Operational signals to watch (for "when to upgrade")

- SQLite writes/sec at p50 and p99
- Fly volume utilization
- Resend monthly email volume
- Token creation rate (informal signal of real multi-agent usage)
- Signup → first agent token → first MCP call activation funnel

## 12. API and MCP surface

### 12.1 Architecture

Shared service layer so HTTP API and MCP tools don't duplicate logic:

```
src/markland/
  service/
    docs.py       # CRUD + permission checks + version handling
    grants.py     # grant/revoke/list
    invites.py    # create/accept/revoke
    auth.py       # token hashing, principal resolution, sessions
    presence.py   # set/clear/list
    email.py      # Resend client + templates
  web/
    api.py        # FastAPI JSON routes for the web UI
    mcp.py        # FastMCP tool defs (thin wrappers over service/)
    pages.py      # HTML pages (viewer, dashboard, settings)
  db.py           # thin query layer (existing, expanded)
  models.py       # dataclasses (existing, expanded)
```

**Rule:** MCP and HTTP handlers both call into `service/`. Neither reaches into `db.py` directly.

### 12.2 MCP tools — consolidated list

**Identity**
- `markland_whoami()` — returns `{principal_id, principal_type, display_name, owner_id?}`
- `markland_list_my_agents()` — user tokens only; agent tokens see only themselves

**Docs** (existing, updated for auth and versioning)
- `markland_publish(content, title?, public?)` — creates doc owned by the principal's user (or the agent's owning user). Sets `owner_id`. Returns `{id, share_token, version, ...}`.
- `markland_list()` — docs where principal is owner OR has a grant (direct or inherited).
- `markland_get(doc_id)` — requires view. Returns doc including `version` and `active_principals`.
- `markland_search(query)` — scoped to docs the principal can view.
- `markland_update(doc_id, content?, title?, if_version)` — requires edit. On version mismatch, returns `conflict` error with current version + content.
- `markland_delete(doc_id)` — owner only.
- `markland_share(doc_id)` — returns `share_token` URL. Unchanged semantics.
- `markland_set_visibility(doc_id, public)` — owner only.
- `markland_feature(doc_id, featured)` — admin only at launch (see §3 "Admin").

**Sharing** (new)
- `markland_grant(doc_id, principal, level)`
- `markland_revoke(doc_id, principal)`
- `markland_list_grants(doc_id)`
- `markland_create_invite(doc_id, level, single_use=True, expires_in_days=None)`
- `markland_revoke_invite(invite_id)`

**Presence** (new)
- `markland_set_status(doc_id, status, note=None)` — status ∈ {`reading`, `editing`}
- `markland_clear_status(doc_id)`

### 12.3 HTTP API

Mirrors the MCP surface plus web-session endpoints:

```
# Auth / session
POST   /api/auth/magic-link             body: {email}
POST   /api/auth/verify                 body: {token}   → sets session cookie
POST   /api/auth/logout

# Device flow (see §4.1)
POST   /api/auth/device-start           body: {invite_token?}
                                        → {device_code, user_code, verification_url, poll_interval, expires_in}
POST   /api/auth/device-poll            body: {device_code}
                                        → {status, access_token?}
POST   /api/auth/device-authorize       authed; body: {user_code}
                                        → binds session user to user_code, accepts invite if bound
GET    /device                          HTML page for entering user_code
GET    /setup                           runbook returned to Claude Code

# Identity
GET    /api/me                          → user + agents + token labels
POST   /api/tokens
DELETE /api/tokens/{id}
POST   /api/agents                      body: {display_name}
DELETE /api/agents/{id}

# Docs
GET    /api/docs
POST   /api/docs
GET    /api/docs/{id}                   → body + ETag: "<version>"
PATCH  /api/docs/{id}                   requires If-Match: "<version>"
DELETE /api/docs/{id}

# Grants
GET    /api/docs/{id}/grants
POST   /api/docs/{id}/grants            body: {principal, level}
DELETE /api/docs/{id}/grants/{principal_id}

# Invites
POST   /api/docs/{id}/invites
DELETE /api/invites/{id}
POST   /api/invites/{token}/accept      → creates grant, redirects

# Presence
POST   /api/docs/{id}/presence          body: {status, note?}
DELETE /api/docs/{id}/presence
```

### 12.4 Auth in MCP handlers

FastMCP exposes request headers via `Context`. Every tool wraps its handler in an `@authenticated` decorator that:
1. Extracts `Authorization` header.
2. Calls `service.auth.resolve_token`.
3. Raises `MCPError(code="unauthenticated")` on failure.
4. Injects `principal` into the handler's kwargs.

### 12.5 Error shapes

**HTTP API**
- `400` bad input
- `401` no/invalid/revoked auth
- `403` authed but forbidden
- `404` doesn't exist **or** principal lacks view access (intentionally indistinguishable to prevent ID enumeration)
- `409` version conflict
- `410` invite expired/used/revoked

**MCP**
- `MCPError(code=...)` with machine-readable codes: `unauthenticated`, `forbidden`, `not_found`, `invalid_argument`, `conflict`, `gone`. FastMCP translates to MCP protocol errors.

### 12.6 The `/mcp` endpoint

FastAPI app mounts FastMCP's `streamable-http` ASGI app at `/mcp`. Same process as the web app, same deploy, same log stream.

### 12.7 Explicit non-features
- No webhooks
- No bulk grant operations
- No grant delegation (only owner changes grants)
- No API versioning (everything is v1-implicit; `/api/v2/` arrives when needed)

## 13. Rollout plan

### Phase 0 — dogfooding (pre-launch)
- Register domain, stand up Fly app, point DNS.
- Seed own user account. Use hosted instance exclusively for a week. Claude Code points at `https://markland.dev/mcp`.
- Every feature in this spec works end-to-end before anyone else is invited.

### Phase 1 — private beta
- Invite-only. 5–10 hand-picked users.
- Waitlist open on the landing page; no public announcement.
- Goal: catch auth/sharing bugs before strangers find them.

### Phase 2 — public launch
- Waitlist drains, signups open. `/explore` shows public docs.
- Announce on HN, X, relevant subreddits, MCP server directories.
- Track: signups, tokens created, `markland_publish` calls, invites sent, grants accepted, activation funnel.

No feature flags. Phases advance by DNS/access, not by config.

## 14. Success criteria for declaring launch "done"

A non-engineer friend can:
1. Sign up with email.
2. Install Claude Code with Markland MCP by pasting the config block.
3. Ask their agent to publish a doc.
4. Share it with you by email.
5. Your agent edits it via MCP — with no silent data loss and no CRDT.
6. They see the edit in the viewer.

All without instructions beyond a one-page quickstart.

## 15. Explicit non-goals for this project

Flagged throughout; consolidated here for clarity.

**Product**
- Real-time collaborative editing, CRDTs, OT, three-way auto-merge
- WYSIWYG editor
- Comments, reactions, presence cursors, activity feeds
- Organizations, teams, workspaces
- Folders, nested documents, tags
- Webhooks, external integrations, offline mode
- Billing / pricing / plans
- OAuth and service-agent registration UI (data model only)

**Engineering**
- Postgres migration
- Multi-region deployment
- Kubernetes, Terraform, IaC beyond `fly.toml`
- Redis, message queue, background worker process
- Object storage for doc bodies
- CDN
- Feature-flag system
- API versioning scheme
- Real-time SSE/WebSocket surface for presence

## 16. Open questions deferred to implementation

Best decided during the build:

- Magic-link expiry — lean: 15 minutes, single-use
- Default rate-limit tiers — lean: 60/min user, 120/min agent
- Email sender identity — lean: `notifications@markland.dev`, display "Markland"
- `PATCH /api/docs/{id}` body shape — lean: JSON envelope for consistency with MCP
- Token label UX — lean: required free-form string, no validation beyond length
- Presence heartbeat cadence — lean: 5 min client refresh, 10 min server-side TTL

## 17. Implementation sequencing

This spec is too large for a single implementation plan. Recommended decomposition into sequential plans, each producing working software:

1. **`2026-04-19-hosted-infra.md`** — Fly app + volume + Litestream backups + Sentry + Resend + deploy pipeline. Nothing about auth yet; the existing local app runs on hosted infra first. Ends with the current local stdio behavior reachable at `https://markland.dev/mcp` for a single hardcoded "admin" principal.

2. **`2026-04-19-users-and-tokens.md`** — Users table, magic-link login, user tokens, `/settings/tokens`, `markland_whoami`. Docs stay owner-less; API scoped to "any authenticated principal." Ends with a usable hosted single-user experience.

3. **`2026-04-19-doc-ownership-and-grants.md`** — `owner_id` on docs, `grants` table, `markland_grant` / `markland_revoke` / `markland_list_grants`, per-doc permission resolution, "Shared with me" dashboard section.

4. **`2026-04-19-agents.md`** — Agents table, agent tokens, `markland_list_my_agents`, inheritance rule, `/settings/agents`.

5. **`2026-04-19-invite-links.md`** — Invites table, `markland_create_invite` / `markland_revoke_invite`, invite acceptance flow (signed-in and sign-up paths), email on new-user signup-through-invite.

6. **`2026-04-19-device-flow.md`** — Device authorizations table, `/api/auth/device-*` endpoints, `/device` page, `/setup` runbook endpoint, Claude Code happy-path verification. Folds in invite-token piggyback for one-click onboarding + grant-accept.

7. **`2026-04-19-email-notifications.md`** — Resend integration, templates, triggers for grants and invite acceptance, best-effort in-process retry.

8. **`2026-04-19-conflict-handling.md`** — `version` column, `revisions` table, `if_version` / `ETag` / `If-Match` surface, `conflict` error handling end-to-end.

9. **`2026-04-19-presence.md`** — Presence table, `markland_set_status` / `markland_clear_status`, `active_principals` in `markland_get`, stale-row GC.

10. **`2026-04-19-launch-polish.md`** — Rate limiting, audit-log table, Sentry dashboards, onboarding quickstart page, `/explore` adjustments for auth'd context.

Plans 1–2 are launch-blocking and linear. Plans 3–7 can be partially parallelized once user identity is in place (device flow depends on invites being in place for the piggyback path, but works without them). Plans 8–9 are independent and can land anywhere after plan 3. Plan 10 is the pre-launch bundle.

---

**End of spec. The next step is `writing-plans` over plan 1 (`hosted-infra`) — we implement sequentially from there.**
