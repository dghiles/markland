# Gap Analysis — Plans 1-10 vs. Build

**Audit date:** 2026-04-19
**Test suite:** `uv run pytest tests/` → **505 passed** (log.md claims 500; actual count is 505 after plan-10 follow-up commits).

## Executive summary

The build is very close to the plans. All ten plans are code-complete in the automatable sense: every "Create:" file called out in a plan's File Structure now exists on disk, every planned MCP tool is registered in `server.py`, and every planned HTTP route module is mounted. The suite is green. The drift that does exist is mostly documented in `log.md`: canonical service signatures differ from the plans' prose (e.g. `docs_svc.publish` vs plan's `publish_doc`, `check_permission(conn, principal, doc_id, action)` vs plan's keyword form), pydantic/session helpers were added to support the plans, and several back-compat shims survive (`_InlineDispatcher`, dual-form `docs.get`, `email_client=` kwarg). The single unambiguous launch-blocking gap is Plan 1 Task 12's `scripts/hosted_smoke.sh` — a mandated artifact that was never written. Everything else that looks missing is either a documented deviation or a human gate (Fly deploy, Phase 0 walkthrough, Sentry DNS/Resend DNS).

---

## Plan 1 — Hosted Infrastructure

### Missing features
- **`scripts/hosted_smoke.sh` does not exist.** Plan Task 12 Step 1 explicitly creates this file; it is mandated as a post-deploy verification artifact. `log.md` marks Task 12 deferred as a "human gate," but the *script* (not its execution) is a code deliverable. Every other file Task 12 touches would be a no-op once the script existed.

### Signature drift
- `create_app(..., admin_token=...)` (plan literal) was later removed in Plan 2 Task 13 and is now `create_app(conn, *, mount_mcp, session_secret, email_client, base_url, email_dispatcher, enable_presence_gc, gc_interval_seconds)`. This is correct per-plan evolution, not a gap.
- `build_mcp(db_conn, base_url)` in the plan vs. current `build_mcp(db_conn, *, base_url, email_client=None)` — extended, not drifted.

### Skipped tasks
- Task 11 Steps 2-3 (`README.md` section "Running Hosted (Fly.io)" + read-back verification) — the plan snippet asked for a specific block; `README.md` was fully rewritten under Plan 10 Task 13 and does not contain the literal "Running Hosted (Fly.io)" section. The *spirit* of the step (link to the runbook) is covered by Plan 10's rewrite.
- Task 12 Steps 1-3 (write + chmod + post-deploy verification of `scripts/hosted_smoke.sh`) — all three unchecked; script is missing.

### Silent extensions
- `create_app` disables FastMCP's built-in DNS-rebinding protection and re-roots `streamable_http_path='/'`. Documented in `log.md`, needed for Fly proxy + to avoid `/mcp/mcp`. Not a gap, but worth noting for security review.
- `create_app` lifespan wrapper chaining the FastMCP sub-app's session manager — necessary but beyond the plan's literal snippet.

### Test coverage gaps
- None. `test_config.py` (3), `test_auth_middleware.py` (6 — since deleted in Plan 2 Task 13), `test_http_mcp.py` (3, rewritten in Plan 2 Task 13), `test_email_service.py` (3→5 under Plan 7), `test_sentry_init.py` (2) all present.

### Human gates (documented, not gaps)
- Task 11 Steps 4+ (`fly launch`, `flyctl secrets set`, DNS, R2 bucket, Resend signup).
- Task 12 Step 3 (execute the smoke script).

---

## Plan 2 — Users and Tokens

### Missing features
- None.

### Signature drift
- Plan Task 10 uses `pydantic.EmailStr` for `_MagicLinkRequest`; canonical implementation uses plain `str` + regex validation because `email-validator` is not installed. Documented in `log.md`.
- `send_magic_link(dispatcher=..., ...)` diverges from plan's `email_client=` — Plan 7 Task 6 superseded.

### Skipped tasks
- Task 15 (manual local browser walkthrough) — documented human gate in auto mode.

