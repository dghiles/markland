# Plans Index

Status index for every plan in this directory, reconciled against the
codebase, git history, and beads on **2026-07-05**. This is the
consolidation layer: plan files themselves routinely ship with their
task checkboxes unticked (agents execute, merge, and move on), so
**checkbox state inside a plan file is not evidence of completion** —
this index and the `docs/ROADMAP.md` Shipped log are authoritative.

Update this file whenever a plan changes state (new plan authored, plan
executed, plan superseded).

## Status summary

| Status | Count |
|---|---|
| Complete | 49 |
| Complete (diagnostic record — preserved, not executed) | 1 |
| Design notes (no tasks) | 3 |
| Partial | 1 |
| Ready to execute now | 1 |
| Trigger-gated | 1 |
| **Total** | **56** |

The two actionable rows are **mcp-phase-b-deprecation-removal** (its
30-day window opened 2026-05-31 — executable immediately) and the
deferred phases of **self-service-deletion**.

## Plans

| Plan | Status | Note |
|---|---|---|
| 2026-04-17-frontend-implementation.md | Complete | Shipped 2026-04-17; boxes unticked |
| 2026-04-18-dark-outlined-primary.md | Design notes | Status header: Shipped — current visual authority |
| 2026-04-18-io24-theming.md | Design notes | Superseded same-day by dark-outlined-primary |
| 2026-04-18-neubrutalism-theming.md | Design notes | Superseded same-day by IO24 pivot |
| 2026-04-19-agents.md | Complete | v1 Plan 4; 54/54 ticked |
| 2026-04-19-conflict-handling.md | Complete | v1 Plan 8; 31/31 ticked |
| 2026-04-19-device-flow.md | Complete | v1 Plan 6; 53/53 ticked |
| 2026-04-19-doc-ownership-and-grants.md | Complete | v1 Plan 3; boxes unticked |
| 2026-04-19-email-notifications.md | Complete | v1 Plan 7; 60/60 ticked |
| 2026-04-19-hosted-infra.md | Complete | v1 Plan 1; 6 unticked boxes are manual first-deploy gestures, done 2026-04-20 |
| 2026-04-19-invite-links.md | Complete | v1 Plan 5; boxes unticked |
| 2026-04-19-landing-waitlist-implementation.md | Complete | Boxes unticked |
| 2026-04-19-launch-polish.md | Complete | v1 Plan 10; boxes unticked |
| 2026-04-19-presence.md | Complete | v1 Plan 9; boxes unticked |
| 2026-04-19-users-and-tokens.md | Complete | v1 Plan 2; boxes unticked |
| 2026-04-20-read-only-viewer-save-to-account.md | Complete | Shipped 2026-04-20; self-review all done |
| 2026-04-20-seo-critical-high-fixes.md | Complete | All C/H items shipped or obsolete per 2026-05-03 audit close-out |
| 2026-04-24-setup-install-ux-fix.md | Complete | PRs #12/#13, 2026-04-28 |
| 2026-04-27-make-repo-public.md | Complete | Repo public 2026-04-28 |
| 2026-04-27-mcp-harness-and-baseline.md | Complete | MCP audit Plan 1 |
| 2026-04-27-mcp-axis-1-6-naming-docstrings.md | Complete | MCP audit Plan 2 |
| 2026-04-27-mcp-axis-2-7-return-shapes-pagination.md | Complete | MCP audit Plan 4 (PR #33) |
| 2026-04-27-mcp-axis-3-error-model.md | Complete | MCP audit Plan 3 |
| 2026-04-27-mcp-axis-4-8-granularity-idempotency.md | Complete | MCP audit Plan 5 (PR #36) |
| 2026-04-27-mcp-axis-5-new-tools.md | Complete | MCP audit Plan 6 (PR #38); laid `mcp-audit-axis-5-released` tag |
| 2026-04-27-mcp-phase-b-deprecation-removal.md | **Ready to execute now** | 30-day window opened **2026-05-31**. Removes 4 shims (`markland_set_visibility`, `markland_feature`, `markland_set_status`, `markland_clear_status`) + `principal=` alias; MCP surface 27→23. All 4 shims verified still present in `server.py` on 2026-07-05 |
| 2026-04-28-agent-token-leak-fix.md | Complete | PR #41, 2026-05-01 |
| 2026-04-28-dispatcher-observability.md | Complete | Verified in source 2026-07-05: `_classify` / `_recipient_hash` / Sentry capture live in `service/email_dispatcher.py`. Was missing from the roadmap Shipped log until this reconciliation |
| 2026-04-28-phase-0-dogfood.md | Complete | GO recorded 2026-05-29; audit log in-file; evidence at `docs/launch/phase-0-evidence-2026-05-29/` |
| 2026-04-28-resend-domain-verify.md | Complete | Done 2026-05-01; runbook state table says done |
| 2026-04-28-security-followups-batch.md | Complete | PR #49, all 6 items |
| 2026-04-28-sentry-dsn-alerts.md | Complete | Done 2026-05-04; smoke route removed |
| 2026-04-29-cutover-to-markland-dev.md | Complete | All 12 tasks, 2026-05-01; 58/58 ticked |
| 2026-04-29-fix-fly-deploy-launch-group.md | Diagnostic record | Not executed by design — `--strategy immediate` workaround holds. Reopen only if orphan machines return |
| 2026-04-29-signed-in-account-discovery.md | Complete | Shipped; finished PR body in-file |
| 2026-05-01-admin-metrics-mcp-tool.md | Complete | Shipped 2026-05-01 |
| 2026-05-01-mcp-audit-followup-a-security.md | Complete | PR #45 |
| 2026-05-01-mcp-audit-followup-b-error-model-completion.md | Complete | PR #46 |
| 2026-05-01-mcp-audit-followup-c-hygiene-polish.md | Complete | PR #47 |
| 2026-05-01-signed-in-banner-coverage-and-overflow.md | Complete | PRs #39/#40/#42 era; FOLLOW-UPS marks it fixed |
| 2026-05-01-umami-analytics.md | Complete | PRs #37 + #43 |
| 2026-05-01-worktree-guardrails.md | Complete | Hooks live; referenced by CLAUDE.md / AGENTS.md |
| 2026-05-03-admin-metrics-tool-usage-expansion.md | Complete | PR #53 |
| 2026-05-03-geo-search-readiness.md | Complete | PRs #54/#55/#56; in-file G1–G5 table all done |
| 2026-05-03-magic-link-single-use-enforcement.md | Complete | PR #59 |
| 2026-05-03-mcp-auth-discovery.md | Complete | PR #66 |
| 2026-05-04-claude-code-plugin-marketplace.md | Trigger-gated | Bead `markland-97r`. Fires at 50+ active MCP installs OR inbound marketplace request |
| 2026-05-04-formal-privacy-policy.md | Complete | Live 2026-05-04 |
| 2026-05-04-formal-terms-of-service.md | Complete | Live 2026-05-04 |
| 2026-05-04-install-onboarding-options-2-4.md | Complete | Shipped 2026-05-09 |
| 2026-05-04-mcp-oauth-probe-coverage.md | Complete | PR #68 |
| 2026-05-04-mcp-trailing-slash-redirect.md | Complete | PR #71 |
| 2026-05-04-self-service-deletion.md | **Partial** | Phase 1 shipped (Track E1, `80769b5`; 19/19 boxes ticked). Phases 2–3 (account soft-delete + purge cron) deferred until 25 organic signups or an external "no account delete" blocker flag. 78 boxes legitimately open |
| 2026-05-04-session-revocation-epoch.md | Complete | PR #70; bead `markland-bul` closed |
| 2026-05-04-token-id-prefix-o1-lookup.md | Complete | PR #69; bead `markland-9dm` closed. Follow-up `markland-brf` (legacy-fallback removal) comes due 2026-08-02 |
| 2026-05-29-pre-launch-cleanup.md | Complete | All 8 tracks landed 2026-05-29/30 (E2/E3 were no-ops — already shipped 2026-05-04). Track F output (Show HN draft) queued NOT POSTED pending the `markland-3sd` soak-window gate. Plan boxes 18/55 ticked — see convention note above |

## Specs

| Spec | Status | Downstream |
|---|---|---|
| 2026-04-17-frontend-design.md | Resolved | frontend-implementation shipped |
| 2026-04-18-landing-waitlist-design.md | Resolved | landing-waitlist-implementation shipped |
| 2026-04-19-multi-agent-auth-design.md | Resolved | users-and-tokens + agents shipped |
| 2026-04-19-read-only-viewer-save-to-account-design.md | Resolved | plan shipped 2026-04-20 |
| 2026-04-27-mcp-audit-design.md | In flight | 6 of 7 plan waves shipped; Phase B removal is the last open plan (window open) |
| 2026-05-03-monetization-strategy-design.md | Awaiting plan | Deliberately demoted until the F-gate soak check confirms the funnel converts |
| 2026-05-04-install-onboarding-options-2-4-design.md | Resolved | plan shipped 2026-05-09 |
| 2026-05-04-self-service-deletion-design.md | In flight | Phase 1 shipped; Phases 2–3 deferred (trigger above) |
