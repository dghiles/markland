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
  1 GB volume, shared-cpu-1x machine. Live at `https://markland.fly.dev/`.
  `MARKLAND_SESSION_SECRET` set. Custom domain `markland.dev` and Resend /
  R2 secrets deferred (see `docs/execution/status.md`).

### Human gates remaining
- Buy `markland.dev`, re-allocate dedicated IPv4, point Cloudflare DNS, cert, flip `MARKLAND_BASE_URL`.
- Resend signup + DNS verification (currently blocks magic-link email).
- R2 bucket + Litestream keys (currently no backups).
- CI deploy token (`flyctl tokens create deploy` → `FLY_API_TOKEN` GitHub secret).
- Claude Code device-flow walkthrough.
- Phase 0 dogfooding (see `docs/runbooks/phase-0-checklist.md`).
- Sentry wiring (see `docs/runbooks/sentry-setup.md`).
