# Changelog

All notable changes to Markland are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — Unreleased
### Hosted multi-agent launch

v1 turns Markland from a single-user local stdio tool into a hosted service
where humans and agents can both publish, grant, edit, and read the same
markdown docs. Ten implementation plans landed on top of each other to deliver
the auth, sharing, conflict handling, presence, email, and operational polish
needed for the spec §14 launch gate (`tests/test_launch_e2e.py`) to pass.

### Added
- Hosted Fly.io deployment, Litestream backups to R2.
- Magic-link auth, per-user API tokens (Argon2id, `mk_usr_` prefix).
- User-owned and service-owned agents with `mk_agt_` tokens.
- Share via email, agent id, or invite link (single-use or multi-use).
- Claude Code device flow onboarding at `/setup`.
- Optimistic concurrency (version + ETag/If-Match; last-50 revisions per doc).
- Advisory presence badges on shared doc pages.
- Transactional email via Resend with in-process dispatcher.
- Per-principal rate limiting (token bucket).
- Append-only audit log + admin UI.
- Activation funnel metrics (JSON stdout).

### Known follow-ups

See [`docs/FOLLOW-UPS.md`](docs/FOLLOW-UPS.md) for the consolidated list of
security, correctness, test-coverage, and documentation items identified during
per-plan reviews. None block v1; all are first-sprint-after-launch candidates.

### Deployed
- First Fly.io deploy on 2026-04-20 — app `markland` (org `personal`, iad),
  1 GB volume, shared-cpu-1x machine. Initially live at
  `https://markland.fly.dev/`. `MARKLAND_SESSION_SECRET` set.
- Cutover to `https://markland.dev` on 2026-05-01 — dedicated Fly IPv4 +
  IPv6, Porkbun-direct A/AAAA at apex, Fly TLS cert issued,
  `MARKLAND_BASE_URL` flipped, `FlyDevRedirectMiddleware` 301s the old
  fly.dev origin, Resend domain verified end-to-end (real magic-link
  sign-ins working from `notifications@markland.dev`), Google Search
  Console domain property added + sitemap submitted. R2 + Litestream
  backups already in place (2026-04-28).
  Plan: `docs/plans/2026-04-29-cutover-to-markland-dev.md`.
- Sentry instrumentation live on 2026-05-03 — `SENTRY_DSN` set as Fly secret,
  Sentry SDK initialized in `run_app.py`, four issue-alert rules configured
  (5xx spike, ConflictError spike, EmailSendError outage, permanent
  EmailSendError) routing to `daveyhiles@gmail.com` via `IssueOwners` ->
  `AllMembers` fallback. Org/project: `markland`/`markland`. Test error
  `MARKLAND-1` confirmed receipt end-to-end. Phase 0 environment row 5/5
  green; only remaining Phase 0 gate is the §14 Alex walkthrough.
- MCP install OAuth-discovery surface landed on 2026-05-03 / 2026-05-04
  (markland-2yj PR #66, markland-6o6 PR #68). MCP clients (Claude Code SDK)
  auto-probe RFC 9728 / RFC 7591 / OIDC paths on every connection; the
  styled HTML 404 was crashing their JSON parsers and preventing
  `initialize` from completing. Fix: `WWW-Authenticate: Bearer` header on
  401 + JSON 404 at every observed probe path
  (`/.well-known/oauth-protected-resource[/mcp]`,
  `/.well-known/oauth-authorization-server[/mcp]`,
  `/.well-known/openid-configuration[/mcp]`, `GET/POST /register`).
  `register_well_known_routes` registrar in
  `src/markland/web/well_known_routes.py`. End-to-end smoke test verified
  with a real Claude Code install (27 tools loaded). Quickstart doc
  republished with `--scope user` + trailing-slash URL form so future
  users skip both the project-scope gotcha and the 307-redirect tax.
  Docs/runbook updated: `docs/runbooks/admin-operations.md` § "MCP install
  troubleshooting" + § "Republishing the live Quickstart doc".
  Open follow-up: markland-dfj (server-side fix to accept `/mcp` without
  redirect to `/mcp/`).
- MCP `/mcp` 307 redirect eliminated on 2026-05-04 (markland-dfj PR #71).
  Authenticated `POST /mcp` (no trailing slash) was 307-redirecting to
  `/mcp/` via Starlette's mount semantics; in a real Claude Code session
  this compounded to ~18s of cold-connect latency. Fix: explicit ASGI
  route at `/mcp` (registered BEFORE the Starlette mount in router order)
  delegates to the same FastMCP sub-app with `scope["path"]` rewritten
  to `/`. The route handler is wrapped in a `_McpNoSlashASGI` class with
  `__call__` so Starlette treats it as raw ASGI rather than a
  request-response handler. PrincipalMiddleware unchanged. Two stale
  redirect-pinning tests in `tests/test_proxy_headers.py` removed.
  Production-verified: `POST /mcp` returns HTTP/2 200 `text/event-stream`
  with `mcp-session-id`, no `Location:` header.

### Human gates remaining
- Phase 0 §14 dogfooding walkthrough — recruit a non-engineer friend ("Alex")
  with a Claude Code install to run signup -> install MCP -> publish -> share
  -> agent-edit -> viewer-sees-edit (see `docs/runbooks/phase-0-checklist.md`).
  Rate-limit + audit + funnel verification depend on this happening.
