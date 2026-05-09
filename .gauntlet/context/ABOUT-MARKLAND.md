## What Markland is

Markland is a publishing surface for markdown documents that AI agents (Claude
Code, etc.) push to via MCP. Live at https://markland.dev.

Public, unauthenticated surfaces an external tester will encounter:

- `/` — homepage
- `/quickstart` — install + setup walkthrough
- `/blog`, `/blog/{slug}`, `/blog/feed.xml` — Atom feed
- `/explore` — public document index
- `/login` — magic-link sign-in (email only, no password)
- `/terms`, `/privacy` — legal pages

The site uses magic-link authentication: you submit an email, receive a one-time
link, and click it. The tester should NOT attempt to complete sign-in unless
the card explicitly provides a working email + a way to read the inbox. For
read-only smoke tests, only verify that the sign-in *form* and *links* behave
correctly — do not submit the form.

## Navigation header

Every page has a top header with at least these landmarks:

- A "Markland" wordmark/logo linking to `/`
- A "Sign in" link in the upper-right (when logged out)
- Some pages also expose "Explore" and "Docs/Quickstart" links

## The "next=" return-path convention

The sign-in link is expected to preserve the user's current location via a
`?next=` query parameter on the `/login` URL, **except** on `/` where the link
is bare `/login` (because `/` is the natural post-login destination).

Examples that should hold:

- On `/quickstart` → Sign in href is `/login?next=/quickstart`
- On `/blog/agent-native-publishing` → `/login?next=/blog/agent-native-publishing`
- On `/` → `/login` (no query string, by design)

This was a real bug fix (PR for `markland-3zx`) and is worth re-checking after
any deploy that touches the header component or the auth flow.
