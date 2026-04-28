# Markland Roadmap

Living document. Strategic frame at the top; tactical lanes (Now / Next /
Later) are the working surface; "Shipped" at the bottom is the historical log
organized by track. Update on every meaningful state change. Tactical detail
that doesn't fit the lane summaries lives in `docs/FOLLOW-UPS.md`.

## Positioning

Markland is **a shared knowledge surface where humans and agents are equal editors.** It sits in the gap between two tools that don't fit agent-era collaboration:

- **Git** — too complicated and overpowered. Branches, merges, commits, and discipline make sense for engineering teams. They're overkill for casual collaboration and alien to agents.
- **Google Docs** — not agent-friendly. Cursors, comments, and suggest-mode are human-shaped. There's no structured surface an agent can write to as a first-class citizen.

Collaboration is no longer just human-to-human. It's also **machine-to-machine** and **human-to-machine**. Markland is built for that three-way model: your agents, a friend's agents, and fully automated agents all reading and writing the same knowledge via MCP — with no merge conflicts to resolve by hand and no "paste this into the doc" handoff.

### The wedge

The sharpest MVP framing is autonomy: **"your agent publishes without asking you."** That's the graspable, demo-able behavior. The bigger idea — shared state across many agents and their owners — is the reason it matters, and the direction v2+ expands into.

### Tagline

Current selection: **"Shared notes for you and your agents."** — collaboration-forward, works for readers who don't know what MCP is. Bench of A/B candidates: [tagline-candidates.md](tagline-candidates.md).

---

## Where we are (2026-04-27)

Code-complete on the v1 build (10 plans, 616 tests collected). Live deploy at
`markland.fly.dev`, CI auto-deploy on push to `main` working since v3.
Marketing surface up: landing + waitlist, `/alternatives` hub with five
competitors, save-to-Markland CTA, trust-floor stub pages. SEO foundation
shipped (meta/OG/JSON-LD, robots.txt, dynamic sitemap, security headers, GEO
paragraph) plus batch 1 of the post-audit action plan.

**Blocked on user-side work:** buying `markland.dev` (blocks Resend domain
verify → magic-link email → real sign-ins; blocks GSC sitemap submission;
blocks `301 → markland.dev` redirects).

---

## Now

Active or imminent. Items here have a plan or a clear next action.

- **MCP audit + test harness** — `docs/specs/2026-04-27-mcp-audit-design.md`. The 18-tool surface accreted across 10 plans rather than being designed as a coherent whole. Audit consolidates naming, return shapes, error model, granularity, pagination, idempotency; adds 5 missing tools (`markland_get_by_share_token`, `markland_list_invites`, `markland_explore`, `markland_fork`, `markland_revisions`); ships behind a 30-day deprecation window. New dual-layer test harness (direct + HTTP backends) + per-tool snapshot baselines back the audit and stay as fast feedback for future MCP work.
- **SEO action plan batch 2+** — remaining items from `docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md`. Critical leftovers: **C3** (HTML 404 page), **C4** (expand `/about /security /privacy /terms` to 250-300 words each — content, not code). High items beyond H2/H3/H5/H6 (already in batch 1).
- **Make repo public** — `docs/plans/2026-04-27-make-repo-public.md`. Three-phase plan (audit, history rewrite, publish + branch protection). Unblocks free GitHub Pro APIs Markland needs and provides marketing/credibility.
- **Buy `markland.dev` and cut over** — sequence in `docs/FOLLOW-UPS.md` Deploy/operations §1. Single user-side action with the largest cascade: unblocks Resend → real magic-link sign-ins, unblocks GSC, unblocks 301 redirects from fly.dev.
- **Install/onboarding flow simplification** — first-time CLI install today is six steps across two channels: CLI shows `user_code` → visit `/device` → email form → check inbox → click magic link → bounce back → enter code → confirm. Device-flow assumes you're already signed in, and magic-link is the sign-in primitive, so they stack. Tonight surfaced a redirect bug on top: `next=/device` doesn't survive the magic-link round-trip (lands on `/me/tokens` instead). Cheapest wins, in order of leverage: (1) fix `next=` redirect so post-sign-in lands on `/device` with code prefilled; (2) prefill `user_code` via `/device?code=…` (route already supports it — runbook needs to construct the link); (3) single-link install — CLI runbook generates one `/device?code=…` URL so sign-in + code-entry happen on the same page; (4) skip device flow for browser-first users — sign in, hit "Connect Claude Code", copy one-shot token from `/me/tokens` into `claude mcp add`. Worth a brainstorm pass before launch — right answer depends on whether the primary install audience is browser-first humans or CLI-first agents.

