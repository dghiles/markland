# Phase 0 Dogfooding Checklist - Markland Launch Gate

Run through this list end-to-end before inviting a single beta user. Each item
maps to spec section 14 success criteria; if every box checks, Markland is launched.

## Environment

- [ ] `https://markland.dev/health` returns `{"status":"ok"}`.
- [ ] `https://markland.dev/mcp` returns 401 without auth, 200 with a valid user token.
- [ ] Sentry receives a test error from `run_app.py` (trigger once by raising from the `/health` handler temporarily, then revert).
- [ ] Resend sends a magic-link email to the operator's inbox within 10 seconds.
- [ ] Litestream shows at least one snapshot against `/data/markland.db` (`flyctl ssh console -C "litestream snapshots /data/markland.db"`).

## Success criteria (spec section 14)

A non-engineer friend ("Alex") can complete this script without instructions
beyond the one-page quickstart:

- [ ] **1. Sign up.** Alex visits `/`, clicks "Sign in", enters their email, clicks the magic link -> redirected to the dashboard.
- [ ] **2. Install.** Alex pastes `claude mcp add markland https://markland.dev/setup` into Claude Code, completes the device flow, sees `markland_*` tools.
- [ ] **3. Publish.** Alex asks "publish a markdown doc titled 'Hello' with some notes". Claude calls `markland_publish`. Share link returned.
- [ ] **4. Share.** Alex asks "share this with <operator's email>, edit access". Claude calls `markland_grant`. Operator receives an email notification.
- [ ] **5. Agent edits.** Operator's agent calls `markland_update` with the correct `if_version`. No silent data loss; operator sees the edit at the share URL within 5 seconds of the update returning.
- [ ] **6. Viewer works.** Alex sees the edit rendered at the share URL.

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
