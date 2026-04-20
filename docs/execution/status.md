# Execution Status

## Plan 1 — Hosted Infrastructure

- **Tasks 1-10: COMPLETE** (2026-04-19).
- **Task 11: PARTIAL** (2026-04-20). Fly app `markland` created (org `personal`, region `iad`), 1 GB volume `data` mounted at `/data`, `MARKLAND_SESSION_SECRET` set, first machine `185191df264378` (shared-cpu-1x / 1 GB) deployed and serving `https://markland.fly.dev/` (custom domain `markland.dev` not yet owned; `MARKLAND_BASE_URL` pinned to fly.dev hostname in `fly.toml`). Still deferred: Resend signup + DNS (blocks magic-link email), R2 bucket + Litestream keys (no backups), `FLY_API_TOKEN` GitHub secret (CI auto-deploy).
- **Task 12: CODE-COMPLETE, NOT RUN** (2026-04-19). `scripts/hosted_smoke.sh` exists; needs a valid user API token to exercise, which needs magic-link email, which needs Resend — so blocked on Task 11 completion or on using the stdlib dev fallback that logs magic-link URLs to `flyctl logs`.

## Plan 2 — Users and Tokens

- **Tasks 1-14: COMPLETE** (2026-04-19).
- **Task 15: SKIPPED** — manual browser walkthrough; auto mode.
- `AdminBearerMiddleware` replaced by `PrincipalMiddleware`. Magic-link sign-in, session cookies, argon2id-hashed per-user API tokens, and the `markland_whoami` MCP tool are all live. Hosted deploy now requires `MARKLAND_SESSION_SECRET`; admin promotion is SQL-only (`UPDATE users SET is_admin = 1 WHERE email = ?`).

## Plan 3 — Doc Ownership and Grants

- **Tasks 1-11: COMPLETE** (2026-04-19).
- **Task 12: SKIPPED** — manual browser walkthrough; auto mode.
- Documents now carry `owner_id`; `grants` table records per-principal `view`/`edit` access. `check_permission` centralises the §12.5 resolution order (owner → direct grant → public+view → deny-as-NotFound). New MCP tools `markland_grant` / `markland_revoke` / `markland_list_grants`, HTTP API under `/api/docs/{id}/grants`, share dialog on the doc page, and `/dashboard` with "My documents" + "Shared with me" sections. Grant notifications sent best-effort via the Resend client (failures logged, not raised).
- Deferred: `if_version` semantics on `update_doc` → Plan 8. Agent-targeted grants delivered in Plan 4.
- Backfill script for pre-Plan-3 docs: `scripts/backfill_owners.py` (set `BACKFILL_OWNER_EMAIL`, run with `--dry-run` first).

## Plan 4 — Agents

- **Tasks 1-12: COMPLETE** (2026-04-19).
- Agents are first-class principals. New `agents` table (user-owned or service-owned). `service/agents.py` handles CRUD. `create_agent_token` mints `mk_agt_<urlsafe32>` tokens; `resolve_token` returns an agent Principal with `user_id` set to the agent's owning user (user-owned) or `None` (service-owned), `is_admin=False`.
- `check_permission` step 3 now live: user-owned agents inherit their owning user's grant on a doc (view or edit). Service-owned agents do not inherit.
- `grant()` accepts both email targets and `agt_…` ids; user-owned agent grants email the owning user (best-effort via Resend; failures never fail the grant). `service/grants.AgentGrantsNotSupported` is retained but unreachable.
- New MCP tool `markland_list_my_agents` (returns own agents for user tokens, self-only for agent tokens, empty for service agents).
- HTTP: `POST/GET/DELETE /api/agents`, `POST/DELETE /api/agents/{id}/tokens`; HTML page at `/settings/agents` with form-based create/revoke/mint-token (plaintext shown once via `?new_token=` redirect).
- Service-agent provisioning: operator helper `scripts/create_service_agent.py` (no web UI; plaintext printed once).
- `publish` now rejects service-owned agents with `PermissionError("invalid_argument: service_agent_cannot_publish")`.

Test suite after Plan 4: **253 passed**.

## Plan 5 — Invite Links

