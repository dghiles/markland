# Launch — Known Quirks

Drafts of items to call out at public-release announcement time. Each
entry is short, copy-pasteable into the launch post / changelog / FAQ.

## SameSite=Strict on the session cookie (`mk_session`)

**Behaviour:** When a signed-in Markland user clicks a Markland link
from another origin (Slack, email, Twitter, an external blog), the
browser does **not** send the `mk_session` cookie on the first request.
For that first page load the user looks like an anonymous visitor —
e.g. on a public-doc viewer page at `/d/{share_token}` they will see
the public-doc view stripped of presence identity and other signed-in
affordances. After one same-site click (any link inside Markland) the
cookie travels normally and the user is back to their authenticated
view.

**Why we made this choice:** `SameSite=Strict` removes a class of
cross-site request-forgery vectors that `Lax` does not (in particular,
top-level cross-site POSTs in some browser-version edge cases).
Combined with our other CSRF protections it raises the floor on
session-bound mutating routes.

**What you might experience:** "I clicked a link from Slack and the
page acted like I wasn't logged in. I refreshed and now I am." Yes,
that's expected. Reload or click any link inside Markland and the
session resumes.

**Source:** [`markland-qzo`](https://github.com/dghiles/markland) /
PR #64 (P1-A).
