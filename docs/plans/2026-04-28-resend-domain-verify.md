# Resend Domain Verify + Secret Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up the live magic-link email path on the Fly-hosted `markland` app: verify `markland.dev` in Resend (DNS records), set `RESEND_API_KEY` + `RESEND_FROM_EMAIL` as Fly secrets, deploy, smoke-test a real magic link end-to-end, and update the first-deploy runbook with the actual flow that worked.

**Architecture:** This is mostly an ops/runbook unit. The application code already supports the live path — `EmailClient` (`src/markland/service/email.py`) calls `resend.Emails.send()` when `api_key` is non-empty, and no-ops with a stdout log otherwise. `Config` (`src/markland/config.py:43-44`) already pulls `RESEND_API_KEY` / `RESEND_FROM_EMAIL` from env. So the work is: (1) DNS records in Cloudflare for SPF/DKIM/DMARC/return-path, (2) Resend dashboard verification, (3) two Fly secrets, (4) redeploy, (5) live smoke test, (6) backfill the runbook with the records and gotchas we hit.

**Tech Stack:** Resend (transactional email), Cloudflare DNS, Fly.io (`flyctl secrets`, `flyctl deploy`, `flyctl logs`), Python `resend` SDK, `itsdangerous` for token signing, pytest for the small regression test guarding the init-log line.