## Next

Queued. Most are post-domain-cutover.

- **Resend domain verify** + `flyctl secrets set RESEND_API_KEY=...`. Without this, magic-link sign-ins on the live deploy require pulling the URL from `flyctl logs`.
- **R2 bucket + Litestream keys.** App boots fine without them (`scripts/start.sh` falls back to plain uvicorn), but the SQLite volume is the only copy of data — one lost volume = full loss.
- **GSC sitemap submission** — deferred until canonical domain. Submitting under fly.dev burns the property on a host we plan to abandon. See `docs/FOLLOW-UPS.md` Deploy/operations §6.
- **CSRF on save routes** — `/d/{t}/fork`, `/d/{t}/bookmark` accept plain form/fetch with `SameSite=Lax`. First user-authored mutating POSTs in the app; ship before any real users.
- **Agent token query-string leak** — `routes_agents.py:224` redirects with the plaintext token in the URL. Replace with signed flash cookie. Audit `identity_routes.py` for the same pattern.
- **Other security follow-ups from FOLLOW-UPS.md** — `user_code` redirect escape, per-IP rate limit on `/device/confirm`, lock-after-N-failed-confirms, `grant_by_principal_id` defensive check, append-only audit enforcement, `/admin/audit` middleware widening.
- **Phase 0 dogfooding walkthrough** against live deploy — `docs/runbooks/phase-0-checklist.md`. Blocked on Resend.
- **Sentry DSN + alert wiring** — `docs/runbooks/sentry-setup.md`.

## Later

v2+ direction. No plans yet; this is the strategic horizon.

- **Real-time co-editing** — Plan 9 ships advisory presence (badges, no live updates). v2 grows toward CRDT / OT collaboration so two agents (or human + agent) can co-edit a doc with sub-second visibility into each other's changes.
- **Agent inbox / activity feed** — once multiple agents share a doc, the question becomes "what did everyone do today" — surface activity per doc and per principal.
- **Org / team accounts** — shared ownership beyond per-user grants. Today every doc has a single human owner.
- **Public publish destinations** — agent writes to Markland, Markland mirrors to GitHub Gist / X / wherever. Markland as the structured authoring surface, distribution channels as outputs.
- **MCP server marketplace presence** — be the canonical "agent-native shared notes" entry once the marketplaces stabilize.

---

## Shipped

Reverse-chronological by track. Each line is one shipped capability with the
date it landed.

### Hosted infrastructure + ops

- **2026-04-24** — `/admin/waitlist` JSON endpoint for signup signals.
- **2026-04-20** — CI auto-deploy working end-to-end (release v3 from `deploy.yml`).
- **2026-04-20** — First Fly.io deploy (`markland` app, iad, 1 GB volume, shared-cpu-1x). Live at `https://markland.fly.dev/`. `MARKLAND_SESSION_SECRET` set; Resend / R2 / Sentry deferred.
- **2026-04-19** — Plan 1 hosted-infra Tasks 1-10: Dockerfile, Fly config, Litestream config, GH Actions workflows, `run_app.py` entrypoint, Sentry-conditional init, Resend client wrapper.

### Build (v1 plans, all 2026-04-19 unless noted)

