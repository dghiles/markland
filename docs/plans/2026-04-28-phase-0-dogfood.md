# Phase 0 Dogfooding Walkthrough Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to walk this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **This is an OPS plan, not a TDD code plan** — tasks are "run command, observe expected output, mark pass/fail," not "write failing test, implement, pass." All evidence is captured to `phase-0-evidence/<step>.log` so the go/no-go gate has artifacts to point at.

**Goal:** Operationalize `docs/runbooks/phase-0-checklist.md` against the live `markland.fly.dev` deploy so a single operator can run the entire success-criteria walkthrough end-to-end, capture evidence, and gate the launch on the result.

**Architecture:** A two-actor walkthrough. **Operator** (you, `daveyhiles@gmail.com`, must be admin) drives most checks from a laptop terminal. **Alex** is a real human friend who runs Claude Code on a separate machine and follows the public quickstart. Each task captures stdout/log evidence under `phase-0-evidence/` so the go/no-go gate at the end is a literal directory listing, not a vibe.

**Tech Stack:** Fly.io (`flyctl`), curl, jq, SQLite (via `flyctl ssh console`), Resend (magic-link email), Sentry (optional), Litestream (R2), the deployed Markland app at `https://markland.fly.dev`, and one separate Claude Code install acting as Alex's MCP client.

**Hard dependencies (block-the-walkthrough secrets/state):**
- `RESEND_API_KEY` set as a Fly secret (Unit 1 / `docs/runbooks/first-deploy.md` §4). Magic-link delivery in Task 1 and Task 5 depends on it. If unset, the dev-fallback in `flyctl logs` shows the link but Task 1.5 (real email arrival) **fails** and the launch is blocked.
- `SENTRY_DSN` set as a Fly secret (Unit 4 / `docs/runbooks/sentry-setup.md`). Task 1.4 (test error appears in Sentry) depends on it. If unset, Task 1.4 is **explicitly skipped and recorded as `SKIP: SENTRY_DSN unset`** rather than failed — Sentry is optional per `fly.toml`/`config.py` defaults.
- `LITESTREAM_*` secrets set (Unit 1). Task 1.5b depends on Litestream actually running.
- The operator user row in `users` has `is_admin = 1`. `/admin/audit` returns 403 otherwise. Task 4 (audit verification) depends on it.
- An existing valid user-token for the operator (`mk_usr_...`) and a separate user account ("Alex") with their own `mk_usr_...` token. Both are minted via the device flow during Tasks 1 and 2.

**Inputs the operator must have on hand before starting:**
- `flyctl` authenticated as the app owner (`flyctl auth whoami` = the org owner).
- An admin token for the operator account: `flyctl ssh console -C "sqlite3 /data/markland.db 'UPDATE users SET is_admin=1 WHERE email=\"<operator-email>\";'"` if not already.
- Two inboxes: operator's email and Alex's email (real human or a second mailbox you own).
- A separate machine (or VM) with `claude` (Claude Code) installed for Alex's MCP client.

---

## File Structure

This plan only **creates** evidence files; it does not modify source.

- Create (during execution, gitignored): `phase-0-evidence/00-env.log` … `phase-0-evidence/07-rollback.log` (one log file per top-level task in this plan, captured via `tee`).
- Read-only: `docs/runbooks/phase-0-checklist.md` (the source-of-truth this plan operationalizes).
- Read-only: `docs/runbooks/first-deploy.md` (cross-reference for secret names).
- Read-only: `docs/runbooks/sentry-setup.md` (cross-reference for Sentry verification).

---

## Task 0: Pre-flight setup

**Files:**
- Create: `phase-0-evidence/` (directory; will be added to `.gitignore` if not already)
- Create: `phase-0-evidence/00-env.log`

- [ ] **Step 0.1: Create the evidence directory**

```bash
mkdir -p phase-0-evidence
```

Expected: no output, exit 0. If the directory already exists, that is fine.

- [ ] **Step 0.2: Confirm `flyctl` auth**

```bash
flyctl auth whoami | tee phase-0-evidence/00-env.log
```

Expected output (literal): an email address line. Pass/fail: passes if exit 0 and the email matches the app owner. On failure: run `flyctl auth login` and retry.

- [ ] **Step 0.3: Confirm app exists and is running**

```bash
flyctl status -a markland 2>&1 | tee -a phase-0-evidence/00-env.log
```

Expected pattern: a row showing `started` (or `running`) for at least one machine; `Hostname = markland.fly.dev`. On failure (no machines, all `stopped`): run `flyctl machine list -a markland` and `flyctl machine start <id>` for the one in `iad`.

- [ ] **Step 0.4: Verify required secrets are present**

