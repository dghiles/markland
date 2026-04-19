# Sentry Alert Setup - Markland

Markland's Sentry DSN is wired in Plan 1 (hosted-infra). This runbook configures
the three alerts that matter at Phase 0 scale.

## Prerequisites

- `SENTRY_DSN` is set as a Fly secret (`flyctl secrets list` to verify).
- You are the admin of the Markland Sentry project.

## Alert 1 - 5xx spike

**Goal:** page when the hosted app starts throwing server errors.

1. Sentry -> Alerts -> Create Alert -> "Issues".
2. Name: `Markland 5xx spike`.
3. Conditions:
   - `event.type:error`
   - `level:error OR level:fatal`
   - `http.status_code:[500 TO 599]`
4. Filter: `environment:production`.
5. Action: email the operator (daveyhiles@gmail.com); if Slack is wired, post to `#markland-alerts`.
6. Threshold: "more than 5 events in 5 minutes".

## Alert 2 - ConflictError rate

**Goal:** detect unusual optimistic-concurrency contention - a signal of a
client-side retry loop gone wrong, or of real multi-agent editing finding a bug.

1. Sentry -> Alerts -> Create Alert -> "Issues".
2. Name: `Markland ConflictError spike`.
3. Conditions:
   - `exception.type:ConflictError` (matches `markland.service.docs.ConflictError`)
   - Threshold: "more than 20 events in 10 minutes".
4. Action: email only (not paging - this is a health signal, not an outage).

## Alert 3 - Email send failures

**Goal:** catch Resend outages early.

1. Sentry -> Alerts -> Create Alert -> "Issues".
2. Name: `Markland email send failures`.
3. Conditions:
   - `exception.type:EmailSendError` (from `markland.service.email`)
   - Threshold: "more than 3 events in 5 minutes".
4. Action: email the operator.

## Structured logging pairing

`run_app.py` installs a JSON log formatter that injects `principal_id`, `doc_id`,
and `action` fields whenever a caller uses `logger.info("msg", extra={...})`.
These fields appear in Fly's log stream verbatim. To surface them in Sentry
breadcrumbs, add `sentry_sdk.set_tag(...)` calls alongside structured log calls
at future milestones - not needed at launch.

## What this runbook does NOT cover

- Sentry performance monitoring / tracing dashboards (defer).
- Custom dashboards - use the default Issues list at Phase 0 scale.
- PagerDuty / on-call rotation - single-operator launch, email is enough.