- **Tasks 1-12: COMPLETE** (2026-04-19).
- `invites` table created via `ensure_invites_schema` (called from `init_db`); argon2id-hashed tokens, indices on `token_hash` and `doc_id`.
- `service/invites.py` owns `create_invite`, `resolve_invite`, `accept_invite`, `revoke_invite`, `list_invites`. Invite URL format: `{base_url}/invite/<urlsafe-token>` (plaintext token in URL, stored as argon2id hash).
- `accept_invite` calls `grant_by_principal_id` internally, is idempotent (does not downgrade higher-or-equal existing grants but still decrements `uses_remaining`), returns the resulting `Grant` or `None`.
- MCP tools `markland_create_invite`, `markland_revoke_invite` added to `server.py`; owner-check inline.
- HTTP routes: `POST /api/docs/{id}/invites`, `DELETE /api/invites/{id}`, `GET /invite/{token}` (public HTML), `POST /api/invites/{token}/accept`.
- Anon invite flow: `/invite/<token>` → email form → `/api/auth/magic-link` (now accepts form-encoded `email` + `return_to`) → email with `/verify?token=…&return_to=/invite/<token>` → signed-in redirect → accept.
- Added `safe_return_to` helper + `return_to` threaded through `send_magic_link` → verify URL → `/verify` GET (redirects to whitelisted `return_to`, defaults to `/`).
- Creator notification email on accept is best-effort (`EmailSendError` and any other Exception swallowed, logged).
- Invite template: `src/markland/web/templates/invite.html` (signed-in + signed-out paths, single Jinja file).

Test suite: `uv run pytest tests/` → **311 passed** (up from 253; +58 tests).

Local verification command (run when ready):

```
MARKLAND_SESSION_SECRET=dev-local-secret \
MARKLAND_BASE_URL=http://localhost:8950 \
uv run python src/markland/run_app.py
```

## Plan 6 — Device Flow

- **Tasks 1-12: COMPLETE** (2026-04-19).
- **Task 13: SKIPPED** — manual Claude Code walkthrough; auto mode.
- One-paste onboarding via OAuth 2.0 device flow (RFC 8628). `device_authorizations` table tracks pending state; `service/device_flow.py` owns `start`/`poll`/`authorize` with 10-min TTL, 5s slow_down window, single-use tokens, and optional invite-token piggyback.
- HTTP surface: `POST /api/auth/device-{start,poll,authorize}` + `GET /device` consent page + `POST /device/confirm` + `GET /device/done` + `GET /setup` markdown runbook (threads `?invite=<token>`).
- Per-IP rate limit on `device-start`: 10 req/min sliding window, in-process; 429 + `retry_after` beyond.
- Device tokens follow the canonical pattern: `resolve_token` returns a user `Principal` minted via `service.auth.create_user_token` when the device poll lands in the authorized state.
- `service/sessions.py` gained four helpers the plan assumed from Plan 2 but that didn't exist: `get_session`, `make_session_cookie_value`, `make_csrf_token`, `verify_csrf_token`, plus a `SessionInfo` dataclass. Wrappers on top of existing `issue_session`/`read_session`.
- Invite piggyback is best-effort: a `None` return from `accept_invite` (revoked/expired invite) surfaces `invite_error` on `/device/done`; exceptions do too; authorization always lands.

Test suite: `uv run pytest tests/` → **373 passed** (up from 316; +57 tests).

## Plan 7 — Email Notifications

- **Tasks 1-12: COMPLETE** (2026-04-19).
- Jinja email templates per trigger (`magic_link`, `user_grant`, `user_grant_level_changed`, `agent_grant`, `invite_accepted`) each ship as `.html` + `.txt` under `src/markland/email_templates/`. `service/email_templates.py` renders to `{subject, html, text}`.
- `EmailClient.send(to, subject, html, text=None, metadata=None)` now forwards `text` (plaintext alongside HTML) and `metadata` (as Resend `tags`).
- `EmailDispatcher` (in-process async queue + jittered exponential retry: 1s/3s/10s then drop) lives in `src/markland/service/email_dispatcher.py`. `enqueue(...)` is **synchronous** (`put_nowait`); the worker pulls items off the queue and calls `EmailClient.send` via `asyncio.to_thread`. Lifecycle owned by FastAPI `lifespan` inside `create_app` so `TestClient(app)` entered as a context manager triggers start/stop; dispatcher exposed via `app.state.email_dispatcher`.
- `send_magic_link(dispatcher=..., ...)` stays sync; uses `email_templates.magic_link` + `dispatcher.enqueue`. Plan 2's sync route handler unchanged.
- `grants.grant()` renders `user_grant` on first-time, `user_grant_level_changed` on re-grant with a different level (same level = no email). Agent-target branch emails the agent's owning user for user-owned agents; service-owned agents get no email.
- `invite_routes._notify_creator` renders `invite_accepted` and enqueues via `app.state.email_dispatcher`.
- `/settings/notifications` stub page so the footer "Manage notifications" link resolves.
- **Back-compat shim:** `create_app` wraps `email_client` in a synchronous `_InlineDispatcher` when no `email_dispatcher` is supplied, so Plan 2–6 tests that only pass `email_client=MagicMock()` keep working. `grants.grant()` likewise still accepts `email_client=` and auto-wraps. Migration to pure dispatcher is a Plan 10 follow-up.