```bash
flyctl secrets list -a markland 2>&1 | tee -a phase-0-evidence/00-env.log
```

Expected: `RESEND_API_KEY`, `MARKLAND_SESSION_SECRET`, `LITESTREAM_REPLICA_URL`, `LITESTREAM_ACCESS_KEY_ID`, `LITESTREAM_SECRET_ACCESS_KEY` all listed. `SENTRY_DSN` may or may not be present.

Pass/fail rules:
- `RESEND_API_KEY` missing -> **STOP**. Magic-link won't send. Fix per `docs/runbooks/first-deploy.md` §4 then resume.
- `LITESTREAM_*` missing -> **STOP**. Snapshots won't exist. Fix per `docs/runbooks/first-deploy.md` §4 then resume.
- `SENTRY_DSN` missing -> record `SENTRY_DSN unset` in the log; Task 1.4 will be skipped.

- [ ] **Step 0.5: Record `SENTRY_DSN` flag for later**

```bash
if flyctl secrets list -a markland | grep -q '^SENTRY_DSN'; then
  echo "SENTRY_DSN_PRESENT=1" | tee -a phase-0-evidence/00-env.log
else
  echo "SENTRY_DSN_PRESENT=0" | tee -a phase-0-evidence/00-env.log
fi
```

This boolean drives Task 1.4 (skip-or-run).

---

## Task 1: Environment checks

Mirrors checklist section "Environment". Five checks. Each captures to `phase-0-evidence/01-env-checks.log`.

**Files:**
- Create: `phase-0-evidence/01-env-checks.log`

- [ ] **Step 1.1: `/health` returns ok**

```bash
curl -fsS https://markland.fly.dev/health | tee phase-0-evidence/01-env-checks.log
echo "" >> phase-0-evidence/01-env-checks.log
```

Expected output (literal): `{"status":"ok"}`

Pass: exit 0 and body matches exactly.
Fail: any non-200, body mismatch, or empty -> **STOP**. Run `flyctl logs -a markland --no-tail | tail -100` and triage. Likely cause: machine stopped (Step 0.3), or a deploy is mid-flight.

- [ ] **Step 1.2: `/mcp/` returns 401 without auth**

```bash
code=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Accept: application/json, text/event-stream" \
  -X POST https://markland.fly.dev/mcp/ \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"phase0","version":"0"}}}')
echo "mcp-no-auth: $code" | tee -a phase-0-evidence/01-env-checks.log
test "$code" = "401"
```

Expected: `mcp-no-auth: 401` and exit 0.

Fail: any other status -> **STOP**. The auth gate is broken; fix before continuing.

- [ ] **Step 1.3: `/mcp/` returns 200 with a valid user token**

Pre-req: a valid `mk_usr_...` token for the operator. If you don't have one yet, complete Task 2.1 (Alex sign up) first against your own email then come back; this check needs at minimum **any** valid user token.

```bash
export MARKLAND_SMOKE_TOKEN="<operator-mk_usr_token>"
MARKLAND_URL=https://markland.fly.dev \
  MARKLAND_SMOKE_TOKEN="$MARKLAND_SMOKE_TOKEN" \
  ./scripts/hosted_smoke.sh 2>&1 | tee -a phase-0-evidence/01-env-checks.log
```

Expected last line: `All hosted smoke checks passed.`

Fail: script exits non-zero -> **STOP**. The error line names which curl assertion failed (initialize, whoami, etc.). Fix root cause — do not loop.

- [ ] **Step 1.4: Sentry receives a test error (skip if SENTRY_DSN unset)**

Conditional on Step 0.5. If `SENTRY_DSN_PRESENT=0`:

```bash
echo "SKIP: SENTRY_DSN unset, skipping Sentry verification" | tee -a phase-0-evidence/01-env-checks.log
```

Mark this checkbox skipped, not failed. Continue.

If `SENTRY_DSN_PRESENT=1`, trigger a deliberate error via the existing `/admin/_test_sentry` route if present, otherwise via `flyctl ssh console`:

```bash
flyctl ssh console -a markland -C "python -c 'import sentry_sdk, os; sentry_sdk.init(os.environ[\"SENTRY_DSN\"]); sentry_sdk.capture_message(\"phase-0 dogfood smoke\", level=\"error\")'" 2>&1 \
  | tee -a phase-0-evidence/01-env-checks.log
```

Expected: command exits 0. Then within 60 seconds, open the Sentry project UI in a browser and confirm a new event titled `phase-0 dogfood smoke` appears.

Pass/fail: pass = the event is visible in Sentry. Fail = no event after 2 minutes -> **STOP**. Either DSN is wrong, the SDK isn't initialized in the deployed image, or the project is in the wrong org. Cross-reference `docs/runbooks/sentry-setup.md`.