### Silent extensions
- `create_app` accepts `**_legacy_kwargs` for back-compat with Plan 1 tests that still pass `admin_token=""`. Not a gap; reasonable shim.
- `service/sessions.py` grew four helpers under Plan 6 (`get_session`, `make_session_cookie_value`, `make_csrf_token`, `verify_csrf_token`, `SessionInfo`) that Plan 2 did not introduce.

### Test coverage gaps
- None. Every `tests/test_*` file from the plan's File Structure exists and passes.

### Human gates
- Task 15 (manual browser walkthrough).

---

## Plan 3 — Doc Ownership and Grants

### Missing features
- None.

### Signature drift
- Plan calls `docs_svc.publish_doc`; canonical symbol is `docs_svc.publish` (keyword facade `publish_doc` was added in Plan 8 as a shim). This is a real API-shape drift from the plan's literal prose — tests in the plan would fail verbatim. Documented in `log.md`.
- `check_permission(conn, principal, doc_id, action)` is positional; plan used keyword form. Documented in `log.md`.
- Plan's `Principal("uid","user","uid")` 3-positional constructor would not match the Plan-2 5-field frozen dataclass. Tests use 5 kwargs. Documented.

### Skipped tasks
- Task 12 (manual browser walkthrough) — human gate.

### Silent extensions
- `tests/test_db_grants.py` was folded into `tests/test_db.py` instead of being a separate file. Functionally equivalent, but the plan's File Structure named a distinct file.
- `SELECT * FROM (... UNION ...) ORDER BY` wrap required for SQLite's UNION + ORDER BY — deviation from plan snippet.

### Test coverage gaps
- None.

### Human gates
- Task 12 (manual walkthrough).

---

## Plan 4 — Agents

### Missing features
- None.

### Signature drift
- Plan's `tests/test_routes_agents.py` imports `markland.service.auth.sign_session_cookie`; canonical helper is `service.sessions.issue_session`. Tests were adapted.
- `build_agents_router` returns `(api_router, html_router)` rather than a single router (prefix splitting). Documented.
- Plan 3's `AgentGrantsNotSupported` retained but unreachable (Plan 4 supersedes).

### Skipped tasks
- None beyond Plan-3 leftovers.

### Silent extensions
- `_maybe_send_agent_grant_email` catches a broad `Exception` (not only `EmailSendError`) so MagicMock-raised `RuntimeError` in tests never fails the grant. Defensive; intentional.

### Test coverage gaps
- None.

---

## Plan 5 — Invite Links

### Missing features
- None.

### Signature drift
- Plan's `resolve_invite`/`_row_to_invite` used `sqlite3.Row` key-access; canonical tuple indexing because the project's connection does not set `row_factory`. Project-wide convention; documented.
- Plan imported `get_grant` from `service.grants`; canonical is `markland.db`. Adapted.
- Plan's tests used `mcp.tool_functions` and `/api/_test/login` — neither exists. Adapted via `mcp.markland_handlers` + direct `issue_session` minting.
- Plan's `accept_invite` snippet assumed `grant_by_principal_id` returns a `Grant`; canonical returns `None`. Adapted.
- `POST /api/auth/magic-link` accepts JSON **and** form-encoded bodies — silent extension of Plan 2 contract, needed for invite HTML form.
- `GET /verify` now 303-redirects when `return_to` is set — extension of Plan 2.

### Skipped tasks
- None.

### Silent extensions
- Invite tokens now prefixed `mk_inv_` (Plan 5 code-review follow-up, documented in `log.md`). Plan did not require a prefix.

### Test coverage gaps
- None.

---

## Plan 6 — Device Flow

### Missing features
- None.

### Signature drift
- Plan-literal fixtures use `MARKLAND_ADMIN_TOKEN` — Plan 2 replaced it. Fixtures set `MARKLAND_SESSION_SECRET` instead.
- Plan's `auth_service.create_user(conn, user_id=..., email=..., display_name=...)` — canonical `service.users.create_user` is `(conn, *, email, display_name)` and auto-generates `user_id`. Adapted.
- Plan's `docs_service.publish_doc(..., owner_id=...)` — canonical `publish` takes `principal`. Tests seed via `db.insert_document` instead.
- Pydantic body models hoisted to module scope (nested `BaseModel` caused FastAPI to mis-route bodies).

