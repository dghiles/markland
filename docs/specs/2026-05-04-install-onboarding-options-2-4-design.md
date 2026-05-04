# Install / Onboarding — Options 2-4 Design

**Date:** 2026-05-04
**Status:** Draft for review (post-brainstorm)
**Related:** `docs/plans/2026-04-24-setup-install-ux-fix.md` (Option 1, shipped as PR #12 + #13)

## Goal

Reduce friction in the Markland install flow for both audiences without
building two parallel install paths. Phase 1 polishes the existing
CLI-first device-flow path. Phase 2 adds a browser-first onramp that
*reuses* Phase 1's path rather than duplicating it.

**Success criteria:**

1. **Phase 1.** A Claude Code (or any MCP) user installing Markland sees
   a single clickable URL, not "visit /device and type the code." The
   `device-start` API response is RFC 8628-compliant so any
   standards-aware client picks up the single-link form without reading
   our `/setup` runbook.
2. **Phase 2.** A first-time user who arrives via a Markland share link,
   signs up, and lands on the dashboard sees a "Connect Claude Code"
   panel that hands them one line to paste into Claude Code. After
   Claude Code completes the device-flow round trip, the panel
   auto-dismisses.

## Non-goals

- **OAuth 2.1 dynamic client registration on `/mcp`.** Eventual
  replacement for device flow; unbounded research. Out of scope.
- **A "Copy this bearer token" UX.** Considered and rejected — the
  third-party concerns review (2026-05-03) and PR #41 both flag
  token-on-screen-and-clipboard as a risk vector. The user-visible
  artifact is the runbook URL, not a token.
- **A standalone `/connect` page.** Dashboard panel is sufficient.
- **Removing `/me/tokens` user-token issuance.** Still has uses (manual
  debugging, non-MCP API access). Untouched.
- **Telemetry on panel dismissal vs. completion.** Worth doing later
  via the funnel-events follow-up; not blocking either phase.

## Audience

| Phase | Primary user | Activation moment |
|-------|--------------|-------------------|
| 1     | Existing Claude Code / Codex user | Pastes "Install Markland from /setup" into their CLI |
| 2     | Browser visitor who arrives at a Markland share link | Clicks "Save / Fork" CTA on `/d/{share_token}`, signs up |

Both phases converge on the same device-flow path. The web side never
mints a user-visible bearer token; the only place a token exists is
inside Claude Code's local config after the device-flow handshake.

## Architecture

```
PHASE 1 (CLI-first)                 PHASE 2 (browser-via-shares)
─────────────────────               ────────────────────────────
User in Claude Code                 User clicks share link
  │                                   │
  │ "Install Markland from /setup"    │ /d/{share_token} viewer
  ▼                                   │
/setup runbook                        │ "Save / Fork" CTA → magic-link
  │                                   ▼
  │ device-start →                  Signed in, owns a fork
  │   user_code +                     │
  │   verification_uri_complete       │ Dashboard "Connect Claude Code" panel
  │                                   │
  │ Show user ONE link:               │ Panel says:
  ▼                                   │   "In Claude Code, paste this:
/device?code=ABCD-EFGH                │    Install the Markland MCP server
  │                                   │    from https://markland.dev/setup"
  │ (signed in already?               │
  │  prefilled form, one click)       │ User pastes into Claude Code, which
  ▼                                   │ then enters the Phase 1 path on the left ────┐
device-flow auth done                 │                                              │
  │                                   ▼                                              │
  │ poll → access_token              [path converges with Phase 1] ◄──────────────────┘
  ▼
claude mcp add … installed
```

---

## Phase 1 — CLI-first polish

Three units, all touching files we already own.

### 1.1 `device-start` response gains `verification_uri_complete`

**Files:** `src/markland/service/device_flow.py`,
`src/markland/web/device_routes.py:135-160`.

**Change:** response shape gains one field:

```jsonc
{
  "device_code":               "<opaque>",
  "user_code":                 "ABCD-EFGH",
  "verification_uri":          "https://markland.dev/device",
  "verification_uri_complete": "https://markland.dev/device?code=ABCD-EFGH",  // NEW
  "poll_interval":             5,
  "expires_in":                600
}
```

`verification_uri_complete` is the RFC 8628 §3.2 standard field for "the
end-user verification URI on the authorization server, with the
`user_code` already present so the user does not have to type it." Built
from `base_url + "/device?code=" + urllib.parse.quote(user_code, safe="")`.

**No DB change. No breaking change for existing callers** — pure
additive. Existing clients that only read `verification_uri` and
`user_code` continue to work; standards-aware clients pick up the
single-link form automatically.

### 1.2 `/setup` runbook step 2 — single-link instruction

**File:** `src/markland/web/device_routes.py:347-442` (the f-string
runbook at `GET /setup`).

**Change:** rewrite step 2's "Show the user exactly this message" block.

Before:

> Visit **{host}/device** and enter the code **ABCD-EFGH**.
> The code expires in 10 minutes.

After:

> Click here to authorize: **{host}/device?code=ABCD-EFGH**
> The link expires in 10 minutes.

Also update step 1's documented response shape to include
`verification_uri_complete` so the runbook teaches Claude Code the new
field exists. The runbook may add an "If your client supports RFC 8628
`verification_uri_complete`, prefer that field" note.

### 1.3 Tests

**File:** `tests/test_device_flow_routes.py`.

Three new test cases:

- `test_device_start_includes_verification_uri_complete` — POST
  `/api/auth/device-start`, assert response includes
  `verification_uri_complete` and that the URL parses as
  `{base_url}/device?code={user_code}` with `user_code` properly
  URL-encoded.
- `test_setup_runbook_uses_single_link_form` — GET `/setup`, assert
  body contains `/device?code=` and does NOT contain the legacy
  "and enter the code" phrasing.
- `test_device_query_param_prefills_form` — GET `/device?code=ABCD-EFGH`
  with a session cookie, assert the rendered HTML form's `user_code`
  field is prefilled with `ABCD-EFGH`.

End-to-end coverage for the full device-flow path already exists
(`test_device_flow_routes.py::test_full_device_flow`). Phase 1 doesn't
change the shape — only the surface — so the existing E2E remains
authoritative.

---

## Phase 2 — Browser-via-shares onramp

Four units. Three modify existing files; one adds a small template
fragment.

### 2.1 `/api/me/dismiss-connect-claude-code` endpoint

**File:** `src/markland/web/identity_routes.py`.

`POST /api/me/dismiss-connect-claude-code`. CSRF-protected (helper from
PR #64). Sets a cookie:

```
mk_dismiss_connect=1; Path=/; Max-Age=31536000; SameSite=Strict; Secure
```

`HttpOnly` is **false** so the dashboard JS can read the cookie for the
conditional render fallback (Section 2.2). The cookie carries no PII;
its only signal is "user has clicked dismiss." Returns 204. No DB
write.

### 2.2 "Connect Claude Code" dashboard panel

**Files:** `src/markland/web/templates/dashboard.html` (or whichever
template renders the signed-in landing — verify in plan),
`src/markland/web/templates/_connect_claude_code.html` (new partial).

**Visibility logic** (server-side, Jinja conditional):

The panel renders iff all three are true:

1. The request has a valid signed-in session.
2. The user has zero rows in `device_authorizations` with
   `status = 'authorized'` for their `user_id`. New service helper:
   `service/device_flow.py::has_authorized_device(conn, user_id) -> bool`.
3. The request does NOT carry the `mk_dismiss_connect=1` cookie.

**Panel content** (the new partial):

```html
<aside class="connect-claude-code"
       data-csrf="{{ csrf_token }}"
       aria-label="Connect Claude Code">
  <header>
    <h2>Connect Claude Code</h2>
    <button class="dismiss" type="button"
            aria-label="Dismiss">×</button>
  </header>
  <p>In Claude Code, paste this message:</p>
  <div class="connect-cli-instruction">
    <code id="connect-instr">Install the Markland MCP server from {{ canonical_host }}/setup</code>
    <button class="copy" type="button"
            data-target="connect-instr">Copy</button>
  </div>
  <p class="fineprint">
    Claude Code will walk you through a one-click browser
    authorization. The access token stays inside Claude Code's local
    config — it never leaves your machine.
  </p>
</aside>
```

The Copy button uses the same vanilla-JS clipboard pattern as the
agent-token Copy button shipped in PR #65. The dismiss `×` button
POSTs to `/api/me/dismiss-connect-claude-code` (with the CSRF token
from `data-csrf`), then on success removes the panel from the DOM.

### 2.3 Auto-dismiss on device-flow completion

**File:** `src/markland/web/device_routes.py` (the `POST /device/confirm`
handler at line 255).

When the handshake completes (`result.ok` is True at line 305-315), the
existing `RedirectResponse` to `/device/done?...` gains a Set-Cookie
header for `mk_dismiss_connect=1` with the same shape as Section 2.1.
This avoids the "user completed the flow but the panel still shows on
next dashboard visit until they click ×" failure mode.

### 2.4 Tests

**Files:** `tests/test_dashboard_connect_panel.py` (new),
`tests/test_identity_routes.py`, `tests/test_device_flow_routes.py`.

- `test_dashboard_connect_panel.py` — render the dashboard for four
  scenarios: anonymous (panel absent), signed-in no authorized device
  (panel present), signed-in with authorized device (panel absent),
  signed-in with dismiss cookie (panel absent).
- `test_identity_routes.py::test_dismiss_connect_claude_code_*` —
  endpoint requires CSRF token, sets cookie correctly, returns 204,
  rejects unauthenticated callers (401 or session-required redirect,
  matching existing pattern).
- `test_device_flow_routes.py::test_confirm_sets_dismiss_cookie` —
  successful `POST /device/confirm` returns a redirect with the
  `mk_dismiss_connect=1` Set-Cookie header.

---

## Sequencing

Phase 1 ships first in its own PR. Phase 2 builds on Phase 1's
`/setup` runbook polish and the `has_authorized_device` helper added
in 1.1's service file, so Phase 2's PR has a soft dependency on Phase
1 landing in `main`.

Recommended order:

1. Phase 1 plan (writing-plans skill output) → execution → PR → merge.
2. Phase 2 plan → execution → PR → merge.

Both phases are small enough that bundling into one PR is also fine,
but separating gives cleaner review surfaces and a working Phase 1 in
production while Phase 2 is in flight.

## Manual verification (post-deploy)

After Phase 1 is in production:
- Run Claude Code, paste "Install the Markland MCP server from
  https://markland.dev/setup", confirm the user-facing message shows
  one clickable link, complete the round trip end-to-end.

After Phase 2 is in production:
- Sign out, click a public Markland share link, click Fork, sign up
  via magic-link, land on dashboard, confirm the "Connect Claude Code"
  panel appears.
- From a Claude Code session, paste the panel's instruction, complete
  the device-flow round trip, return to the dashboard, confirm the
  panel is gone.
- Sign out and back in; confirm the panel stays gone.

## Open follow-ups (not blocking)

- **Telemetry.** When `first_mcp_call` event tracking lands (separate
  follow-up), instrument panel-shown / panel-dismissed / device-flow-
  completed-from-panel as a funnel.
- **Eventual OAuth 2.1 path.** Once Claude Code or another priority
  client supports OAuth 2.1 dynamic client registration on `/mcp`, the
  whole `/setup` runbook becomes optional. Plan: re-evaluate after
  monetization spec resolves and we have signal on which client
  ecosystems matter.