Capture screenshot evidence:

```bash
echo "SENTRY_EVENT_VISIBLE=1 (manually verified at $(date -u +%FT%TZ))" \
  | tee -a phase-0-evidence/01-env-checks.log
```

- [ ] **Step 1.5a: Resend sends magic-link to operator inbox within 10 seconds**

Trigger a sign-in:

```bash
curl -fsS -X POST https://markland.fly.dev/auth/start \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "email=<operator-email>" \
  -o /dev/null -w "auth-start: %{http_code}\n" \
  | tee -a phase-0-evidence/01-env-checks.log
date -u +"trigger-ts: %FT%TZ" | tee -a phase-0-evidence/01-env-checks.log
```

Expected: `auth-start: 200` (or 302 — record either; both indicate the form was accepted).

Then check the operator inbox. The email subject should match the production magic-link subject (look at `src/markland/web/auth_routes.py` if uncertain — typically `Sign in to Markland`).

Stopwatch: target = arrival within 10 seconds of `trigger-ts`. Acceptable = arrival within 60 seconds (Resend latency varies).

```bash
date -u +"received-ts: %FT%TZ" | tee -a phase-0-evidence/01-env-checks.log
```

Pass: email arrived, subject correct, magic-link clicks through to dashboard.
Fail (no email after 5 minutes): **STOP**. Inspect:
1. `flyctl logs -a markland | grep -i resend` — look for `resend send error` lines.
2. `flyctl secrets list -a markland | grep RESEND_API_KEY` — confirm key still present.
3. Resend dashboard "Activity" tab — look for the outbound message and any bounce/spam reason.

- [ ] **Step 1.5b: Litestream shows at least one snapshot**

```bash
flyctl ssh console -a markland -C "litestream snapshots /data/markland.db" 2>&1 \
  | tee -a phase-0-evidence/01-env-checks.log
```

Expected pattern: at least one row with a non-empty `replica`, `generation`, `index`, `size`, `created` column. Header line is fine. **Empty result** (only the header) = fail.

Fail: **STOP**. Either Litestream isn't running (check `flyctl logs -a markland | grep -i litestream` for crash loop) or the R2 credentials are wrong. Cross-reference `docs/runbooks/first-deploy.md` §4.

---

## Task 2: End-to-end six-step walkthrough (the Alex script)

This is the human-driven half. The operator coordinates with Alex (a real friend) on a video call or chat, but **does not** show Alex any commands beyond what's printed on the public quickstart page (`/setup`). The point is to catch UX cliffs.

**Files:**
- Create: `phase-0-evidence/02-walkthrough.log`

- [ ] **Step 2.1: Alex signs up**

Alex visits `https://markland.fly.dev/`, clicks **Sign in**, types their email, clicks the magic link in their inbox.

Record:

```bash
echo "=== 2.1 SIGNUP ===" | tee phase-0-evidence/02-walkthrough.log
echo "alex_email: <alex-email>" | tee -a phase-0-evidence/02-walkthrough.log
echo "signup_completed_ts: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/02-walkthrough.log
```

Expected: Alex lands on `/dashboard` after clicking the magic link; the page shows their email in the top-right.

Pass: Alex can describe the dashboard in their own words ("I see a place that says 'no docs yet'"). This is a UX check — if Alex is confused about what just happened, that is a fail even if the HTTP 200 is fine. Note any confusion verbatim in the log.

Fail (technical): magic link 404s, or click-through lands on an error page -> **STOP**. Check `flyctl logs` for the click timestamp.

Fail (UX): Alex stalls -> **STOP**. Note the friction point in the log; that is a Phase 0 blocker by definition.

- [ ] **Step 2.2: Alex installs the MCP server**

Alex tells Claude Code (verbatim, into a fresh chat): *"install the Markland MCP server from https://markland.fly.dev/setup"*

Expected sequence:
1. Claude Code visits `/setup` (or Alex copies the `claude mcp add` command shown there).
2. Alex runs `claude mcp add markland https://markland.fly.dev/mcp/` (or whatever the page prints — it must work without modification).
3. Claude Code prompts Alex to authorize via device flow URL.
4. Alex visits the URL, signs in (cookie still valid from 2.1), approves the device.
5. Claude Code shows `markland_*` tools in `claude mcp list`.

Capture from Alex's terminal:

```bash
# Alex runs this on their machine and pastes output to the operator
claude mcp list
```

Expected pattern: a line containing `markland` and showing `connected` (or equivalent green status).

Operator records:

```bash
echo "=== 2.2 INSTALL ===" | tee -a phase-0-evidence/02-walkthrough.log
echo "alex_mcp_list_output: <paste from alex>" | tee -a phase-0-evidence/02-walkthrough.log
echo "install_completed_ts: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/02-walkthrough.log
```

Pass: `claude mcp list` shows markland connected and Alex did not have to copy anything that wasn't on `/setup`.
Fail (UX): Alex needs to be coached -> **STOP**, log the missing instruction on `/setup`.
Fail (technical): device flow returns an error -> grab `flyctl logs -a markland | grep device` and triage.

- [ ] **Step 2.3: Alex publishes a doc**

Alex says to Claude Code: *"publish a markdown doc titled 'Hello' with some notes"*

Expected: Claude Code calls `markland_publish` and replies with a share URL of the form `https://markland.fly.dev/d/<slug>` (or `/v/<id>`).

Operator records:

```bash
echo "=== 2.3 PUBLISH ===" | tee -a phase-0-evidence/02-walkthrough.log
echo "alex_publish_share_url: <paste from alex>" | tee -a phase-0-evidence/02-walkthrough.log
echo "publish_completed_ts: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/02-walkthrough.log

# Operator verifies the URL is reachable
curl -fsS -o /dev/null -w "share-url-status: %{http_code}\n" \
  "<paste-share-url>" | tee -a phase-0-evidence/02-walkthrough.log
```

Expected: `share-url-status: 200`.

Pass: 200 and a non-empty page body.
Fail: 404/500 -> **STOP**. Check `flyctl logs` for the publish timestamp.

- [ ] **Step 2.4: Alex shares with the operator (edit access)**

Alex says: *"share this with `<operator-email>`, edit access"*

Expected: Claude Code calls `markland_grant`. Operator's inbox receives a notification email within 60 seconds. Email contains a link to the share URL or an "open this doc" CTA.

Record:

```bash
echo "=== 2.4 SHARE ===" | tee -a phase-0-evidence/02-walkthrough.log
echo "operator_received_grant_email_ts: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/02-walkthrough.log
echo "grant_email_subject: <paste subject>" | tee -a phase-0-evidence/02-walkthrough.log
```

Pass: email arrives, links work.
Fail (no email): cross-check Resend Activity. Grant audit row may still exist (Task 4) — note that and continue diagnosing email.
Fail (link broken): record the broken URL; **STOP**.

- [ ] **Step 2.5: Operator's agent edits the doc**

Operator runs in their own Claude Code:

> *"Append a paragraph to the doc at `<share-url>` that says 'Edited by operator at <timestamp>'. Use `if_version` to avoid clobbering."*

Expected: Claude Code calls `markland_update` with the doc's current version. The reply contains the new version number and **no** `version_conflict` error.

Capture the JSON return value (paste to log):

```bash
echo "=== 2.5 AGENT EDIT ===" | tee -a phase-0-evidence/02-walkthrough.log
echo "update_response: <paste JSON>" | tee -a phase-0-evidence/02-walkthrough.log
echo "update_completed_ts: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/02-walkthrough.log
```

Pass: response contains `"ok": true` (or equivalent success shape) and a higher version number than before.
Fail (`version_conflict`): re-fetch with `markland_fetch`, retry. If it persists, that is an actual bug -> **STOP**.

- [ ] **Step 2.6: Alex sees the edit at the share URL**

Alex refreshes the share URL in their browser. Within 5 seconds of the operator's `update_completed_ts`, the new paragraph must be visible.

Record:

```bash
echo "=== 2.6 VIEWER ===" | tee -a phase-0-evidence/02-walkthrough.log
echo "alex_saw_edit_ts: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/02-walkthrough.log
echo "latency_seconds: $(( $(date -u -d "<alex_saw_edit_ts>" +%s) - $(date -u -d "<update_completed_ts>" +%s) ))" \
  | tee -a phase-0-evidence/02-walkthrough.log
```

(Or compute manually if `date -d` is unavailable on macOS — use `python -c "import datetime as d; print((d.datetime.fromisoformat('...') - d.datetime.fromisoformat('...')).total_seconds())"`.)

Pass: latency < 5 s and the new paragraph is rendered correctly.
Fail (latency 5–30 s): record as a **soft fail** — note in the go/no-go section but do not block.
Fail (latency > 30 s or content missing): **STOP**. Caching or invalidation bug.

---

## Task 3: Rate limiting verification

Three tiers, three loops. Defaults from `src/markland/web/rate_limit_middleware.py`: user=60/min, agent=120/min, anon=20/min, with `Retry-After` header on 429.

**Files:**
- Create: `phase-0-evidence/03-rate-limits.log`