### Skipped tasks
- Task 13 (manual Claude Code walkthrough) — human gate.

### Silent extensions
- `service/sessions.py` helpers added here rather than in Plan 2 (as plan assumed). Documented.
- Invite-piggyback semantics: `None` from `accept_invite` surfaces `invite_error`, not silent success. Unit test added to pin new behaviour (`test_authorize_invite_none_return_marks_error_but_still_ok`).

### Test coverage gaps
- None.

### Human gates
- Task 13 (manual CLI walkthrough).

---

## Plan 7 — Email Notifications

### Missing features
- None.

### Signature drift
- `grants.grant(conn, *, base_url, principal, doc_id, target, level, dispatcher=None, email_client=None)` — the `email_client=` kwarg is a back-compat shim not in the plan. Same pattern in `create_app`. Documented in `log.md` as intentional; Plan 10 follow-ups call for deletion.
- `send_magic_link(dispatcher, email, secret, base_url, return_to, expires_in_minutes)` — drops `email_client=` entirely. Plan 2's sig changed here.

### Skipped tasks
- Task 5 Step 3 (local-boot verification) — auto mode, no user.

### Silent extensions
- `_InlineDispatcher` back-compat shim in both `web/app.py` (line ~80) and `service/grants.py` (line ~264). Two copies; Plan 10 follow-up flags this.
- Two invite end-to-end tests (`test_invite_signup_flow.py`, `test_invite_smoke.py`) added `html.unescape(...)` because Jinja now autoescapes `&` in the magic-link URL — silent behaviour change.

### Test coverage gaps
- The plan's Task 4 retry test with real delays lives in `test_email_integration.py` (2 tests) rather than `test_email_dispatcher.py`. Both files exist; coverage fine.

### Human gates
- Task 5 Step 3 (manual local boot).

---

## Plan 8 — Conflict Handling

### Missing features
- None.

### Signature drift
- `service.docs.get()` has **dual signature** — legacy `(conn, principal, doc_id, base_url)` returning dict, and Plan 8 `(conn, doc_id, principal)` returning `Document`. Plan prescribed a hard replace; dual form preserved Plan-3 callers. Documented in `log.md`.
- `service.docs.update()` is `(conn, doc_id, principal, *, content, title, if_version)` — plan matches but the "canonical API" memo's `update_doc(conn, *, principal, doc_id, …)` keyword form is only exposed via the `tools.documents.update_doc` shim. Two call shapes coexist.
- `update_doc` shim accepts optional `principal` (defaults to admin-like stub) so `scripts/smoke_test.py` keeps working — extension for a non-auth context.

### Skipped tasks
- None.

### Silent extensions
- `tools/documents.py` was effectively empty before Plan 8 and was repopulated with a full set of thin shims (`publish_doc`, `get_doc`, `update_doc`, `list_docs`, `search_docs`, `share_doc`, `delete_doc`, `set_visibility_doc`, `feature_doc`) to satisfy `scripts/smoke_test.py` and plan tests. `log.md` notes this.
- `_update` in `server.py` propagates conflict as dict; the `@mcp.tool()` wrapper inspects and raises `ToolError`. Composable for handler tests.

### Test coverage gaps
- None. All four new test files exist.

---

## Plan 9 — Presence

### Missing features
- None.

