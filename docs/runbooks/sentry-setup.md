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

**Goal:** catch Resend outages and persistent send rejections early.

1. Sentry -> Alerts -> Create Alert -> "Issues".
2. Name: `Markland email send failures`.
3. Conditions:
   - `exception.type:EmailSendError` (from `markland.service.email`)
   - Threshold: "more than 3 events in 5 minutes".
4. Action: email the operator.

The `EmailDispatcher` calls `sentry_sdk.capture_exception` when it drops an
email after exhausting its retry budget OR on first attempt when the failure
classifies as permanent (sandbox-mode rejection, validation error). Each event
carries these tags:

- `template` - which email template (e.g. `magic_link`, `user_grant`).
- `failure_kind` - `permanent` (won't ever succeed) or `transient` (gave up after retries).
- `attempts` - string-encoded attempt count (e.g. `"1"` for permanent, `"4"` for exhausted).
- `recipient_hash` - sha256-truncated recipient digest (12 hex chars). Use this
  to correlate "same recipient seeing repeated drops" without storing PII.

Filter or split the alert by `failure_kind:permanent` if you want to be paged
*only* on misconfiguration (e.g. a never-verified Resend domain) and not on
transient outages.

## Structured logging pairing

`run_app.py` installs a JSON log formatter that promotes `principal_id`,
`doc_id`, and `action` from `extra={...}` to top-level fields. The dispatcher
emits a drop log line with `extra={"action": {...}}` containing:

- `action.template`, `action.failure_kind`, `action.recipient_hash` (same shape
  as the Sentry tags above)
- `action.attempts` (int, not string - the JSON formatter preserves the type)
- `action.error_class` (e.g. `EmailSendError`)

Grep Fly logs by these fields rather than the message string - the message
intentionally uses `recipient_hash`, not the raw address, to avoid leaking
recipients into Sentry breadcrumbs (LoggingIntegration captures WARNING+ as
breadcrumbs by default).

## What this runbook does NOT cover

- Sentry performance monitoring / tracing dashboards (defer).
- Custom dashboards - use the default Issues list at Phase 0 scale.
- PagerDuty / on-call rotation - single-operator launch, email is enough.