- [ ] **Step 3.1: User token → 429 after 60/min**

```bash
TOKEN="<operator-mk_usr_token>"
echo "=== 3.1 USER 60/min ===" | tee phase-0-evidence/03-rate-limits.log
for i in $(seq 1 70); do
  curl -s -o /dev/null -w "%{http_code} " \
    -H "Authorization: Bearer $TOKEN" \
    https://markland.fly.dev/health
done | tee -a phase-0-evidence/03-rate-limits.log
echo "" | tee -a phase-0-evidence/03-rate-limits.log
```

Expected pattern: a run of `200`s followed by at least one `429`. Then verify `Retry-After`:

```bash
curl -s -D - -o /dev/null \
  -H "Authorization: Bearer $TOKEN" \
  https://markland.fly.dev/health 2>&1 \
  | grep -i "^retry-after\|^HTTP/" \
  | tee -a phase-0-evidence/03-rate-limits.log
```

Expected: a header line `Retry-After: <seconds>` with seconds in [1, 60].

Pass: at least one 429 in the loop AND `Retry-After` header present.
Fail (zero 429s): rate limiter not enforcing — **STOP**.
Fail (429 but no header): `Retry-After` regression — **STOP**.

Recovery check:

```bash
sleep 65
code=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  https://markland.fly.dev/health)
echo "post-window: $code" | tee -a phase-0-evidence/03-rate-limits.log
test "$code" = "200"
```

Expected: `post-window: 200`. Fail = sliding window broken.

- [ ] **Step 3.2: Agent token → 429 after 120/min**

Mint an agent token if you don't already have one:

```bash
# From the dashboard /settings page or via API
curl -fsS -X POST https://markland.fly.dev/api/tokens \
  -H "Authorization: Bearer <operator-mk_usr_token>" \
  -H "Content-Type: application/json" \
  -d '{"kind":"agent","name":"phase-0-rate-test"}' \
  | tee -a phase-0-evidence/03-rate-limits.log
```

Expected: JSON containing `"token":"mk_agt_..."`. Save it as `AGENT_TOKEN`.

```bash
AGENT_TOKEN="mk_agt_..."
echo "=== 3.2 AGENT 120/min ===" | tee -a phase-0-evidence/03-rate-limits.log
for i in $(seq 1 130); do
  curl -s -o /dev/null -w "%{http_code} " \
    -H "Authorization: Bearer $AGENT_TOKEN" \
    https://markland.fly.dev/health
done | tee -a phase-0-evidence/03-rate-limits.log
echo "" | tee -a phase-0-evidence/03-rate-limits.log
```

Expected: at least one `429` after request 120-ish. Same pass/fail rules as 3.1. Recovery check uses `sleep 65` and expects 200.

- [ ] **Step 3.3: Anon IP → 429 after 20/min on `/explore`**

```bash
echo "=== 3.3 ANON 20/min ===" | tee -a phase-0-evidence/03-rate-limits.log
for i in $(seq 1 25); do
  curl -s -o /dev/null -w "%{http_code} " \
    https://markland.fly.dev/explore
done | tee -a phase-0-evidence/03-rate-limits.log
echo "" | tee -a phase-0-evidence/03-rate-limits.log
```

Expected: at least one `429` after request 20-ish.

Pass/fail same shape as 3.1.

Note: If your operator IP is shared (corporate NAT, VPN), this can cross-contaminate other tests. Run 3.3 last in this task, then `sleep 65` before any further requests.

- [ ] **Step 3.4: Recovery sweep**

```bash
sleep 65
echo "=== 3.4 RECOVERY ===" | tee -a phase-0-evidence/03-rate-limits.log
for label in "user" "agent" "anon"; do
  case "$label" in
    user)  hdr="-H \"Authorization: Bearer $TOKEN\"";       url="https://markland.fly.dev/health" ;;
    agent) hdr="-H \"Authorization: Bearer $AGENT_TOKEN\""; url="https://markland.fly.dev/health" ;;
    anon)  hdr="";                                          url="https://markland.fly.dev/explore" ;;
  esac
  code=$(eval curl -s -o /dev/null -w "%{http_code}" $hdr $url)
  echo "recovery-$label: $code" | tee -a phase-0-evidence/03-rate-limits.log
done
```

Expected: all three lines show `200`. Any 429 here means the limiter window didn't reset cleanly -> **STOP**.

---

## Task 4: Audit log row presence

After Tasks 2.3–2.5 (and optionally invite flow), `/admin/audit` must show rows for `publish`, `grant`, `update`, and `invite_create` + `invite_accept` *only if* invites were used. The walkthrough above (2.4) used `markland_grant` directly, not invite links, so `invite_*` rows are optional.

