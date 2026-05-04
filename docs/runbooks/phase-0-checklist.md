# Phase 0 Dogfooding Checklist - Markland Launch Gate

Run through this list end-to-end before inviting a single beta user. Each item
maps to spec section 14 success criteria; if every box checks, Markland is launched.

## Status as of 2026-05-03

- **Environment row**: 5/5 green.
- **Sentry alerts**: 4/4 configured (org `markland`, project `markland`).
- **§14 walkthrough**: partial — Eric (`hello@ericpaulsen.io`) ran steps 1–3
  end-to-end on 2026-05-02 via Claude Code, but stopped at view-only grant.
  Edit-grant + agent-update + viewer-sees-edit loop (steps 4–6) still
  unverified in production.
- **Rate-limit + audit + funnel verification**: still blocked. Audit log
  captured Eric's invite_accept / publish / grant correctly, but the agent
  `markland_update` path has no production evidence.

## Environment

- [x] `https://markland.dev/health` returns `{"status":"ok"}`.
- [x] `https://markland.dev/mcp` returns 401 without auth, 200 with a valid user token.
- [x] Sentry receives a test error (`MARKLAND-1` on 2026-05-03 via temporary
  `/__sentry_test` endpoint, env-var-gated; route removed after verification).
- [x] Resend sends a magic-link email to the operator's inbox within 10 seconds
  (verified 2026-05-03: email arrived same-minute as `POST /api/auth/magic-link`).
- [x] Litestream shows snapshots against `/data/markland.db` — verified 2026-05-03,
  multiple s3 generations including same-day snapshot.

## Sentry alerts (live as of 2026-05-03)

Org `markland`, project `markland`. All four route via `IssueOwners` →
`AllMembers` fallback to `daveyhiles@gmail.com`.

- [x] **Markland 5xx spike** — level >= error, environment=production,
  threshold > 5 events / 5 min.
- [x] **Markland ConflictError spike** — `exception.type == ConflictError`,
  threshold > 20 events / 15 min. (Spec said 10m; Sentry's issue-alert UI only
  exposes 1m/5m/15m/1h intervals — `15m` is the closest match. Tighten via
  metric alert later if 15m proves too loose.)
- [x] **Markland email send failures** — `exception.type == EmailSendError`,
  threshold > 3 events / 5 min.
- [x] **Markland email permanent failures** —
  `exception.type == EmailSendError` AND tag `failure_kind == permanent`,
  threshold >= 1 event / 5 min.

## Success criteria (spec section 14)

A non-engineer friend can complete this script without instructions beyond
the one-page quickstart:

- [x] **1. Sign up.** Eric accepted invite `inv_22c11ff00ac35828` at
  2026-05-02 19:50:34 UTC. (Used invite link rather than pure `/sign-in`
  flow, which is also a supported entry path. Magic-link UI was not
  exercised by Eric — open question whether to add a second person who
  starts from `/` to validate that route too.)
- [x] **2. Install.** Eric completed Claude Code device flow at 19:54:02 UTC;
  token `tok_b5b386...` issued, last used 21:06 UTC (70+ min of active use).
  `markland_*` tools clearly worked since publish in step 3 used them.
- [x] **3. Publish.** Eric published `417df037...` "Adcast — AI Video Ads for
  Performance Marketers" at 19:58:43 UTC via `markland_publish`. Share token
  `ovwr-0s90gBT-QLMq4WB8A`. Audit row #7 logged.
- [ ] **4. Share with edit access.** Eric granted `view` only on 2026-05-02
  19:59:46 UTC (audit row #8). Edit-level grant has no production evidence —
  needs a second pass (ask Eric to re-share with edit, or recruit another
  non-engineer to run steps 4–6 fresh).
- [ ] **5. Agent edits via `markland_update`.** No revisions exist for the
  Adcast doc (`version=1`, `created_at == updated_at`). Optimistic concurrency
  (`if_version`) and conflict handling have no production evidence.
- [ ] **6. Viewer sees edit within 5s.** Blocked on step 5.

## Rate limiting + audit verification

- [ ] Exceed 60/min on a user token via a tight loop -> receive 429 with `Retry-After`.
- [ ] Exceed 120/min on an agent token -> 429 with `Retry-After`.
- [ ] Exceed 20/min from an anon IP on `/explore` -> 429.
- [ ] After steps 1-6, `/admin/audit` shows rows for: `publish`, `grant`, `invite_create` (if invites were used), `invite_accept` (if used), `update`.

## Metrics funnel sanity

- [ ] `flyctl logs` shows one JSON line each for: `signup`, `token_create`, `first_mcp_call`, `first_publish`, `first_grant`, `first_invite_accept` after the end-to-end walkthrough.

## Go/no-go

If every box is checked, send Phase 1 invites. If anything fails, fix before
inviting anyone - the whole point of Phase 0 is that strangers never see bugs
Alex found.

## Rollback

The launch is reversible: every change lives behind the same Fly app. If
something catastrophic surfaces, `flyctl deploy --image <previous>` restores the
last known-good image; DB state replays from Litestream.
