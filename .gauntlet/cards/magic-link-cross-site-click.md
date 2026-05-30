---
id: magic-link-cross-site-click
title: Magic-link click from a cross-site origin signs the user in
status: ready
tags: auth, smoke, regression, samesite
stakeholder: end-user
---

A past bug (`markland-qzo`, reverted in PR #74) set the `mk_session`
cookie with `SameSite=Strict`. The unit-test layer (httpx TestClient)
does not enforce SameSite, so tests passed, but real browsers do enforce
it — and a Strict cookie is NOT sent on the 303 follow-up after a
cross-site top-level navigation. Magic-link clicks from email clients,
Slack, iMessage, and similar redirectors silently bounced users back to
`/login` instead of signing them in.

This card verifies the regression is fixed and stays fixed by driving
the exact scenario the unit tests cannot: cross-origin → /verify → 303
→ /dashboard → must be authenticated.

## How to drive it

1. **Read the e2e mint secret from the fixture file** via the `read`
   tool: `read .gauntlet/context/secrets/e2e-mint-secret.md`. Parse
   the `MARKLAND_E2E_SECRET=<value>` line.

   If the file is missing or the value is still the literal placeholder
   `<paste-value-here>`, abort and call `report_result` with status
   `errored` and reason: *"Secret fixture missing — see
   `.gauntlet/context/secrets/README.md` for setup."*

2. **Mint a fresh verify URL** by POSTing to the e2e smoke endpoint.
   The endpoint mints a real prod-signed token without round-tripping
   through Resend, so the card stays under 60 seconds:

   ```js
   const r = await fetch('https://markland.dev/api/test/mint-magic-link?email=smoke-' + Date.now() + '@markland.test', {
     method: 'POST',
     headers: { 'X-Markland-E2E-Secret': '<value from step 1>' }
   });
   ({ status: r.status, body: await r.json() })
   ```

   Expect HTTP 200 and a body shaped `{ verify_url: "https://markland.dev/verify?token=...", email: "..." }`.

3. **Establish a cross-site browsing context** by navigating to a
   non-markland origin first. This is critical — without the cross-site
   start, the test passes for `Strict` too, which is the exact blind
   spot that caused the original bug:

   ```js
   await page.goto('https://example.com');
   ```

4. **Trigger the cross-site navigation to /verify** via JS, NOT by
   calling `navigate` directly. `navigate` from the same Playwright
   page typically counts as same-site for SameSite purposes; setting
   `window.location.href` from a script running on example.com is the
   genuine cross-site top-level nav that mirrors an email-redirector
   click:

   ```js
   window.location.href = '<verify_url from step 2>';
   ```

5. **Wait for the redirect chain to settle**, then read the final URL
   and confirm signed-in state:

   ```js
   // After the JS nav settles:
   const me = await fetch('/api/me');
   ({ url: window.location.href, meStatus: me.status, meBody: await me.text() })
   ```

## Acceptance Criteria

- Step 2: `/api/test/mint-magic-link` returns HTTP 200 with a `verify_url`
  string that starts with `https://markland.dev/verify?token=`.
- Step 5: the final `window.location.href` ends with `/dashboard`
  (NOT `/login`, NOT `/login?next=...`, NOT any path containing
  `magic-link` or `verify`).
- Step 5: `/api/me` returns HTTP 200 with a body whose `email` field
  equals the email from step 2's response. This is the proof that the
  session cookie survived the cross-site → 303 → same-origin chain.
- The doc page title is `Dashboard · Markland` (extract via
  `document.title` or the page snapshot).

## Failure modes — what to look for

- **Final URL ends with `/login`** → SameSite regression is back.
  Likely `mk_session` cookie was set with `SameSite=Strict` again.
  Check `src/markland/web/auth_routes.py` around the `set_cookie` call
  in `verify_page`.
- **`/api/me` returns 401** → session cookie not stored at all. Check
  `Secure` flag mismatch with the request scheme, or `Path` mismatch.
- **Mint endpoint returns 404** → either `MARKLAND_E2E_SECRET` isn't
  set on Fly (check `flyctl secrets list -a markland`) or the secret
  in the fixture file is stale. Endpoint 404s on both "not deployed"
  and "wrong secret" by design.
- **Mint endpoint returns 400** → the test email didn't end with
  `@markland.test`. Fix the local-part generation in step 2.

Capture one screenshot of the dashboard after step 4 as evidence.