Action labels are sourced from grep of `src/markland/service/`: `publish` (`docs.py:120`), `grant` (`grants.py:203,271`), `revoke` (`grants.py:330`), `invite_create` (`invites.py:111`), `invite_accept` (`invites.py:212`), `update` (`docs.py:283`).

**Files:**
- Create: `phase-0-evidence/04-audit.log`

- [ ] **Step 4.1: Confirm operator is admin**

```bash
flyctl ssh console -a markland -C \
  "sqlite3 /data/markland.db 'SELECT email, is_admin FROM users WHERE email=\"<operator-email>\";'" \
  | tee phase-0-evidence/04-audit.log
```

Expected: a line `<operator-email>|1`.

Fail (`|0`): promote the operator:

```bash
flyctl ssh console -a markland -C \
  "sqlite3 /data/markland.db 'UPDATE users SET is_admin=1 WHERE email=\"<operator-email>\";'"
```

- [ ] **Step 4.2: Fetch `/admin/audit` and verify required rows**

```bash
TOKEN="<operator-mk_usr_token>"
curl -fsS https://markland.fly.dev/admin/audit \
  -H "Authorization: Bearer $TOKEN" \
  | tee -a phase-0-evidence/04-audit.log > phase-0-evidence/04-audit.html
```

Expected: HTTP 200, an HTML page rendered from `admin_audit.html`.

Then check each required action appears at least once:

```bash
for action in publish grant update; do
  count=$(grep -c "\"action\": \"$action\"" phase-0-evidence/04-audit.html \
       || grep -c ">$action<" phase-0-evidence/04-audit.html)
  echo "audit-$action: $count" | tee -a phase-0-evidence/04-audit.log
  test "$count" -ge 1 || { echo "FAIL: missing $action audit row"; exit 1; }
done
```

(The exact grep pattern depends on how `admin_audit.html` renders the action — adjust to match the live HTML; both `>publish<` cell text and JSON-blob text are likely. If neither hits, dump and inspect: `head -200 phase-0-evidence/04-audit.html`.)

Expected: three lines `audit-publish: >=1`, `audit-grant: >=1`, `audit-update: >=1`.

Fail: zero rows for any required action -> **STOP**. Cross-check the service layer: a missing audit row means the write path silently dropped it.

- [ ] **Step 4.3: Conditional invite rows**

If you also exercised `markland_invite` during the walkthrough (not in the script above), repeat Step 4.2 looking for `invite_create` and `invite_accept`. If you didn't, log:

```bash
echo "audit-invite_create: SKIP (not exercised in walkthrough)" \
  | tee -a phase-0-evidence/04-audit.log
echo "audit-invite_accept: SKIP (not exercised in walkthrough)" \
  | tee -a phase-0-evidence/04-audit.log
```

Skipping these is acceptable per the checklist's parenthetical "(if invites were used)".

---

## Task 5: Metrics funnel sanity

Six JSON-line events must appear in `flyctl logs` after Task 2 ran end-to-end:
`signup`, `token_create`, `first_mcp_call`, `first_publish`, `first_grant`, `first_invite_accept`.

`first_invite_accept` is **only** emitted if the invite flow ran (Task 4.3). If you skipped invites, you skip `first_invite_accept` here too — record as `SKIP`, do not block.

Source-of-truth (already verified by grep):
- `signup`: `src/markland/service/users.py:62`
- `token_create`: `src/markland/service/auth.py:100,129`
- `first_mcp_call`: `src/markland/web/rate_limit_middleware.py:103`
- `first_publish`: `src/markland/service/docs.py:125`
- `first_grant`: `src/markland/service/grants.py:208,276`
- `first_invite_accept`: `src/markland/service/invites.py:223`

All emit JSON to stdout via `service/metrics.py`.

**Files:**
- Create: `phase-0-evidence/05-metrics.log`

- [ ] **Step 5.1: Capture a window of logs covering Task 2**

```bash
flyctl logs -a markland --no-tail \
  | tee phase-0-evidence/05-metrics-raw.log \
  | grep -E '"event":"(signup|token_create|first_mcp_call|first_publish|first_grant|first_invite_accept)"' \
  | tee phase-0-evidence/05-metrics.log
```

Expected pattern: one or more JSON lines per event.

(If `flyctl logs --no-tail` returns nothing because the time window has rolled, switch to `flyctl logs -a markland --since 1h` or pipe a live tail in a separate terminal during Task 2.)

- [ ] **Step 5.2: Verify each required event appears at least once**

