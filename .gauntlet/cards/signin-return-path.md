---
id: signin-return-path-001
title: Sign in link in the nav preserves the return path
status: ready
tags: auth, smoke, regression
stakeholder: end-user
---

A regression in the past caused the nav "Sign in" link to drop the user's
current page when clicked, sending them to bare `/login` instead of
`/login?next=<current-path>`. After sign-in, that meant the user landed on the
homepage instead of the page they were on. The fix preserves the return path
in a `?next=` query parameter.

Visit a few pages on https://markland.dev, find the "Sign in" link in the
header (top-right), and confirm its `href` matches the rule. **Do not click
through and submit the sign-in form** — only inspect the link's `href` and the
URL it would take a user to.

Pages to check:

- `/quickstart` — must link to `/login?next=/quickstart`
- `/blog/agent-native-publishing` — must link to `/login?next=/blog/agent-native-publishing`
- `/` — must link to bare `/login` (no `?next=` query string; this is by
  design — `/` is the natural post-login destination)

Use the `extract` tool or `eval` JS like
`document.querySelector('header a[href*="/login"]').href` to read the href
without clicking. Capture one screenshot of the header on `/quickstart` as
evidence.

## Acceptance Criteria

- On `/quickstart`, the header's "Sign in" link href ends with `/login?next=/quickstart`
- On `/blog/agent-native-publishing`, the header's "Sign in" link href ends with `/login?next=/blog/agent-native-publishing`
- On `/`, the header's "Sign in" link href ends with exactly `/login` (no query string)
- The link is visible and rendered (not hidden by CSS, not behind a hamburger that wasn't opened)