### Signature drift
- Plan's `sqlite3.Row` key-access replaced with positional tuple indexing (project convention).
- Plan's pydantic `Literal` 422 replaced with manual dict validation → 400, matching the plan's asserted status code (the plan's own snippet would have produced 422 — this is a *correction*, not drift).
- Plan's Task 6 `require_principal()` shim + `markland.tools.auth` module do not exist; existing `_require_principal(ctx)` in `server.py` reused.
- Plan's Task 7 proposed rewriting `service.docs.get` to return a dict with `active_principals`; canonical `_get` in `server.py` adds `active_principals` to the dict returned by the dual-form `docs_svc.get(...)` — preserves Plan 8.

### Skipped tasks
- None.

### Silent extensions
- Task 5's unified lifespan folds GC into existing dispatcher/MCP lifespan rather than replacing the lifespan body. Correct and necessary.

### Test coverage gaps
- Plan 9 follow-up in `log.md` notes two tests that were NOT added and should be: (a) non-viewer `GET /api/docs/{id}/presence` returns 404; (b) share-token holder viewer behaviour. These are the only two real test gaps in the whole audit. Non-blocking for launch but worth addressing.

---

## Plan 10 — Launch Polish

### Missing features
- None in code. Task 12 Phase 0 live walkthrough is a human gate.

### Signature drift
- Plan's fixtures reference `markland.config.reset_config` and `create_app(..., admin_token="")`; neither matches canonical. Tests adapted.
- Plan's tests reference `create_user` from `markland.service.auth`; actual location is `markland.service.users`. Returns `User` dataclass, not id. Adapted.
- Plan's tests reference `build_mcp_tools` (plain-function registry); actual is `mcp.markland_handlers` on the FastMCP instance. Adapted.
- Plan's invite tests assume an `invite_tokens` table; invites actually store the hashed token inline on `invites`. Adapted.
- Plan's launch-gate test expected `>=7` audit rows; actual flow emits 5 (grant_by_principal_id internally called by accept_invite does not emit). Test asserts `>=5`. Documented in `log.md`.

### Skipped tasks
- Task 12 Phase 0 dogfooding walkthrough — human gate against live deploy.

### Silent extensions
- `/admin/audit` resolves bearer tokens inline (duplicates `PrincipalMiddleware` logic) because middleware only gates `/mcp` prefix. Documented as Plan 10 follow-up.
- `RateLimitMiddleware` is outermost due to Starlette reverse-add order; `_resolve_principal_lazy()` duplicates `resolve_token`. Plan 10 follow-up.
- `datetime.utcnow()` deprecation warnings in `web/app.py`, `service/presence.py`, and `test_presence_viewer_badge.py`. Cosmetic; noted in follow-ups.

### Test coverage gaps
- Integration test for real `EmailDispatcher` lifespan start/stop (currently bypassed by `_InlineDispatcher` shim in fixtures) — flagged as Plan 7 follow-up.

### Human gates
- Phase 0 walkthrough, Sentry DSN, Resend DNS verification, `flyctl deploy`, R2 bucket — all documented in `docs/runbooks/`.

---

## Launch-blocking gaps

These MUST be fixed before the Fly deploy can be declared clean. Cosmetic follow-ups (`datetime.utcnow` deprecation, shim consolidation, middleware reordering) are out of scope here; they are already logged at the bottom of `log.md`.

1. **`scripts/hosted_smoke.sh` does not exist.** Plan 1 Task 12 Steps 1-2 are unchecked. This is a required artifact for verifying the deploy end-to-end (`/health`, `/mcp` 401 unauthed, `/mcp` 200 authed, `/` 200). Without it, the Phase 0 checklist has no repeatable post-deploy verifier. **Action:** write the script per the plan's Step 1 snippet, `chmod +x`, commit. Estimated effort: 10 minutes.

2. **`docs/runbooks/first-deploy.md` references `MARKLAND_ADMIN_TOKEN` in sections 3-7** — the token was removed in Plan 2 Task 13. The runbook still says "Generate an admin token" and sets it as a Fly secret, but `config.admin_token` and the `AdminBearerMiddleware` no longer exist in code. The runbook already acknowledges this (TODOs at the top reference "missing from `.env.example`"), but the `flyctl secrets set` block will prescribe a secret that does nothing in the app. **Action:** update the runbook to drop `MARKLAND_ADMIN_TOKEN` secret setting and replace with the admin-promotion SQL (`UPDATE users SET is_admin=1 WHERE email=?`) that `status.md` already describes. Estimated effort: 15 minutes.

No other launch-blocking gaps. The suite is green (505 passing), all planned MCP tools are registered, all planned HTTP routes are mounted, and all human gates are explicitly flagged.