```bash
for event in signup token_create first_mcp_call first_publish first_grant; do
  count=$(grep -c "\"event\":\"$event\"" phase-0-evidence/05-metrics.log)
  echo "metric-$event: $count" | tee -a phase-0-evidence/05-metrics.log
  test "$count" -ge 1 || { echo "FAIL: missing $event metric"; exit 1; }
done

# Conditional
if grep -q '"action":"invite_accept"' phase-0-evidence/04-audit.html 2>/dev/null; then
  count=$(grep -c '"event":"first_invite_accept"' phase-0-evidence/05-metrics.log)
  echo "metric-first_invite_accept: $count" | tee -a phase-0-evidence/05-metrics.log
  test "$count" -ge 1 || { echo "FAIL: invite was used but no first_invite_accept metric"; exit 1; }
else
  echo "metric-first_invite_accept: SKIP (invite flow not exercised)" \
    | tee -a phase-0-evidence/05-metrics.log
fi
```

Expected: five (or six) `metric-...: >=1` lines, or `SKIP` for `first_invite_accept`.

Fail: any required event with count 0 -> **STOP**. The activation funnel is broken; we can't measure Phase 1 without it. Likely cause: the `metrics.emit*` call site was removed in a refactor, or `service/metrics.py` was muted.

- [ ] **Step 5.3: Sanity-check the JSON shape**

Pick one line of each event and confirm it parses:

```bash
for event in signup token_create first_mcp_call first_publish first_grant; do
  line=$(grep "\"event\":\"$event\"" phase-0-evidence/05-metrics.log | head -1)
  echo "$line" | python -c "import json,sys; d=json.loads(sys.stdin.read()); assert 'event' in d and 'ts' in d and 'principal_id' in d; print('shape-ok:', d['event'])" \
    | tee -a phase-0-evidence/05-metrics.log
done
```

Expected: five `shape-ok: <event>` lines.

Fail: any `KeyError` -> a metrics emitter has drifted from the contract in `src/markland/service/metrics.py`. **STOP**.

---

## Task 6: Go / no-go gate

This is a manual gate. Evidence comes from `phase-0-evidence/`.

**Files:**
- Create: `phase-0-evidence/06-go-no-go.log`

- [ ] **Step 6.1: Tally evidence**

```bash
echo "=== Phase 0 evidence summary ===" | tee phase-0-evidence/06-go-no-go.log
ls -la phase-0-evidence/ | tee -a phase-0-evidence/06-go-no-go.log
echo "" | tee -a phase-0-evidence/06-go-no-go.log
for f in phase-0-evidence/*.log; do
  echo "--- $f ---"; cat "$f"; echo
done | tee -a phase-0-evidence/06-go-no-go.log
```

- [ ] **Step 6.2: Score against the gate**

The gate (from `docs/runbooks/phase-0-checklist.md`): **every** unskipped checkbox must pass. Skips are allowed only for:
- Task 1.4 (Sentry) when `SENTRY_DSN` is unset.
- Task 4.3 / Task 5's `first_invite_accept` when invites were not exercised.
- Task 2.6 latency in [5, 30] seconds (recorded as soft fail; not blocking).

Anything else marked fail = **NO-GO**.

Record decision:

```bash
echo "DECISION: <GO|NO-GO>" | tee -a phase-0-evidence/06-go-no-go.log
echo "DECIDED_BY: <operator-name>"   | tee -a phase-0-evidence/06-go-no-go.log
echo "DECIDED_AT: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/06-go-no-go.log
echo "BLOCKERS: <none|list>"          | tee -a phase-0-evidence/06-go-no-go.log
```

- [ ] **Step 6.3: If GO — Phase 1 invites**

Send the first batch of Phase 1 invites (out of scope for this plan; document who/when in the log):

```bash
echo "PHASE_1_INVITES_SENT_TO: <list of emails>" | tee -a phase-0-evidence/06-go-no-go.log
echo "PHASE_1_INVITES_SENT_AT: $(date -u +%FT%TZ)" | tee -a phase-0-evidence/06-go-no-go.log
```

- [ ] **Step 6.4: If NO-GO — file blockers**

For each failed checkbox, file a `bd` issue with the captured log lines pasted in:

```bash
for blocker in <list>; do
  bd create --title "Phase 0 blocker: $blocker" --priority high \
    --body "$(cat phase-0-evidence/<relevant>.log)"
done
```

Then loop: fix, redeploy, re-run from Task 1.1. Do **not** invite anyone until a clean GO is recorded.

---

## Task 7: Rollback procedure (rehearse, do not execute)

Per the checklist: rollback = `flyctl deploy --image <previous>`; DB replays from Litestream. Rehearse the steps so muscle memory exists if Phase 1 day-1 melts.

**Files:**
- Create: `phase-0-evidence/07-rollback.log`