**Prerequisites (assumed done — not part of this plan):**
- `markland.dev` is registered and on Cloudflare DNS (per `docs/runbooks/first-deploy.md` §1).
- A Resend account exists for `daveyhiles@gmail.com`.
- `flyctl` is authenticated locally; the `markland` Fly app already exists (per the "Current deploy state" table in the runbook).
- DNS A/AAAA records for `markland.dev` apex are pointing at Fly (or it's acceptable to test against the `markland.fly.dev` hostname — the plan calls this out where relevant).

---

## File Structure

This plan touches:

- **Modify:** `docs/runbooks/first-deploy.md` — replace stub §2 (Resend) with the actual records and verified-flow notes; flip the "Current deploy state" table row for Resend from **pending** to **done**.
- **Create:** `tests/test_run_app_init_log.py` — one regression test that asserts `run_app.py`'s init-log line includes `resend=True` when `RESEND_API_KEY` is set, so we don't silently regress the visibility we rely on for smoke verification.
- **Read-only references (do not modify):**
  - `src/markland/service/email.py` — `EmailClient` no-op vs. live branch (lines 41-46 vs 48-65).
  - `src/markland/service/magic_link.py` — `send_magic_link()` (lines 67-107).
  - `src/markland/config.py:43-44` — env-var reads.
  - `src/markland/run_app.py:80-87` — the init-log line we depend on for verification.
  - `scripts/start.sh` — entrypoint; no changes needed.
  - `tests/test_email_integration.py`, `tests/test_email_dispatcher.py`, `tests/test_service_magic_link.py` — existing coverage; we are not modifying these.

---

## Task 1: Verify the application code path is live-ready (no code changes)

This is a sanity gate. Before touching DNS or Fly, prove the only difference between "disabled" and "live" is whether `RESEND_API_KEY` is non-empty in the process env.

**Files:**
- Read: `src/markland/service/email.py:41-65`
- Read: `src/markland/config.py:43-44`
- Read: `src/markland/run_app.py:61-65,80-87`

- [ ] **Step 1: Read `EmailClient.send` and confirm the disabled-vs-live branch**

Open `src/markland/service/email.py` and confirm lines 41-46 are the disabled branch:

```python
if not self._api_key:
    logger.info(
        "Email disabled (no RESEND_API_KEY); would have sent to %s: %s",
        to, subject,
    )
    return None
```

And lines 48-65 are the live branch that calls `resend.Emails.send(payload)`.

Expected: no code changes needed. The branch flips purely on `self._api_key` truthiness, which comes from `Config.resend_api_key` (`src/markland/config.py:43`).

- [ ] **Step 2: Confirm `run_app.py` constructs `EmailClient` from config**

Open `src/markland/run_app.py` and verify lines 61-64:

```python
email_client = EmailClient(
    api_key=config.resend_api_key,
    from_email=config.resend_from_email,
)
```

Expected: matches what's in the file. Nothing to change.

- [ ] **Step 3: No commit — this task is verification only**

If anything in the code surprises you, stop the plan and surface it. Otherwise proceed.

---

## Task 2: Add a regression test for the init-log line

We rely on `flyctl logs` showing `resend=True` after the redeploy in Task 6 to know the secret is loaded. Lock that string down so a refactor doesn't silently strip it.

**Files:**
- Create: `tests/test_run_app_init_log.py`
- Read: `src/markland/run_app.py:80-87`

- [ ] **Step 1: Read the exact init-log format string**

Open `src/markland/run_app.py:80-87`. The format string is:

```python
"Starting Markland hosted app on %s:%d (db: %s, mcp_enabled=%s, resend=%s)"
```

with the final `%s` argument being `bool(config.resend_api_key)`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_run_app_init_log.py`:

```python
"""Regression: run_app.py's init-log format string must surface `resend=<bool>`.

We use this string in the first-deploy runbook to verify the Fly secret loaded
after a redeploy. If the format changes, the runbook check breaks silently.
"""

from __future__ import annotations

from pathlib import Path


def test_run_app_init_log_includes_resend_flag() -> None:
    src = Path("src/markland/run_app.py").read_text()
    # The exact format string we depend on.
    assert "resend=%s" in src, (
        "run_app.py init log must include `resend=%s` so operators can verify "
        "the RESEND_API_KEY secret loaded after `flyctl deploy`."
    )
    # And we must actually pass `bool(config.resend_api_key)` for that slot.
    assert "bool(config.resend_api_key)" in src, (
        "run_app.py must pass bool(config.resend_api_key) into the init log."
    )
```

- [ ] **Step 3: Run the test to verify it passes against current code**

Run: `uv run pytest tests/test_run_app_init_log.py -q`

Expected: `1 passed`. (This is a "lock the contract" test, not a TDD red-first test — the contract already holds; we're cementing it.)

- [ ] **Step 4: Commit**

```bash
git add tests/test_run_app_init_log.py
git commit -m "test(run_app): lock down resend=<bool> in init log line"
```

---

## Task 3: Add Resend's DNS records to Cloudflare

This step is manual and human-gated. No code, no tests. Output is a set of new DNS records on `markland.dev`.

**Files:**
- None (Cloudflare dashboard + Resend dashboard).

- [ ] **Step 1: In Resend, add the domain**

1. Sign in to https://resend.com as `daveyhiles@gmail.com`.
2. Domains -> Add domain -> enter `markland.dev`.
3. Region: choose **us-east-1** (matches Fly app region `iad`, minimizes cross-region send latency).
4. Resend will display 4-6 DNS records. Keep the tab open — you'll paste them into Cloudflare next.

- [ ] **Step 2: In Cloudflare DNS, add each record exactly as Resend shows**

For `markland.dev` zone, expect roughly these record types (Resend will show the exact names/values; copy them verbatim):

| Type | Name | Value (from Resend) | Proxy |
|------|------|--------------------|-------|
| MX | `send` | `feedback-smtp.us-east-1.amazonses.com` (priority 10) | DNS only (grey cloud) |
| TXT | `send` | `v=spf1 include:amazonses.com ~all` | DNS only |
| TXT | `resend._domainkey` | DKIM public key (long base64 string Resend gives you) | DNS only |
| TXT | `_dmarc` | `v=DMARC1; p=none;` | DNS only |

Notes:
- **All records must be grey cloud (DNS only).** Cloudflare-proxied mail records break SPF/DKIM lookups.
- Resend may show the DKIM record name as `resend._domainkey.markland.dev`. In Cloudflare, just enter the host portion (`resend._domainkey`); Cloudflare auto-suffixes the zone.
- If Resend shows a "return-path" CNAME (e.g. `bounces.markland.dev` -> something at `amazonses.com`), add it too. Same grey-cloud rule.
- Do **not** add a record that conflicts with an existing `@` MX (the trust-floor pages have no inbox configured yet). If one already exists, document it and ask the operator before deleting.

- [ ] **Step 3: Wait for Cloudflare to propagate and Resend to verify**

Cloudflare propagates internally in seconds, but Resend's verifier may take 1-5 minutes. In the Resend Domains page, the row for `markland.dev` should flip from "Pending" to **Verified** (green check on each record).

Verify locally:

```bash
dig +short TXT _dmarc.markland.dev
dig +short TXT resend._domainkey.markland.dev
dig +short MX send.markland.dev
```

Expected: each command returns the value you entered (DKIM is one long quoted string).

- [ ] **Step 4: Generate a sending API key**

In Resend: API Keys -> Create API Key.
- Name: `markland-fly-prod`
- Permission: **Sending access** (not full access)
- Domain: **`markland.dev` only**

Copy the `re_...` value to your password manager **immediately** — Resend shows it once.

- [ ] **Step 5: No commit — this task touches dashboards, not the repo.**

---

## Task 4: Set the Fly secrets

**Files:**
- None (operates on Fly app `markland`).

- [ ] **Step 1: Set `RESEND_API_KEY` and `RESEND_FROM_EMAIL` together**

Run the secrets command in **one** invocation so Fly only restarts machines once:

```bash
flyctl secrets set \
  --app markland \
  RESEND_API_KEY='re_...paste from Task 3 step 4...' \
  RESEND_FROM_EMAIL='notifications@markland.dev'
```

Notes:
- `RESEND_FROM_EMAIL` is already in `fly.toml [env]` per `docs/runbooks/first-deploy.md:324` — setting it as a secret overrides that with the same value, which is fine and explicit. (We could leave it in `[env]` only, but pinning it as a secret here means rotating the env doesn't accidentally drop the from address.)
- Use **single quotes** to avoid shell interpolation of the `re_` prefix or any special chars.
- Do **not** echo the API key to stdout, do **not** paste it into a chat or commit.

- [ ] **Step 2: Verify both secrets show up**

```bash
flyctl secrets list --app markland
```

Expected: both `RESEND_API_KEY` and `RESEND_FROM_EMAIL` rows appear with recent `Updated` timestamps. Values are not displayed (Fly redacts them).

- [ ] **Step 3: No commit — Fly secrets are not stored in the repo.**

---

## Task 5: Redeploy and verify the init log line

`flyctl secrets set` triggers a rolling restart automatically, but we want to confirm the new process picked up the key. If for any reason Fly skipped the restart (rare), force a redeploy.

**Files:**
- None (Fly machines).

- [ ] **Step 1: Tail the logs while the rolling restart finishes**

```bash
flyctl logs --app markland
```

Wait until you see a fresh boot cycle. The line we care about is from `src/markland/run_app.py:80-87`:

```
Starting Markland hosted app on 0.0.0.0:8080 (db: /data/markland.db, mcp_enabled=True, resend=True)
```

Expected: `resend=True`. If you see `resend=False`, the secret didn't load — re-run Task 4 step 1 and check for typos.

- [ ] **Step 2: If no fresh boot appeared, force a redeploy**

```bash
flyctl deploy --app markland
```

Then re-tail logs and confirm the `resend=True` line.

- [ ] **Step 3: Confirm no `Email disabled` warnings on the live machine**

The disabled-branch log line is `Email disabled (no RESEND_API_KEY); would have sent to ...` (`src/markland/service/email.py:42-45`). After the redeploy, this string should **not** appear when a magic link is requested. (We test that in Task 6.)

- [ ] **Step 4: No commit — verification only.**

---

## Task 6: Live smoke test — magic link end-to-end

The live test exercises the path:
`POST /auth/magic-link` -> `send_magic_link()` -> `EmailDispatcher.enqueue` -> `EmailClient.send()` -> `resend.Emails.send()` -> Resend -> inbox.

**Files:**
- None (browser, terminal, mailbox).

- [ ] **Step 1: Decide which hostname to test against**

The Resend domain is `markland.dev`. The Fly app may still be reachable at `markland.fly.dev` if DNS for the apex isn't cut over yet. Both work for sending — Resend doesn't care about the request hostname, only the verified domain in the `from` address.

- If `markland.dev` resolves to Fly: use `https://markland.dev/auth/magic-link`.
- Otherwise: use `https://markland.fly.dev/auth/magic-link` (the magic-link URL embedded in the email will use whatever `MARKLAND_BASE_URL` is set to in `fly.toml [env]`, so the click-through will land on whichever is currently live — that's fine).

- [ ] **Step 2: Request a magic link to a real inbox you control**

In a browser, visit the host from step 1's `/auth/magic-link` page, enter `daveyhiles@gmail.com`, submit.

Tail logs in another terminal:

```bash
flyctl logs --app markland
```

Expected: a JSON log line `Magic-link email enqueued for daveyhiles@gmail.com` (from `src/markland/service/magic_link.py:106`), followed shortly by no `EmailSendError` or `Email disabled` lines.

- [ ] **Step 3: Confirm the email arrives**

Wait up to 60 seconds. Expected: an email from `notifications@markland.dev` lands in the Gmail inbox. The subject and body come from `email_templates.magic_link()`.

If it doesn't arrive within 2 minutes:
- Check Resend dashboard -> Logs. If "Delivered" — it's a Gmail filtering issue; check Spam.
- If "Bounced" with SPF/DKIM error — DNS records propagated slowly or are wrong; re-verify Task 3 step 3.
- If no Resend log row at all — `RESEND_API_KEY` is wrong or scoped to a different domain; re-check Task 3 step 4.

- [ ] **Step 4: Click the magic link and confirm sign-in works**

Click the link in the email. Expected: redirect to `/` signed in. Confirm by visiting `/settings/tokens` — the page should load without prompting for sign-in.

- [ ] **Step 5: Repeat with a second non-Gmail inbox if available**

Send-test to a non-Gmail address (e.g. an iCloud or work address) to catch SPF/DKIM mistakes that Gmail's permissive policy would mask. If you don't have one handy, skip — Resend's dashboard "Send Test Email" with a non-Gmail address is an acceptable substitute.

- [ ] **Step 6: No commit — smoke test only.**

---

## Task 7: Update the first-deploy runbook

Replace the stub Resend section with the actual flow we just verified, and flip the "Current deploy state" row.

**Files:**
- Modify: `docs/runbooks/first-deploy.md` (the "Current deploy state" table row for §2, and §2 itself).

- [ ] **Step 1: Flip the Resend row in the "Current deploy state" table**

In `docs/runbooks/first-deploy.md`, around line 22, change:

```
| 2. Resend domain verify | **pending** — blocked on domain purchase |
```

to:

```
| 2. Resend domain verify | done — `markland.dev` verified, `RESEND_API_KEY` + `RESEND_FROM_EMAIL` set on Fly |
```

Also flip the row near line 25:

```
| 7. Set secrets | only `MARKLAND_SESSION_SECRET` set; Resend + Litestream + Sentry pending |
```

to reflect that `RESEND_API_KEY` and `RESEND_FROM_EMAIL` are now set (Litestream/Sentry status untouched — out of scope for this plan):

```
| 7. Set secrets | `MARKLAND_SESSION_SECRET` + `RESEND_API_KEY` + `RESEND_FROM_EMAIL` set; Litestream + Sentry pending |
```

- [ ] **Step 2: Replace the stub `## 2. Resend - verify sending domain` section**

The current section (lines 79-93) is generic. Replace its body with the verified-flow content. The new section keeps the same heading and the trailing `---` separator, but the steps reflect what actually happened:

```markdown
## 2. Resend - verify sending domain

This step is required for magic-link sign-in to work in production.
Verified flow as of 2026-04-28:

1. Sign up / log in at https://resend.com.
2. Domains -> Add domain -> `markland.dev`. Region: **us-east-1**
   (matches Fly region `iad`).
3. Resend displays 4 DNS records. Add them to Cloudflare DNS for
   `markland.dev`, all **DNS only (grey cloud)**:

   | Type | Name | Value |
   |------|------|-------|
   | MX | `send` | `feedback-smtp.us-east-1.amazonses.com` (priority 10) |
   | TXT | `send` | `v=spf1 include:amazonses.com ~all` |
   | TXT | `resend._domainkey` | DKIM public key (long base64 — copy from Resend) |
   | TXT | `_dmarc` | `v=DMARC1; p=none;` |

   If Resend also shows a return-path CNAME (e.g. `bounces` ->
   `feedback-smtp.us-east-1.amazonses.com`), add it. Same grey-cloud rule.

4. In the Resend Domains page, wait for the row to flip from
   "Pending" to **Verified** (typically 1-5 min). Verify locally:

   ```bash
   dig +short TXT _dmarc.markland.dev
   dig +short TXT resend._domainkey.markland.dev
   dig +short MX send.markland.dev
   ```

5. API Keys -> Create API Key. Name `markland-fly-prod`, permission
   **Sending access**, domain **`markland.dev` only**. Copy the
   `re_...` key — Resend shows it once.

6. Set the Fly secrets in a single invocation (one rolling restart):

   ```bash
   flyctl secrets set \
     --app markland \
     RESEND_API_KEY='re_...' \
     RESEND_FROM_EMAIL='notifications@markland.dev'
   ```

7. Confirm the redeploy picked up the key — tail logs and look for
   the init line from `src/markland/run_app.py`:

   ```
   Starting Markland hosted app on 0.0.0.0:8080 ... resend=True ...
   ```

   `resend=False` means the secret didn't load — recheck step 6.

8. Live smoke: visit `/auth/magic-link`, request a link to a mailbox
   you control, click through, confirm sign-in works. Cross-check in
   Resend dashboard -> Logs. Test against at least one non-Gmail
   inbox to catch SPF/DKIM issues Gmail would mask.

Record (in your password manager):
- `RESEND_API_KEY=re_...`
- `RESEND_FROM_EMAIL=notifications@markland.dev` (matches `fly.toml`)

---
```

Use the `Edit` tool with `old_string` matching the existing section verbatim (lines 79-94) and `new_string` set to the block above.

- [ ] **Step 3: Verify the runbook still renders cleanly**

```bash
grep -n "^## " docs/runbooks/first-deploy.md
```

Expected: section ordering unchanged; `## 2. Resend - verify sending domain` is still followed by `## 3. Cloudflare R2 - Litestream replica bucket`. No duplicated `---` separators.

- [ ] **Step 4: Run the test suite to make sure no docs-adjacent test broke**

```bash
uv run pytest tests/ -q
```

Expected: all green, including `tests/test_run_app_init_log.py` from Task 2.

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/first-deploy.md
git commit -m "docs(runbook): backfill Resend section with verified flow"
```

---

## Task 8: Final verification pass

- [ ] **Step 1: Re-run the full test suite**

```bash
uv run pytest tests/ -q
```

Expected: all green.

- [ ] **Step 2: Re-confirm live state**

In one terminal:

```bash
flyctl logs --app markland
```

In another, request a fresh magic link via `/auth/magic-link`. Confirm:
- `Magic-link email enqueued for ...` in logs.
- No `Email disabled` line.
- Email arrives.
- Click-through signs you in.

- [ ] **Step 3: Sanity-check the runbook table reflects reality**

```bash
grep -n "Resend" docs/runbooks/first-deploy.md | head -5
```

Expected: the "Current deploy state" row for §2 says `done`; the §7 row mentions `RESEND_API_KEY` set.

- [ ] **Step 4: No commit — verification only.**

---

## Self-Review Checklist

**1. Spec coverage:**
- (a) Domain purchase — explicitly out of scope, called out in Prerequisites.
- (b) DNS verify (SPF/DKIM/DMARC) — Task 3.
- (c) `flyctl secrets set RESEND_API_KEY` + `RESEND_FROM_EMAIL` — Task 4.
- (d) Deploy + verify init log line — Task 5.
- (e) Smoke-test magic-link send (staging + production email) — Task 6 step 5 covers a second non-Gmail inbox; "staging" doesn't exist as a separate Fly app, so the second-inbox test is the proxy for it.
- (f) Confirm `EmailClient` no-longer-disabled path executes — Task 5 step 3 (no `Email disabled` line) + Task 6 step 2 (no warning, dispatcher enqueued line present).
- (g) Update `docs/runbooks/first-deploy.md` Resend section — Task 7.

All seven items mapped.

**2. Placeholder scan:** No "TBD", "implement later", "fill in details", "similar to", or unspecified error handling. Every step has an exact command or exact text to write. Two intentional ellipses exist for the API key value (`re_...`) — those are the real-secret placeholder, not a plan-failure placeholder.

**3. Type/contract consistency:**
- Init-log format string `resend=%s` referenced in Task 2, Task 5 step 1, and Task 7 step 2 — all match `src/markland/run_app.py:80-87`.
- Disabled-branch log string `Email disabled (no RESEND_API_KEY)` referenced in Task 5 step 3 — matches `src/markland/service/email.py:42-45`.
- Enqueue log string `Magic-link email enqueued for` referenced in Task 6 step 2 and Task 8 step 2 — matches `src/markland/service/magic_link.py:106`.
- Fly app name `markland` consistent across Tasks 4-7.

No issues found.
