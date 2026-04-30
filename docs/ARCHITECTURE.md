# Markland Architecture

This document is a wayfinding map for engineers working on Markland. It covers what
the service is, how a request flows through it, where each feature lives, and how the
ten implementation plans stacked into the current codebase. For authoritative design
decisions see `docs/specs/2026-04-19-multi-agent-auth-design.md`; for per-plan status
see `docs/execution/status.md`.

## Overview

Markland is a shared-notes surface where humans and agents are equal editors over
MCP. The v1 launch covers: hosted Fly.io deployment with Litestream-backed SQLite;
magic-link auth with per-user API tokens; user-owned and service-owned agents with
their own tokens; per-doc grants by email or agent id; single- and multi-use invite
links; Claude Code onboarding via OAuth device flow at `/setup`; optimistic
concurrency (version + ETag) with a capped revision log; advisory presence badges;
transactional email through Resend via an in-process dispatcher; per-principal rate
limiting; an append-only audit log with admin UI; and JSON-line activation funnel
metrics. Real-time CRDT editing, teams/orgs, and OAuth are explicitly out of scope.

## Request paths

- **MCP (local stdio)** — `src/markland/server.py::build_mcp` can run standalone
  via the FastMCP CLI for local development. Still useful while Claude Code is
  offline.
- **MCP (hosted, streamable-http)** — the same `build_mcp` result is mounted at
  `/mcp` inside the FastAPI app by `src/markland/web/app.py::create_app`. Requests
  hit `PrincipalMiddleware` first (bearer → `request.state.principal`), then
  `RateLimitMiddleware`, then FastMCP's session manager.
- **Web viewer** — `/d/<share_token>` renders a document in `document.html` with
  the presence badge block. `/explore`, `/dashboard`, `/settings/*`, `/admin/*`
  round out the HTML surface.
- **Auth** — magic link (`POST /api/auth/magic-link` → email → `GET /verify`)
  issues a signed `mk_session` cookie (30 days). Device flow (`POST
  /api/auth/device-{start,poll,authorize}` plus the `GET /device` consent page and
  `GET /setup` runbook) is the Claude Code onboarding path and mints a user token
  on authorize. Per-user API tokens (`mk_usr_…`) and per-agent tokens (`mk_agt_…`)
  are argon2id-hashed and minted from `/settings/tokens` / `/settings/agents`.
- **Admin** — `is_admin` boolean on `users`, promoted via SQL. Admin-only
  surfaces: `markland_feature` (MCP), `markland_audit` (MCP), and `/admin/audit`
  (HTML).

## Layered architecture

```
web/       FastAPI routes, HTML templates, Starlette middleware
  ├─ app.py             create_app() — lifespan, middleware wiring, view routes
  ├─ principal_middleware.py   reads bearer, attaches request.state.principal
  ├─ rate_limit_middleware.py  token-bucket, per-principal / per-IP
  ├─ auth_routes.py, identity_routes.py   magic-link + per-user tokens
  ├─ routes_agents.py, api_grants.py      agents + grants (API + HTML)
  ├─ invite_routes.py, device_routes.py   invites + device flow
  ├─ presence_api.py, presence_gc.py      presence API + GC lifespan task
  └─ templates/         Jinja2 (dark-mode Markland tokens)

service/   Pure Python, no FastAPI imports. All business rules live here.
  ├─ auth.py, users.py, sessions.py, magic_link.py   identity + sessions
  ├─ agents.py                                       agent CRUD
  ├─ permissions.py                                  check_permission (§12.5)
  ├─ docs.py                                         doc CRUD, versioning, conflicts
  ├─ grants.py                                       grant / revoke / notify
  ├─ invites.py                                      invite create / accept
  ├─ device_flow.py                                  start / poll / authorize
  ├─ presence.py                                     set / clear / list / gc
  ├─ email.py, email_templates.py, email_dispatcher.py   Resend + Jinja + queue
  ├─ audit.py, metrics.py                            append-only log + JSONL funnel
  └─ rate_limit.py                                   token buckets

db.py      SQLite connection (WAL, foreign_keys=ON). init_db runs every
           idempotent schema migration inline. Also exposes row helpers
           (insert_document, upsert_grant, get_grant, insert_revision,
           prune_revisions, record_audit, …).

models.py  Frozen dataclasses (Document, Grant, Agent, Invite, …) + id prefixes.
```

**Middleware order** (outer → inner, as Starlette runs them): the current wiring
adds `PrincipalMiddleware` first and `RateLimitMiddleware` second; Starlette reverses
that so `RateLimitMiddleware` is actually outermost. `_resolve_principal_lazy()`
inside `rate_limit_middleware.py` re-resolves the bearer for `/mcp`-prefixed paths
so the rate limiter still sees the real principal. See `docs/FOLLOW-UPS.md` —
this is a known inconsistency; either swap the add-order or document the lazy
resolve as intentional.