- [ ] **Step 7.1: Identify the previous known-good image**

```bash
flyctl releases -a markland | head -20 | tee phase-0-evidence/07-rollback.log
```

Expected: a list of releases with version, image ref, and status. The current release is at the top; the previous-good is whichever one was running before the most recent deploy.

Record:

```bash
echo "CURRENT_IMAGE=$(flyctl releases -a markland --json | python -c 'import json,sys; r=json.load(sys.stdin)[0]; print(r[\"ImageRef\"])')" \
  | tee -a phase-0-evidence/07-rollback.log
echo "PREVIOUS_IMAGE=$(flyctl releases -a markland --json | python -c 'import json,sys; r=json.load(sys.stdin)[1]; print(r[\"ImageRef\"])')" \
  | tee -a phase-0-evidence/07-rollback.log
```

- [ ] **Step 7.2: Document — but do NOT run — the rollback command**

```bash
cat <<'EOF' | tee -a phase-0-evidence/07-rollback.log
# DRY RUN — only execute on a real Phase 1 incident
# 1. Roll back the application image:
#    flyctl deploy -a markland --image <PREVIOUS_IMAGE>
# 2. Verify:
#    curl -fsS https://markland.fly.dev/health
#    flyctl status -a markland
# 3. If DB corruption (not just app bug), restore from Litestream:
#    flyctl ssh console -a markland -C "litestream restore -o /data/markland.db.restored \
#      -if-replica-exists s3://<replica-url>"
#    Then move /data/markland.db.restored -> /data/markland.db with the app stopped:
#    flyctl machine stop <id> -a markland
#    flyctl ssh console ... mv ...
#    flyctl machine start <id> -a markland
# 4. Re-run Task 1 (environment checks) to confirm rollback succeeded.
EOF
```

This block is intentionally not executed. The destructive action requires explicit user confirmation in a real incident.

- [ ] **Step 7.3: Confirm Litestream restore credentials still work (read-only)**

```bash
flyctl ssh console -a markland -C "litestream snapshots /data/markland.db" 2>&1 \
  | tee -a phase-0-evidence/07-rollback.log
```

Expected: same non-empty snapshot list as Task 1.5b. (We're proving the restore *would* work without performing it.)

Fail: empty list -> **STOP**. Rollback is not actually safe right now; fix Litestream before going GO on Task 6.

---

## Self-Review Checklist

Run after writing this plan; fix issues inline.

**1. Spec coverage** — every checklist item from `docs/runbooks/phase-0-checklist.md`:

- Environment: `/health` -> Task 1.1. `/mcp` 401/200 -> Task 1.2 + 1.3. Sentry test error -> Task 1.4. Resend magic-link -> Task 1.5a. Litestream snapshots -> Task 1.5b.
- Success criteria 1–6 -> Task 2.1–2.6 one-to-one.
- Rate limiting (user/agent/anon) -> Task 3.1/3.2/3.3 + recovery 3.4.
- Audit rows (publish, grant, invite_create, invite_accept, update) -> Task 4.2 + 4.3 (conditional).
- Metrics funnel (6 events) -> Task 5.1 + 5.2 + 5.3.
- Go/no-go -> Task 6.
- Rollback -> Task 7 (rehearsal only).

**2. Placeholder scan** — Searched for "TBD"/"figure out"/"add appropriate"/"similar to". The remaining `<angle-bracket>` tokens (e.g. `<operator-email>`, `<paste-share-url>`, `<list of emails>`) are runtime values the operator literally must paste in, not gaps in the plan. The plan lists exactly what each one is.

**3. Type/name consistency** — `mk_usr_` and `mk_agt_` token prefixes match `scripts/hosted_smoke.sh` and the canonical Plan-2 token format. Audit action names (`publish`, `grant`, `update`, `invite_create`, `invite_accept`) and metric event names (`signup`, `token_create`, `first_mcp_call`, `first_publish`, `first_grant`, `first_invite_accept`) are byte-for-byte the strings emitted by the source files cited above.

**4. Honesty about scope** — This is a runbook execution plan, not TDD code. There is no `pytest` step. Verification is by running the walkthrough and capturing artifacts under `phase-0-evidence/`. The plan says so up front and the go/no-go gate is the only "test."

---

## Execution Handoff

Plan complete and saved to `docs/plans/2026-04-28-phase-0-dogfood.md`.

This is a runbook walkthrough — execute it inline with the operator and a real human "Alex" present. Do **not** dispatch subagents (no agent has the inboxes or Alex's machine). Use `superpowers:executing-plans` for checkpoint-style stepping; pause after Task 2 to confirm UX findings before continuing.