- **Plan 10 — Launch polish.** Per-principal token-bucket rate limiting (60/120/20 default per user/agent/anon). `audit_log` table + service + admin UI + `markland_audit` MCP tool. Activation funnel metrics (6 events to stdout JSON). Session-aware `/explore`. `/quickstart` page. JSON log formatter. Rewritten README. End-to-end launch-gate test.
- **Plan 9 — Presence.** `presence` table with 10-min TTL, `service/presence.py`, background GC task, MCP tools (`markland_set_status`, `markland_clear_status`, embedded `active_principals` on `markland_get`), HTTP API, viewer badge.
- **Plan 8 — Conflict handling.** Monotonic `version` column + `revisions` table (50-row prune), `ConflictError`, `BEGIN IMMEDIATE` in `update()`. MCP `if_version` required. HTTP `ETag: W/"<n>"` + `If-Match` (428 / 409 / 200).
- **Plan 7 — Email notifications.** Jinja templates per trigger. `EmailDispatcher` (in-process async queue, jittered retry 1s/3s/10s). `EmailClient` extended with `text=` + `metadata=`. `/settings/notifications` stub.
- **Plan 6 — Device flow.** RFC 8628 device flow at `/device` + `/setup` runbook. `device_authorizations` table, slow_down rate limit, per-IP limiter on `device-start`, invite-token piggyback.
- **Plan 5 — Invite links.** `invites` table (argon2id-hashed tokens), MCP tools `markland_create_invite` / `markland_revoke_invite`, HTTP routes including `GET /invite/{token}`, anon signup-via-magic-link flow with `safe_return_to` open-redirect guard.
- **Plan 4 — Agents.** `agents` table (user-owned + service-owned), `mk_agt_` tokens, agent-inheritance in `check_permission`, `markland_list_my_agents` tool, `/settings/agents` page, `scripts/create_service_agent.py`.
- **Plan 3 — Doc ownership and grants.** `documents.owner_id`, `grants` table, `check_permission` (§12.5 resolution: owner → grant → public+view → deny-as-NotFound). MCP `markland_grant` / `markland_revoke` / `markland_list_grants`. Dashboard with My/Shared sections.
- **Plan 2 — Users and tokens.** Magic-link auth, `mk_session` signed cookie, `mk_usr_` argon2id-hashed API tokens, `PrincipalMiddleware` (replaced `AdminBearerMiddleware`), `markland_whoami` tool.

### Marketing + UX surface

- **2026-04-20** — `/alternatives` hub + per-competitor comparison pages (markshare.to + 4 others).
- **2026-04-20** — Save-to-Markland CTA partial (desktop popover + mobile sheet); `/fork` and `/bookmark` routes with logged-out intent capture; `/resume` + magic-link hook for post-login action resume; signed pending-intent cookie via `URLSafeTimedSerializer`; `bookmarks` table + `forked_from_doc_id` column; "Saved" dashboard section; "Forked from" attribution on viewer.
- **2026-04-19** — Landing page + waitlist (`landing-waitlist-implementation.md`).
- **2026-04-18** — Frontend theming experiments (`dark-outlined-primary`, `io24-theming`, `neubrutalism-theming`).
- **2026-04-17** — Frontend implementation baseline.

### SEO foundation

- **2026-04-27** — SEO batch 1 from 2026-04-24 audit: `/alternatives` competitor cards as `<h2>` (C1), `Offer` on `SoftwareApplication` JSON-LD (C2), `BreadcrumbList` on per-competitor pages (H2), `logo` + `sameAs` on `Organization` (H3), additional H5/H6/M8 quick wins. Audit artifacts committed under `docs/audits/2026-04-24-seo-audit/`. HackMD coverage test added.
- **2026-04-22** — `_seo_meta.html` partial (canonical, OG, Twitter, JSON-LD); per-page meta descriptions; homepage retitle for MCP + Claude Code; GEO definitional paragraph for AI Overviews / LLM citation; expanded `/quickstart` (600+ words, H2 steps, templated host); trust-floor stub pages (`about/security/privacy/terms`) + footer; dynamic `/robots.txt` and `/sitemap.xml` (sourced from `COMPETITORS`); `SecurityHeadersMiddleware` (HSTS, CSP, XFO, XCTO, Referrer-Policy, Permissions-Policy, per-path `X-Robots-Tag`).