Test suite: `uv run pytest tests/` → **397 passed** (up from 373; +24 tests).

## Plan 8 — Conflict Handling

- **Tasks 1-7: COMPLETE** (2026-04-19).
- Documents now carry a monotonic integer `version` column (default 1, idempotent migration). `revisions` table added with per-doc pruning capped at 50 rows; indexed on `(doc_id, id DESC)`.
- `service.docs.update()` signature is now `update(conn, doc_id, principal, *, content, title, if_version: int)` — `if_version` is REQUIRED, returns a `Document`, and wraps its work in `BEGIN IMMEDIATE`. Raises `ConflictError(current_version, current_title, current_content)` on stale `if_version`; inserts a PRE-update revision snapshot on success; prunes to 50 rows.
- `service.docs.get()` supports two call forms: legacy `(conn, principal, doc_id, base_url)` returning a dict, and Plan 8 `(conn, doc_id, principal)` returning a `Document` with `version`. Dict form now includes `"version"`.
- `markland_update` MCP tool requires `if_version: int`; on `ConflictError` it raises `mcp.server.fastmcp.exceptions.ToolError("conflict: …")` with `err.data = {code, current_version, current_content, current_title}`. `markland_get` already returns `version` via `_doc_to_full`.
- HTTP: `GET /api/docs/{id}` sets `ETag: W/"<version>"`; `PATCH /api/docs/{id}` requires `If-Match` (weak or strong form); missing → `428 precondition_required`; mismatched → `409` with `{error, current_version, current_content, current_title}`.
- `tools/documents.py` now exposes thin shims (`publish_doc`, `get_doc`, `update_doc`, `list_docs`, `search_docs`, `share_doc`, `delete_doc`, `set_visibility_doc`, `feature_doc`) for Plan 8 tests and `scripts/smoke_test.py`; `update_doc` accepts `principal` (optional, defaults to admin-like stub) and required `if_version` kwarg.
- Four new test files: `test_service_docs_versioning.py` (9), `test_mcp_update_conflict.py` (4), `test_http_conflict.py` (5), `test_conflict_e2e.py` (2) — 20 new tests total.

Test suite: `uv run pytest tests/` → **417 passed** (up from 397; +20 tests).

## Plan 9 — Presence

- **Tasks 1-10: COMPLETE** (2026-04-19).
- Advisory presence table with `(doc_id, principal_id)` composite PK, 10-minute TTL, indexed on `expires_at`. Added inline to `init_db` alongside an `idx_presence_expires` index.
- `service/presence.py` exposes `set_status`, `clear_status`, `list_active`, `gc_expired` — all accept an optional `now: datetime | None` parameter for deterministic testing. `set_status` is an upsert that refreshes `expires_at`; `list_active` filters `expires_at > now` in-SQL as defense-in-depth; `gc_expired` is the hygiene job. `ActivePrincipal` dataclass carries the join result incl. `display_name` from `users`/`agents`.
- Background GC task registered on the FastAPI lifespan via `web/presence_gc.py` — `start(conn, interval_seconds=60.0)` returns `(task, stop_event)` and failures in each tick are logged and swallowed so a bad DB call never kills the loop. `create_app` gained `enable_presence_gc` / `gc_interval_seconds` kwargs; `run_app.py` enables it at 60 s. Default is off, so every pre-existing test still creates a silent no-op lifespan.
- MCP: new `markland_set_status(ctx, doc_id, status, note=None)` (gates on `check_permission(..., "view")`, returns `{doc_id, status, expires_at}`) and `markland_clear_status(ctx, doc_id)` (idempotent, returns `{ok: True}`). `markland_get` now embeds `active_principals: list[dict]` with `principal_id, principal_type, display_name, status, note, updated_at`.
- HTTP: `POST/DELETE/GET /api/docs/{id}/presence` in `web/presence_api.py`. Principal resolved from `request.state.principal` (test injector or `PrincipalMiddleware`) OR the `mk_session` cookie. `POST` rejects missing/invalid status with 400 (body parsed as a plain dict and validated manually, not pydantic-Literal which yields 422); returns 404 when the caller lacks view or the doc is missing.
- Web viewer: `/d/{share_token}` renders a `data-presence-badge` block (coloured dot, display name, status, optional note, coarse "N min ago") above the document content when `active_principals` is non-empty. No live updates — page refresh required.
- Six new test files: `test_presence_schema.py` (4), `test_presence_service.py` (15 incl. task-10 end-to-end TTL lifecycle), `test_presence_gc_task.py` (3), `test_presence_mcp.py` (6), `test_presence_api.py` (7), `test_presence_viewer_badge.py` (3) — 38 new tests.