## Core abstractions

### Principal (`service/auth.py`)

Frozen dataclass, five fields, used everywhere permissions are checked:

```python
@dataclass(frozen=True)
class Principal:
    principal_id: str              # usr_<hex> or agt_<hex>
    principal_type: Literal["user", "agent"]
    display_name: str | None
    is_admin: bool
    user_id: str | None = None     # owning user for agents; None for users/service
```

### Permission resolution (`service/permissions.py`)

`check_permission(conn, principal, doc_id, action)` — spec §12.5 order:
1. Owner (`documents.owner_id == principal.principal_id`) → allow.
2. Direct grant (`grants.principal_id == principal.principal_id`) → allow iff
   grant level covers action.
3. Agent inheritance — user-owned agent inherits `(doc, owner_id, 'user')` grant.
4. Public + `view` action → allow.
5. Otherwise raise `NotFound` (never `PermissionDenied` for non-owners —
   "deny-as-NotFound" hides existence of docs the caller can't see).

### Grant ops (`service/grants.py`)

- `grant(conn, *, base_url, principal, doc_id, target, level, dispatcher=None,
  email_client=None)` — owner-only; `target` is an email (→ user, created if
  needed) or an `agt_…` id (→ agent; user-owned agents email the owning user).
- `grant_by_principal_id(conn, *, doc_id, principal_id, level, ...)` — no
  permission check, no audit. Used internally by `accept_invite`.
- `revoke(...)`, `list_grants(...)`.

### Optimistic concurrency (`service/docs.py`)

- Every doc carries `version: int` (default 1).
- `update(conn, doc_id, principal, *, content, title, if_version: int)` is the
  only writer. `BEGIN IMMEDIATE` → SELECT current → if `version != if_version`
  raise `ConflictError(current_version, current_title, current_content)` →
  `insert_revision` pre-update snapshot → UPDATE with `version+1` →
  `prune_revisions(keep=50)`.
- MCP tool `markland_update` requires `if_version: int`; conflicts become
  `ToolError("conflict: …")` with structured `err.data`.
- HTTP: `GET /api/docs/{id}` emits `ETag: W/"<version>"`. `PATCH` requires
  `If-Match` (weak or strong); missing → 428, stale → 409 with full conflict
  body, success → 200 plus new ETag.

## Data model (`db.py::init_db`)

One line per table:

- `users` — `id`, `email` (unique), `display_name`, `is_admin`, `created_at`.
- `tokens` — argon2id-hashed API tokens for users (`mk_usr_…`) and agents
  (`mk_agt_…`), keyed by `(principal_type, principal_id)`.
- `waitlist` — retained pre-launch landing email capture.
- `agents` — `id` (`agt_…`), `owner_type` (user|service), `owner_id`,
  `display_name`, `revoked_at`.
- `documents` — `id`, `owner_id` (FK users), `version`, `title`, `content`,
  `share_token`, `is_public`, `is_featured`, timestamps.
- `grants` — `(doc_id, principal_id)` PK; `level` ∈ `{view, edit}`;
  `principal_type` discriminator for downstream joins.
- `invites` — argon2id-hashed `mk_inv_…` tokens, `uses_remaining`, optional
  `expires_at`, `revoked_at`.
- `device_authorizations` — device-flow state: `device_code`, `user_code`,
  status, `expires_at`, `consumed_at`, optional piggyback `invite_token`.
- `revisions` — pre-update snapshots capped at 50 per doc, index on
  `(doc_id, id DESC)`.
- `presence` — `(doc_id, principal_id)` PK; `status` ∈ `{reading, editing}`;
  `expires_at` (10-min TTL), indexed.
- `audit_log` — append-only: `principal_id`, `action`, `doc_id`, `metadata`
  (JSON), `created_at`. Indexes on `created_at DESC` and `doc_id`.

## Background tasks

All lifecycle-managed by the single unified FastAPI `lifespan` inside
`create_app` — start in order, stop in reverse:

- **EmailDispatcher** (`service/email_dispatcher.py`) — async queue + jittered
  exponential retry (1s / 3s / 10s, then drop). `enqueue(...)` is
  **synchronous** (`put_nowait`); the worker calls `EmailClient.send` via
  `asyncio.to_thread`. Exposed at `app.state.email_dispatcher`. A synchronous
  `_InlineDispatcher` shim keeps older `email_client=MagicMock()` tests working;
  see `docs/FOLLOW-UPS.md` for the dedup follow-up.
- **Presence GC** (`web/presence_gc.py`) — 60-second tick calling
  `presence.gc_expired`; exceptions swallowed so a bad DB call never kills the
  loop. Off by default; `run_app.py` flips it on for hosted deploys.
- **FastMCP session manager** — the mounted MCP sub-app has its own task group;
  `create_app` chains its `lifespan_context` inside the unified lifespan so
  `TestClient(app)` with-blocks drive start/stop.

## Deployment

- **Fly.io single process** — Dockerfile + `fly.toml`, one container running
  `scripts/start.sh`, which does `litestream restore` then `exec litestream
  replicate -- uvicorn markland.run_app:app`.
- **SQLite + Litestream → Cloudflare R2** — continuous replication of
  `/data/markland.db`; config in `litestream.yml`.
- **Sentry** — conditional init in `run_app.py` (only if `SENTRY_DSN` set);
  wiring runbook at `docs/runbooks/sentry-setup.md`.
- **Resend** — `service/email.py::EmailClient` wraps the Resend SDK; in-process
  `EmailDispatcher` is the only caller.
- **Logs** — `run_app.py` installs a JSON log formatter on the root logger;
  structured fields (`principal_id`, `doc_id`, `action`) are surfaced via
  `logger.info(..., extra={...})`. Metrics in `service/metrics.py` write JSON
  lines to stdout for Fly log scraping.
- **CI/CD** — `.github/workflows/test.yml` runs pytest on every push;
  `.github/workflows/deploy.yml` runs `flyctl deploy --remote-only
  --strategy immediate` on push to `main`. `--strategy immediate` is a
  workaround for a flyctl launch-group lookup bug — the default rolling
  strategy creates orphan sibling machines instead of updating in place.
  See `docs/plans/2026-04-29-fix-fly-deploy-launch-group.md`.

## How the 10 plans stacked

Each plan finds its feature at a predictable place in the tree; start here when
hunting for where to add something similar.

1. **Hosted infrastructure** (`docs/plans/2026-04-19-hosted-infra.md`) —
   `run_app.py` entrypoint, `create_app` mounts `/mcp` over streamable-http,
   Sentry conditional, `EmailClient` stub, Dockerfile, `fly.toml`,
   `litestream.yml`, CI workflows. An `AdminBearerMiddleware` (since deleted)
   was the placeholder auth.
2. **Users and tokens** — `users` + `tokens` tables, `service/users.py`,
   `service/auth.py` (Principal + argon2id + `mk_usr_…`),
   `service/sessions.py`, `service/magic_link.py`, `PrincipalMiddleware`,
   `/login`, `/verify`, `/settings/tokens`, `markland_whoami`. Replaced the
   admin-bearer gate.
3. **Doc ownership and grants** — `documents.owner_id`, `grants` table,
   `service/permissions.py::check_permission`, `service/docs.py`,
   `service/grants.py`, `markland_grant` / `markland_revoke` /
   `markland_list_grants`, `/api/docs/{id}/grants`, `/dashboard` "Shared with
   me".
4. **Agents** — `agents` table, `service/agents.py`, `mk_agt_…` tokens,
   agent-inheritance step 3 in `check_permission`, `grant()` accepts `agt_…`
   targets, `markland_list_my_agents`, `/api/agents`, `/settings/agents`,
   `scripts/create_service_agent.py`.
5. **Invite links** — `invites` table, `service/invites.py`,
   `markland_create_invite` / `markland_revoke_invite`, `/invite/{token}` page,
   `/api/invites/{token}/accept`, magic-link `return_to` threading for anon
   accept.
6. **Device flow** — `device_authorizations` table, `service/device_flow.py`,
   `/api/auth/device-{start,poll,authorize}`, `/device` consent, `/device/done`,
   `/setup` runbook, invite-token piggyback, per-IP rate limit on start.
7. **Email notifications** — `email_templates/` Jinja pairs (html + txt) per
   trigger, `service/email_templates.py`, `service/email_dispatcher.py`,
   lifespan-owned dispatcher, `grants.grant()` and `invite_routes._notify_creator`
   switched to templates.
8. **Conflict handling** — `documents.version`, `revisions` table,
   `docs.update(if_version=…)` in `BEGIN IMMEDIATE`, `ConflictError`,
   `markland_update` requires `if_version`, `GET /api/docs/{id}` emits ETag,
   `PATCH` requires `If-Match` → 428/409/200.
9. **Presence** — `presence` table with 10-min TTL, `service/presence.py`,
   `web/presence_gc.py` GC task, `markland_set_status` / `markland_clear_status`,
   `markland_get` embeds `active_principals`, `/api/docs/{id}/presence`,
   presence badge block in `document.html`.
10. **Launch polish** — `service/rate_limit.py` + `web/rate_limit_middleware.py`,
    `audit_log` table + `service/audit.py` wired into every mutating service
    call, `service/metrics.py` activation funnel, `/admin/audit` HTML +
    `markland_audit` MCP tool, `/quickstart`, session-aware `/explore`, JSON log
    formatter, hosted-first README, `tests/test_launch_e2e.py` (the spec §14
    launch gate).
