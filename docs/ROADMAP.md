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

## Where we are (2026-05-03)

Live at **`https://markland.dev`**. Cutover complete 2026-05-01 (full
write-up in the Shipped log). Two days of polish + hardening since:
**MCP audit done through Plan 6** (axis 5 — five new tools shipped in PR
#38) plus a three-PR retrospective sweep (Plan A security, Plan B error
model, Plan C hygiene — PRs #45/#46/#47). **Security follow-ups batch
landed** (PR #49 — all 6 items: `user_code` redirect escape, per-IP rate
limit on `/device/confirm`, lock-after-N-fails, `grant_by_principal_id`
defensive check, append-only `audit_log` enforcement, `/admin/audit`
middleware widening). **Agent token query-string leak fixed** via signed
flash cookie (PR #41). **Umami Cloud analytics live** (PR #37 + CSP fix
#43). **SEO audit complete** — every C/H/M/L item from
`docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md` is done or obsolete
(C3 branded 404, C4 trust pages ≥250w, L3 AI-crawler blocklist, L4
`/admin/*` middleware dedupe, L5 post-cutover sitemap/GSC). **Fresh
strategic input:** GEO / AI-search readiness analysis at
`docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md` scored us 62/100 —
solid SSR + JSON-LD foundation, but the AI-crawler blocklist is currently
locking us out of Perplexity and (partially) Claude Web. Decision pending.

One MCP audit plan left — Plan 7 (Phase B deprecation/removal of 4
shims). Code-complete on the v1 build (10 plans, 864 tests).
`markland_admin_metrics` MCP tool live since 2026-05-01.

---

## Now

Active or imminent. Items here have a plan or a clear next action.

- **GEO / AI-search posture decision** — fresh analysis at `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md` (score 62/100). Concrete trade: today's robots.txt blocks `PerplexityBot`, `GPTBot`, and the deprecated `Claude-Web`/`anthropic-ai` UAs (modern `ClaudeBot` is allowed via wildcard). Doing nothing keeps us out of Perplexity and ChatGPT's offline index. Next action is a call: unblock named AI-search crawlers (Perplexity + GPTBot for ChatGPT Search) and ship `/llms.txt` + question-shaped H2/H3 + a small FAQ block, OR keep the block and accept the visibility cost. Plan-pending until the call is made.
- **MCP audit Plan 7 — Phase B deprecation/removal** — opens 30 days after the `mcp-audit-axis-5-released` tag (laid 2026-05-01, so window opens **2026-05-31**). Removes 4 deprecation shims: `markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status`. Plan: `docs/plans/2026-04-27-mcp-phase-b-deprecation-removal.md`.
- **Install/onboarding flow simplification** — Option 1 shipped (PR #12 + #13). Remaining: (2) prefill `user_code` via `/device?code=…` (route already supports it — runbook needs to construct the link); (3) single-link install — CLI runbook generates one `/device?code=…` URL so sign-in + code-entry happen on the same page; (4) skip device flow for browser-first users — sign in, hit "Connect Claude Code", copy one-shot token from `/me/tokens` into `claude mcp add`. Plan `docs/plans/2026-04-24-setup-install-ux-fix.md`. Worth a brainstorm pass on (2)-(4) before launch — right answer depends on whether the primary install audience is browser-first humans or CLI-first agents.

## Next

Queued. The big security/analytics/MCP-axis batches all landed; what's
left is launch-readiness polish.

- **Phase 0 dogfooding walkthrough** against live deploy — plan: `docs/plans/2026-04-28-phase-0-dogfood.md` (operationalizes `docs/runbooks/phase-0-checklist.md`). Resend verified, magic-link tested end-to-end — fully unblocked.
- **CSRF on save routes** — `/d/{t}/fork`, `/d/{t}/bookmark`, `DELETE /d/{t}/bookmark` accept plain form/fetch with `SameSite=Lax`. First user-authored mutating POSTs in the app; ship before any real users. No plan yet — small.
- **Sentry DSN + alert wiring** — plan: `docs/plans/2026-04-28-sentry-dsn-alerts.md`. Code path lives (`config.sentry_dsn` + conditional init in `run_app.py`); operator action is provisioning the DSN secret and wiring the three alerts (5xx spike, ConflictError spike, EmailSendError spike).
- **Soak-window analytics check** — beads `markland-fjd` (2 weeks post-launch): pull Umami stats + `/admin/metrics` 14d funnel snapshot + cross-reference signups vs Umami sessions, post a 1-message summary.

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

- **2026-05-03** — Rate-limiter memory bound: periodic stale-key GC on the hit-counter dicts so `/device/confirm`'s per-IP limiter can't grow without bound (PR #51, beads `markland-77d`).
- **2026-05-03** — `/admin/*` bearer-resolution dedupe (SEO audit L4): single helper across `/admin/waitlist` + `/admin/metrics` + drops a redundant `last_used_at` write per request (PR #50).
- **2026-05-01** — **Cutover to `markland.dev` complete.** All 12 tasks of `docs/plans/2026-04-29-cutover-to-markland-dev.md` shipped: dedicated Fly IPv4 (149.248.214.141) + IPv6 (2a09:8280:1::107:b98d:0), Porkbun-direct A/AAAA at apex (Porkbun API DNS edits), Fly TLS cert issued, `MARKLAND_BASE_URL` flipped to `https://markland.dev`, machine rolled in place via `flyctl deploy --strategy immediate`, `FlyDevRedirectMiddleware` 301s the old `markland.fly.dev` host (`076a3c2`), Resend DNS records (SPF/DKIM/DMARC) verified end-to-end via real magic-link sign-in from `notifications@markland.dev`, GSC domain property added with TXT verification + sitemap.xml submitted. Hosted_smoke green on cutover-relevant checks; a residual grep-on-escaped-JSON false-positive in the smoke whoami assertion is logged in FOLLOW-UPS for separate fix.
- **2026-05-01** — `markland_admin_metrics` MCP tool + `GET /admin/metrics` JSON endpoint. Aggregates signups, publishes, grants_created, invites_accepted from existing tables over a configurable window (default 7d, cap 30d) plus unwindowed waitlist_total. Admin-only via existing `is_admin` gate. `first_mcp_call` returned as null pending event-table follow-up.
- **2026-04-29** — Domain `markland.dev` registered at Porkbun (registry expires 2027-04-29, locked, contact privacy on, Porkbun nameservers active). Unblocks the cutover sequence.
- **2026-04-28** — Five "Next"-lane plans landed under `docs/plans/2026-04-28-*.md`: Resend domain verify, security follow-ups batch (6 items), Phase 0 dogfood walkthrough, Sentry DSN + alerts, agent token query-string leak fix.
- **2026-04-28** — Repo public on GitHub. Three-phase make-repo-public plan executed: audit, git-filter-repo identity scrub of full history, publish + branch protection ruleset on `main` (no direct push, no force push, signed reviews via PR). Unblocks GitHub Pro APIs and provides marketing/credibility.
- **2026-04-24** — `/admin/waitlist` JSON endpoint for signup signals.
- **2026-04-20** — CI auto-deploy working end-to-end (release v3 from `deploy.yml`).
- **2026-04-20** — First Fly.io deploy (`markland` app, iad, 1 GB volume, shared-cpu-1x). Live at `https://markland.fly.dev/`. `MARKLAND_SESSION_SECRET` set; Resend / R2 / Sentry deferred.
- **2026-04-19** — Plan 1 hosted-infra Tasks 1-10: Dockerfile, Fly config, Litestream config, GH Actions workflows, `run_app.py` entrypoint, Sentry-conditional init, Resend client wrapper.

### Build (v1 plans + post-launch security/MCP)

- **2026-05-03** — **Security follow-ups batch (PR #49)** — all 6 items from `docs/plans/2026-04-28-security-followups-batch.md`: `user_code` redirect escape via `urllib.parse.quote`, per-IP rate limit on `POST /device/confirm`, lock-after-N-failed-confirms on the device row, `grant_by_principal_id` defensive `principal_type` check, append-only `audit_log` enforcement (DB trigger), `/admin/audit` middleware coverage widened.
- **2026-05-01** — **Agent token query-string leak fixed (PR #41)** — `routes_agents.py:223-225` no longer redirects with `?new_token=…`. Now writes the token to a signed flash cookie (`URLSafeTimedSerializer`, mirrors `pending_intent.py`) read once on the next page render, then cleared.
- **2026-05-01** — **MCP audit Plan 6 — axis 5 (PR #38)** — five new tools: `markland_get_by_share_token`, `markland_list_invites`, `markland_explore`, `markland_fork`, `markland_revisions`. Layer B baselines + extended idempotency catalog.
- **2026-05-01** — **MCP audit Plan 5 — axis 4/8 (PR #36)** — granularity + idempotency.
- **2026-05-01** — **MCP audit Plan 4 — axis 2/7 (PR #33)** — return shapes + pagination.
- **2026-05-03** — **MCP retrospective Plans A/B/C** — three follow-ups from the audit's own retrospective: Plan A security hardening (PR #45), Plan B error-model completion (PR #46), Plan C hygiene (PR #47).

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

- **2026-05-01** — **Umami Cloud analytics live (PR #37 + CSP fix #43)** — env-gated drop-in (`UMAMI_WEBSITE_ID`, `UMAMI_SCRIPT_URL`), admin paths excluded, `<script defer>` only when configured, two-host topology (`cloud.umami.is` + `api-gateway.umami.dev`) allowed in `connect-src`. Privacy-first, cookieless, no PII; disclosed on `/security`.
- **2026-05-01** — Signed-in banner coverage on every authed page + overflow fix (PR #39); themed login/magic-link/verify pages (PR #40, #34); "Sign in" link in header for signed-out visitors (PR #42).
- **2026-04-28** — Install-flow fixes from 2026-04-24 dogfood run (PR #12 + #13). `?next=` thread-through (`/login` → magic-link → `/verify` preserves intended landing); url-encoded `next=` so a `user_code` containing `&` or `?` survives the `/device/confirm` bounce; "For humans" preamble on `/setup`; runbook fixed to use the `/install` Claude Code command rather than the unsupported `claude mcp add markland <url>`; `claude mcp add` references swept across docs; trust `X-Forwarded-Proto` so the `/mcp` redirect preserves https behind Fly's proxy.
- **2026-04-20** — `/alternatives` hub + per-competitor comparison pages (markshare.to + 4 others).
- **2026-04-20** — Save-to-Markland CTA partial (desktop popover + mobile sheet); `/fork` and `/bookmark` routes with logged-out intent capture; `/resume` + magic-link hook for post-login action resume; signed pending-intent cookie via `URLSafeTimedSerializer`; `bookmarks` table + `forked_from_doc_id` column; "Saved" dashboard section; "Forked from" attribution on viewer.
- **2026-04-19** — Landing page + waitlist (`landing-waitlist-implementation.md`).
- **2026-04-18** — Frontend theming experiments (`dark-outlined-primary`, `io24-theming`, `neubrutalism-theming`).
- **2026-04-17** — Frontend implementation baseline.

### SEO foundation

- **2026-05-03** — GEO / AI-search readiness analysis published at `docs/audits/2026-05-03-geo-analysis/GEO-ANALYSIS.md` (score 62/100). Live curl + static-HTML inspection of 7 sitemap URLs, platform-by-platform breakdown (Google AIO, ChatGPT Search, Perplexity, Claude Web, Bing Copilot), AI-crawler access matrix.
- **2026-05-03** — **SEO audit complete** — every C/H/M/L item from `docs/audits/2026-04-24-seo-audit/ACTION-PLAN.md` shipped or marked obsolete. Final landings: C3 branded HTML 404 (`tests/test_404_page.py`), C4 trust pages expanded ≥250 words with E-E-A-T signal (`48dc2df`), L3 robots.txt AI-crawler blocklist expanded (PR #48), L4 `/admin/*` middleware dedupe (PR #50), L5 post-cutover sitemap submitted + GSC verified.
- **2026-04-28** — Self-hosted Figtree, DM Mono, Newsreader (perf/SEO Task 10). Variable woff2 files served from `src/markland/web/assets/fonts/`, `@font-face` declarations in `base.html`, Newsreader italic axis widened to weight 600, `tests/test_self_hosted_fonts.py` verifies presence and font-face declarations.
- **2026-04-27** — SEO batch 1 from 2026-04-24 audit: `/alternatives` competitor cards as `<h2>` (C1), `Offer` on `SoftwareApplication` JSON-LD (C2), `BreadcrumbList` on per-competitor pages (H2), `logo` + `sameAs` on `Organization` (H3), additional H5/H6/M8 quick wins. Audit artifacts committed under `docs/audits/2026-04-24-seo-audit/`. HackMD coverage test added.
- **2026-04-22** — `_seo_meta.html` partial (canonical, OG, Twitter, JSON-LD); per-page meta descriptions; homepage retitle for MCP + Claude Code; GEO definitional paragraph for AI Overviews / LLM citation; expanded `/quickstart` (600+ words, H2 steps, templated host); trust-floor stub pages (`about/security/privacy/terms`) + footer; dynamic `/robots.txt` and `/sitemap.xml` (sourced from `COMPETITORS`); `SecurityHeadersMiddleware` (HSTS, CSP, XFO, XCTO, Referrer-Policy, Permissions-Policy, per-path `X-Robots-Tag`).