Test suite: `uv run pytest tests/` → **455 passed** (up from 417; +38 tests).

## Plan 10 — Launch polish

- **Tasks 1-11, 13: COMPLETE** (2026-04-19).
- **Task 12: PARTIAL** — JSON log formatter + runbook files (`docs/runbooks/sentry-setup.md`, `docs/runbooks/phase-0-checklist.md`) are committed. The Phase 0 dogfooding walkthrough against a live Fly deploy is a HUMAN GATE; the code-side equivalent is `tests/test_launch_e2e.py`.
- Per-principal rate limiting (user 60/min, agent 120/min, anon 20/min, all overrideable) via `service/rate_limit.py` + `web/rate_limit_middleware.py` — token buckets with LRU eviction, 429 + `Retry-After` on denial.
- Audit log: new `audit_log` table; `service/audit.py` exposes `record()` (best-effort, never raises) + `list_recent()`. Wired into every mutating service call in `docs.py`, `grants.py`, `invites.py`. Admin-only `/admin/audit` HTML page + `markland_audit` MCP tool.
- Metrics emitter: `service/metrics.py` writes JSON lines to stdout; `emit_first_time()` dedups via in-process set. Six-event activation funnel (`signup`, `token_create`, `first_mcp_call`, `first_publish`, `first_grant`, `first_invite_accept`) wired across `users.py`, `auth.py`, `rate_limit_middleware.py`, `docs.py`, `grants.py`, `invites.py`.
- `/explore` is session-aware: anons see only public; authed users can toggle `?view=mine` for owned + granted docs.
- `/quickstart` five-step onboarding page added; linked from landing hero.
- `run_app.py` installs a JSON log formatter on the root logger; structured fields (`principal_id`, `doc_id`, `action`) flow through `extra={...}`.
- `README.md` rewritten hosted-first with MCP-tools table, rate-limit defaults, runbook links.
- `tests/test_launch_e2e.py` (the spec section 14 launch gate) passes: publish -> grant -> read -> update -> invite -> accept -> view, asserting `publish`, `grant`, `update`, `invite_create`, `invite_accept` audit actions are all present.

Test suite: `uv run pytest tests/` -> **500 passed** (up from 455; +45 tests across 11 new files).

### Human gates not executed

- Phase 0 dogfooding walkthrough against live Fly deploy (checklist in `docs/runbooks/phase-0-checklist.md`) — blocked on Resend so magic-link sign-in can complete.
- Sentry DSN + alert wiring (runbook in `docs/runbooks/sentry-setup.md`).
- Resend signup + DNS verification once `markland.dev` is owned; then `flyctl secrets set RESEND_API_KEY=...`.
- Cloudflare R2 bucket + S3 API token; then `flyctl secrets set LITESTREAM_*` + restart so Litestream starts backing up.
- `flyctl tokens create deploy` + GitHub `FLY_API_TOKEN` secret for CI auto-deploy.
- Buying / re-pointing `markland.dev` — see `docs/FOLLOW-UPS.md` for the re-allocation steps (dedicated IPv4, DNS, cert, flip `MARKLAND_BASE_URL`).

All plans (1-10) are code-complete and the app is live at `https://markland.fly.dev/`. Phase 1 invites can go out once Resend is wired and the Phase 0 walkthrough passes.
