# Pre-Launch Clean-Up Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take Markland from "technically live but stalled" to "Show-HN-ready" by fixing the homepage conversion leak (91% bounce, 0 signups in 14d), restarting content velocity (post #2 is ~24 days late), validating the install flow end-to-end ourselves, and shipping the trust gates that will be load-bearing the moment a Show HN drives traffic.

**Architecture:** Six independent tracks, sequenced so the foundation (Phase 0 dogfood) lands before the leak-fix (homepage CRO), the leak-fix lands before the content + outreach push (post #2 + Show HN draft), and the trust gates ship in parallel as a backstop. Each track has bounded scope; novel work (Tracks B/C/D/F) is task-broken-down inline, work with existing plans (Tracks A/E) delegates to those plans.

**Tech Stack:** FastAPI + Jinja2, pytest, vanilla JS for the dashboard panel, markdown content for the blog post, no new infra.

**Soak-window evidence driving this plan:** `docs/ROADMAP.md` Next-lane entry "Soak-window analytics check [done 2026-05-29]". 14d window: 0 signups, 1 publish (admin), 52 visitors, 91% bounce, 1 blog view, 60% pageview drop WoW. Conclusion: funnel leaks at the hero, not the trust gates.

---

## File Structure

**Modify:**

- `src/markland/web/templates/landing.html:570-595` — hero block (the leak point: primary CTA collects waitlist emails on a service that's already live).
- `src/markland/web/templates/dashboard.html` — wire the new "First publish" welcome panel.
- `src/markland/web/identity_routes.py` — add a dismiss endpoint for the welcome panel.
- `src/markland/service/docs.py` — new helper `user_has_owned_docs(conn, user_id) -> bool`.
- `docs/ROADMAP.md` — sequencing notes + post-completion strikethroughs.

**Create:**

- `src/markland/web/templates/_welcome_first_publish.html` — new dashboard partial.
- `src/markland/web/content/blog/share-claude-code-output.md` — anchor post #2.
- `tests/test_landing_cta.py` — pin the new hero CTA shape.
- `tests/test_dashboard_welcome_panel.py` — pin visibility logic for the new panel.
- `tests/test_blog_post_share_claude.py` — pin metadata + word-count for post #2.
- `docs/launch/2026-05-29-show-hn-draft.md` — Show HN post text + canned replies, not yet posted.

**Delegate to existing plans (do not rewrite):**

- `docs/plans/2026-04-28-phase-0-dogfood.md` — finish steps 4-14.
- `docs/plans/2026-05-04-self-service-deletion.md` — Phase 1 only (doc deletion UI).
- `docs/plans/2026-05-04-formal-privacy-policy.md` — all 14 tasks.
- `docs/plans/2026-05-04-formal-terms-of-service.md` — all 17 tasks.

**Test framework:** `uv run pytest tests/ -q`.

---

# Track A — Phase 0 Dogfood Finish (validate before optimizing)

**Why first:** if the flow we're about to drive traffic into has bugs we haven't found, optimizing the hero just funnels people into a broken experience faster.

## Task A1: Execute the existing Phase 0 plan, steps 4-14

**Files:** none in this plan — delegate.

- [ ] **Step 1: Read the existing plan**

```bash
less docs/plans/2026-04-28-phase-0-dogfood.md
```

- [ ] **Step 2: Confirm where Eric stopped**

Existing roadmap note: "Eric ran 1-3 with view-grant only (`b87f338`)." Steps 4-14 cover edit-grant, grant-revocation, MCP-from-CLI, agent token issuance, public-doc reading, `markland_search` from a fresh client.

- [ ] **Step 3: Run each remaining step against `https://markland.dev` from a clean Claude Code config**

For each step, capture what worked and what didn't. File any new bug as a beads issue under the `markland-fjd` family (or new bead) before moving to the next step. Do not fix bugs inline — that scope-creeps the validation pass.

- [ ] **Step 4: Update the dogfood plan with pass/fail per step**

Edit `docs/plans/2026-04-28-phase-0-dogfood.md` to record completion. Add a row to the audit log at the bottom (mirror Eric's format).

- [ ] **Step 5: Commit**

```bash
git add docs/plans/2026-04-28-phase-0-dogfood.md
git commit -m "docs(dogfood): Phase 0 steps 4-14 verified against prod"
```

- [ ] **Step 6: If any bug was filed, decide whether to ship the homepage CRO now or fix-the-bug-first**

If a P0/P1 bug was filed, STOP this plan and fix the bug. The homepage CRO can wait. If only P2/P3 bugs, continue — the leak fix is higher leverage than the polish.

---

# Track B — Homepage Conversion Fix (the leak)

**Why:** hero primary CTA today is `POST /api/waitlist` with copy "Pre-launch · we'll email when it's ready." Service has been live 30 days. Visitors who came to try it find a waitlist gate and bounce. 91% bounce on a homepage that's 64% of pageviews = the single biggest improvement available.

## Task B1: Pin current hero with a regression test (catch the change explicitly)

**Files:**
- Test: `tests/test_landing_cta.py` (new).

- [ ] **Step 1: Write the failing test**

Create `tests/test_landing_cta.py`:

```python
"""Landing page hero CTA — must send users into the magic-link flow,
not into a pre-launch waitlist. Pins the conversion fix from
docs/plans/2026-05-29-pre-launch-cleanup.md."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    app = create_app(
        conn, mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        yield c


def test_landing_hero_primary_cta_routes_to_login(client):
    """The big primary CTA on / should hand the visitor straight into
    magic-link sign-in, not into /api/waitlist."""
    r = client.get("/")
    assert r.status_code == 200
    text = r.text
    # The waitlist form must NOT be the primary CTA in the hero block.
    # We allow waitlist as a secondary/footer affordance for users who
    # really want it — but not as the giant button people land on.
    hero_section = text.split("<section class=\"section\"", 1)[0]
    assert 'action="/api/waitlist"' not in hero_section, (
        "hero still gates conversion on /api/waitlist — see "
        "docs/plans/2026-05-29-pre-launch-cleanup.md Track B"
    )
    # The new primary path: /login (magic link)
    assert "/login" in hero_section


def test_landing_no_pre_launch_messaging(client):
    """Site has been live for 30+ days. 'Pre-launch · we'll email when
    it's ready' contradicts the actual state of the product."""
    r = client.get("/")
    assert "Pre-launch" not in r.text
    assert "we'll email when it's ready" not in r.text
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_landing_cta.py -v
```

Expected: both FAIL — the hero today serves a waitlist form and contains "Pre-launch · we'll email when it's ready".

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_landing_cta.py
git commit -m "test(landing): pin hero CTA must route to /login (red)"
```

(Failing test alone is intentional — documents the target. Task B2 turns it green.)

---

## Task B2: Replace the hero primary CTA

**Files:**
- Modify: `src/markland/web/templates/landing.html:570-595`.

- [ ] **Step 1: Edit the hero block**

In `src/markland/web/templates/landing.html`, find the block starting at line 570 (`<span class="hero-chip">`). Replace the lines through `<span class="cta-hint">Pre-launch · we'll email when it's ready</span>` with:

```html
    <span class="hero-chip">
        <span class="chip-dot" aria-hidden="true"></span>
        Public beta &middot; free during beta
    </span>

    <h1 aria-label="Shared documents for you and your agents">Shared documents<span class="period-red">.</span><br>For you <em>and</em> your agents<span class="period-blue">.</span></h1>
    <p class="lede">One markdown surface. Your agents, your teammates, and their agents — all editing the same docs via MCP.</p>
    <p class="lede" style="font-size: 0.98rem; margin-top: -1.4rem;">
      <strong>Markland is an MCP-based document publishing platform</strong> that lets AI agents like Claude Code publish, share, and grant access to markdown documents via a single tool call.
    </p>

    <form class="waitlist-form" method="get" action="/login">
        <input type="email" name="email" required placeholder="you@company.com" aria-label="Email address">
        <input type="hidden" name="source" value="hero">
        <button type="submit" class="btn primary">Sign in &amp; try it</button>
    </form>

    <p class="cta-hint" style="margin-top: 0.7rem; font-size: 0.88rem; color: var(--muted);">
      We'll email you a magic link. No password to set up.
    </p>

    <a href="/explore" class="hero-secondary-link">See a sample doc &rarr;</a>
    <p class="hero-cta" style="margin-top: 0.8rem; font-size: 0.95rem; color: var(--muted);">
      Need the install steps? <a href="/quickstart">5-step quickstart &rarr;</a>
      &nbsp;·&nbsp;
      Not ready yet? <a href="#waitlist-footer">Join the waitlist</a>
    </p>
```

- [ ] **Step 2: Add the demoted waitlist as a footer section**

Find the closing `</section>` of the hero block, then scan forward for any closing `</section>` that fits the page layout naturally (a non-hero CTA section, possibly near the FAQ — search `id="cta-section"` or `id="signup-section"` in the file). If a separate CTA section exists, add inside it a small block:

```html
<aside id="waitlist-footer" style="max-width: 32rem; margin: 2rem auto; padding: 1rem 1.25rem; border: 1px solid var(--outline); border-radius: var(--radius-lg); background: var(--surface);">
  <p style="margin: 0 0 0.4rem; color: var(--muted); font-size: 0.92rem;">Prefer to wait?</p>
  <form class="waitlist-form" method="post" action="/api/waitlist">
      <input type="email" name="email" required placeholder="you@company.com" aria-label="Email address for waitlist">
      <input type="hidden" name="source" value="footer">
      <button type="submit" class="btn">Join the waitlist</button>
  </form>
</aside>
```

If no obvious section exists, append before `</body>` near the closing footer.

- [ ] **Step 3: Verify `/login` accepts the prefilled email query param**

Check `src/markland/web/auth_routes.py` for the `/login` GET handler. If it accepts an `email` query param and prefills it into the magic-link form, you're done. If not, add it (it should be a one-line `request.query_params.get("email", "")` injected into the template context).

```bash
grep -n "def login\|/login" src/markland/web/auth_routes.py
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_landing_cta.py -v
```

Expected: both PASS.

- [ ] **Step 5: Run the broader landing/auth suites**

```bash
uv run pytest tests/test_landing_*.py tests/test_auth_routes.py tests/test_login_*.py -q
```

Expected: all green.

- [ ] **Step 6: Manual smoke against the local server**

```bash
uv run python -m markland.run_app &
sleep 2
curl -s http://localhost:8000/ | grep -E "(/login|Sign in & try it|Pre-launch)" | head -5
# Expected: /login appears, "Sign in & try it" appears, "Pre-launch" does NOT appear.
kill %1
```

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/templates/landing.html tests/test_landing_cta.py
git commit -m "feat(landing): primary hero CTA → magic-link sign-in (kill 91% bounce)"
```

- [ ] **Step 8: Deploy**

```bash
flyctl deploy --remote-only --strategy immediate
```

Expected: build + deploy succeed.

- [ ] **Step 9: Verify against prod**

```bash
curl -s https://markland.dev/ | grep -E "(/login|Sign in & try it|Pre-launch)" | head -5
```

Expected: same as Step 6 result.

---

# Track C — Content velocity (restart the cadence)

**Why:** the SEO strategy doc says brand mentions outrank backlinks 3× for AI citations; content is the ammunition. Post #1 is 24 days old; post #2 was due 2026-05-17.

## Task C1: Pick + write post #2 — "How to share Claude Code output without copy-pasting"

This is the most-direct-intent post on the SEO strategy's anchor list. It maps 1:1 to the visitor we want.

**Files:**
- Create: `src/markland/web/content/blog/share-claude-code-output.md`.

- [ ] **Step 1: Write the frontmatter + post body**

Create the file with this frontmatter (parsed by `src/markland/web/blog.py`):

```markdown
---
title: How to share Claude Code output without copy-pasting
slug: share-claude-code-output
published_at: 2026-05-30
description: Claude Code writes great markdown. Use the markland_publish MCP tool to turn it into a shareable URL in one call — no Notion, no Docs, no copy-paste.
---

The most common Claude Code workflow goes like this. You ask Claude for a
plan, a spec, a debugging report, or a "here's what changed today" summary.
Claude writes ~1,500 words of clean, well-structured markdown directly into
the terminal. You read it, like it, and then realize: how do I share this
with someone who isn't sitting at my machine?

The path most people take: copy the output, open Notion or a Google Doc,
paste, fight the formatting, fix the code blocks Notion munged, give the
doc a name, click Share, copy the link, paste it into Slack. Best case
that's three minutes of context-switching. Worst case the code blocks
break, the lists renumber, and you spend ten minutes re-formatting.

There is a better way. Install the Markland MCP server once, and
Claude Code gets a new tool — `markland_publish` — that takes the
markdown your agent just wrote, uploads it to <https://markland.dev>, and
returns a shareable URL. One tool call. No copy, no paste, no format fix.

## The 60-second install

Open Claude Code and send this message:

> Install the Markland MCP server from https://markland.dev/setup

Claude Code fetches the runbook, walks you through a one-click browser
authorization, and writes the MCP server config into `~/.claude.json`.
You'll be back in your terminal with a working `markland_publish` tool
in under a minute.

If you want the long version, the [quickstart](https://markland.dev/quickstart)
covers it step-by-step. Markland's auth uses RFC 8628 device flow —
the same primitive `gh auth login` and `vercel login` use — so you'll
recognize the pattern.

## The new workflow

Once installed, the friction drops to zero. After Claude writes the
spec / report / summary, you say:

> Publish that as a Markland doc and give me the link.

Claude calls `markland_publish` with the markdown you just generated.
Markland returns a `https://markland.dev/d/<token>` URL. You paste the
URL into Slack. Total elapsed time from "ask for the spec" to
"link in Slack": about ten seconds longer than just asking for the
spec.

Documents are private by default. The URL works for anyone you share
it with, but it's a share-token URL, not a public-index entry — search
engines and AI crawlers don't see it. If you do want a public doc, ask
Claude to publish it as public and the URL becomes `markland.dev/d/<slug>`
indexable. Default-private means you can dump a half-formed thought
into Markland and not worry about it leaking before you've polished it.

## When this beats the alternatives

Notion is great if your team lives in Notion. But Notion was built for
humans, and its block model means everything your agent writes gets
translated into Notion blocks — losing the markdown source-of-truth in
the process. If you want to round-trip the same doc through three
different agents, Markland preserves the bytes; Notion munges them.

Google Docs has the same shape: built for humans, not agents. There
is no `gdocs_publish` MCP tool (yet), and the OAuth flow to script
against Drive is non-trivial. Markland's whole point is that the
publishing surface is a single MCP tool call.

GitHub Gist works if your audience is technical and you don't mind
the GitHub login wall on the reader side. Markland docs are reachable
without an account.

## What's in the toolkit

`markland_publish` is the headline tool, but the MCP server exposes a
full set of operations Claude Code can use:

- `markland_publish` — turn markdown into a URL
- `markland_update` — edit an existing doc (with version control)
- `markland_search` — find your past docs by title or content
- `markland_grant` — give another human or agent read/edit access
- `markland_revoke` — remove access
- `markland_fork` — copy someone else's doc to your account
- `markland_list_my_agents` — see what agents have access
- ...and a few more

Full reference on the [quickstart](https://markland.dev/quickstart).

## Try it

The whole thing is free during public beta. Visit
[markland.dev](https://markland.dev), sign in with a magic link, and
the install runbook will walk Claude Code through the rest.

The next time Claude writes you a 1,500-word spec, you're ten seconds
from a shareable link, not three minutes from a fight with Notion.
```

- [ ] **Step 2: Run the blog tests to verify the new post parses + meets the SEO contract**

```bash
uv run pytest tests/test_blog.py -v
```

Expected: all PASS, including the SEO-contract tests (word-count guard 120-200 words on definition lead, meta description 130-165 chars, markdown renders).

If the meta-description length test fails: trim the `description` field to fit the 130-165 char range.

- [ ] **Step 3: Verify the post renders end-to-end**

```bash
uv run python -c "
from markland.web.blog import load_posts
posts = load_posts()
slugs = [p.slug for p in posts]
assert 'share-claude-code-output' in slugs, slugs
print('OK: post #2 loaded')
"
```

Expected: `OK: post #2 loaded`.

- [ ] **Step 4: Commit**

```bash
git add src/markland/web/content/blog/share-claude-code-output.md
git commit -m "feat(blog): post #2 — How to share Claude Code output without copy-pasting"
```

- [ ] **Step 5: Deploy**

```bash
flyctl deploy --remote-only --strategy immediate
```

- [ ] **Step 6: Verify against prod**

```bash
curl -fsS https://markland.dev/blog | grep -E "share-claude-code-output|How to share"
curl -fsS https://markland.dev/blog/share-claude-code-output | head -20
curl -fsS https://markland.dev/blog/feed.xml | grep "<entry>" | wc -l
# Expected: link visible on /blog index, full post renders, feed has 2 entries.
```

- [ ] **Step 7: Update `/llms.txt` if needed**

`/llms.txt` should pick up the new post automatically if it sources from the same `load_posts()` function. Verify:

```bash
curl -fsS https://markland.dev/llms.txt | grep "share-claude-code-output"
```

Expected: line present. If not, find where `/llms.txt` is rendered and confirm it iterates `load_posts()`.

---

# Track D — First-publish nudge for new users

**Why:** when Track B starts converting visitors to signups, the new dashboard panel makes the "now what?" moment self-serve. Without it, signups bounce a second time.

## Task D1: `user_has_owned_docs` service helper

**Files:**
- Modify: `src/markland/service/docs.py` — append helper.
- Test: `tests/test_service_docs.py` (extend) or create `tests/test_user_has_owned_docs.py`.

- [ ] **Step 1: Write the failing tests**

Append to whichever file tests `service/docs.py`. If unclear, create `tests/test_user_has_owned_docs.py`:

```python
"""service/docs.py::user_has_owned_docs — used by the dashboard
welcome panel visibility logic. Pins markland-fjd follow-up."""

from __future__ import annotations

import pytest
from markland.db import init_db
from markland.service.auth import Principal
from markland.service.docs import publish, user_has_owned_docs
from markland.service.users import create_user


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_user_has_owned_docs_false_for_new_user(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    assert user_has_owned_docs(conn, user.id) is False


def test_user_has_owned_docs_true_after_publish(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    alice = Principal(principal_id=user.id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    publish(conn, principal=alice, title="T", content="x", is_public=False)
    assert user_has_owned_docs(conn, user.id) is True


def test_user_has_owned_docs_false_for_user_with_only_grants(conn):
    """A grant on someone else's doc doesn't count as 'owned'."""
    alice = create_user(conn, email="alice@example.com", display_name="A")
    bob = create_user(conn, email="bob@example.com", display_name="B")
    # alice publishes; bob has no published docs (even if alice grants him)
    aprinc = Principal(principal_id=alice.id, principal_type="user",
                       display_name="A", is_admin=False, user_id=None)
    publish(conn, principal=aprinc, title="T", content="x", is_public=False)
    assert user_has_owned_docs(conn, bob.id) is False
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_user_has_owned_docs.py -v
```

Expected: FAIL — `user_has_owned_docs` doesn't exist.

- [ ] **Step 3: Implement the helper**

Append to `src/markland/service/docs.py`:

```python
def user_has_owned_docs(conn: sqlite3.Connection, user_id: str) -> bool:
    """True if `user_id` owns at least one document. Used by the
    dashboard welcome panel — when False, panel suggests publishing
    a first doc."""
    row = conn.execute(
        "SELECT 1 FROM documents WHERE owner_id = ? LIMIT 1",
        (user_id,),
    ).fetchone()
    return row is not None
```

- [ ] **Step 4: Run tests to verify pass**

```bash
uv run pytest tests/test_user_has_owned_docs.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/docs.py tests/test_user_has_owned_docs.py
git commit -m "feat(docs): user_has_owned_docs helper for welcome panel"
```

---

## Task D2: Welcome panel partial + dashboard wiring

**Files:**
- Create: `src/markland/web/templates/_welcome_first_publish.html`.
- Modify: `src/markland/web/templates/dashboard.html`.
- Modify: `src/markland/web/dashboard.py` — pass `show_welcome_panel: bool` and `csrf_token: str`.
- Test: `tests/test_dashboard_welcome_panel.py` (new).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_dashboard_welcome_panel.py`:

```python
"""Dashboard 'first publish' welcome panel — visibility logic.

Renders iff: signed in AND no owned docs AND no mk_dismiss_welcome=1
cookie. Mirrors the _connect_claude_code panel pattern from
docs/plans/2026-05-04-install-onboarding-options-2-4.md.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import sessions as sessions_mod
from markland.service.auth import Principal
from markland.service.docs import publish
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"
PANEL_MARKER = 'aria-label="Welcome — publish your first doc"'


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    app = create_app(
        conn, mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        c.state_alice_id = user.id
        c.state_conn = conn
        yield c


def _login(client, user_id=None):
    uid = user_id or client.state_alice_id
    cookie = sessions_mod.make_session_cookie_value(uid, secret=SECRET)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def test_panel_absent_for_anon(client):
    r = client.get("/dashboard")
    assert PANEL_MARKER not in r.text


def test_panel_present_for_signed_in_with_no_docs(client):
    _login(client)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER in r.text


def test_panel_absent_when_user_has_owned_docs(client):
    _login(client)
    alice = Principal(principal_id=client.state_alice_id,
                      principal_type="user", display_name="Alice",
                      is_admin=False, user_id=None)
    publish(client.state_conn, principal=alice,
            title="T", content="x", is_public=False)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text


def test_panel_absent_when_dismiss_cookie_set(client):
    _login(client)
    client.cookies.set("mk_dismiss_welcome", "1")
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert PANEL_MARKER not in r.text
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_dashboard_welcome_panel.py -v
```

Expected: 3 FAIL (panel doesn't exist yet).

- [ ] **Step 3: Create the partial template**

Create `src/markland/web/templates/_welcome_first_publish.html`:

```html
{# Welcome — first-publish nudge for new accounts (no owned docs).
   Mirrors the _connect_claude_code pattern: dismiss button + cookie. #}
<aside class="welcome-first-publish"
       aria-label="Welcome — publish your first doc"
       data-csrf="{{ csrf_token }}"
       style="max-width: 48rem; margin: 2rem auto; padding: 1.25rem 1.5rem; border: 1px solid var(--blue); border-radius: 8px; background: var(--surface);">
  <header style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 0.5rem;">
    <h2 style="font-size: 1.1rem; margin: 0;">Welcome to Markland</h2>
    <button class="dismiss" type="button"
            data-dismiss-welcome aria-label="Dismiss"
            style="background: none; border: none; font-size: 1.5rem; line-height: 1; cursor: pointer; color: var(--muted); padding: 0 0.25rem;">×</button>
  </header>
  <p>You're signed in. Now ask Claude Code (or any MCP-compatible agent) to publish your first doc:</p>
  <pre style="background: var(--surface-2); border: 1px solid var(--outline-hairline); border-radius: 6px; padding: 0.5rem 0.75rem; font-family: var(--font-mono); font-size: 0.85rem; margin: 0.5rem 0;"><code>Publish a markdown doc titled "Hello Markland" with some notes about a project I'm working on.</code></pre>
  <p style="color: var(--muted); font-size: 0.92rem;">
    Your doc shows up in <a href="/dashboard">your dashboard</a> with a shareable URL. Default-private — only people you grant access to can read it.
  </p>
  <p style="color: var(--muted); font-size: 0.92rem; margin-top: 0.5rem;">
    Haven't installed Markland in Claude Code yet?
    <a href="/quickstart">5-step quickstart →</a>
  </p>
</aside>

<script nonce="{{ csp_nonce }}">
(function () {
  var panel = document.querySelector('.welcome-first-publish');
  if (!panel) return;
  var dismissBtn = panel.querySelector('[data-dismiss-welcome]');
  if (!dismissBtn) return;
  dismissBtn.addEventListener('click', function () {
    var csrf = panel.getAttribute('data-csrf') || '';
    fetch('/api/me/dismiss-welcome', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrf },
      credentials: 'same-origin',
    }).then(function () { panel.remove(); });
  });
})();
</script>
```

- [ ] **Step 4: Wire visibility logic into `src/markland/web/dashboard.py`**

In `src/markland/web/dashboard.py`, locate the existing block that computes `show_connect_panel` (added by the install/onboarding Phase 2 plan). Immediately after it, add:

```python
        from markland.service.docs import user_has_owned_docs
        dismissed_welcome = request.cookies.get("mk_dismiss_welcome") == "1"
        show_welcome_panel = (
            not dismissed_welcome
            and not user_has_owned_docs(conn, user_id)
        )
```

Then in the `render_with_nav(...)` call, add the new kwargs alongside `show_connect_panel`:

```python
                show_connect_panel=show_connect_panel,
                show_welcome_panel=show_welcome_panel,
                csrf_token=csrf_token,
```

- [ ] **Step 5: Wire the partial into `dashboard.html`**

In `src/markland/web/templates/dashboard.html`, find the existing `{% if show_connect_panel %}` block and add immediately below it:

```html
{% if show_welcome_panel %}
  {% include "_welcome_first_publish.html" %}
{% endif %}
```

- [ ] **Step 6: Run tests to verify pass**

```bash
uv run pytest tests/test_dashboard_welcome_panel.py -v
```

Expected: 4 PASS.

- [ ] **Step 7: Run the broader dashboard suite to confirm no regression**

```bash
uv run pytest tests/test_dashboard*.py -q
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/markland/web/templates/_welcome_first_publish.html \
        src/markland/web/templates/dashboard.html \
        src/markland/web/dashboard.py \
        tests/test_dashboard_welcome_panel.py
git commit -m "feat(dashboard): welcome / first-publish nudge for new users"
```

---

## Task D3: Dismiss endpoint

**Files:**
- Modify: `src/markland/web/identity_routes.py` — append `/api/me/dismiss-welcome`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_identity_routes.py`:

```python
def test_dismiss_welcome_requires_auth(client):
    r = client.post("/api/me/dismiss-welcome")
    assert r.status_code == 401


def test_dismiss_welcome_requires_csrf(client):
    _login(client)
    r = client.post("/api/me/dismiss-welcome")
    assert r.status_code == 403


def test_dismiss_welcome_sets_cookie(client):
    _login(client)
    from markland.service.sessions import make_csrf_token
    csrf = make_csrf_token(client.state_alice_id, secret=SECRET)
    r = client.post(
        "/api/me/dismiss-welcome",
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 204
    assert r.cookies.get("mk_dismiss_welcome") == "1"
```

- [ ] **Step 2: Run to verify failure**

```bash
uv run pytest tests/test_identity_routes.py -v -k dismiss_welcome
```

Expected: FAIL — route doesn't exist (404).

- [ ] **Step 3: Add the route**

Append to `src/markland/web/identity_routes.py` (inside `build_router`, after the existing `/api/me/dismiss-connect-claude-code` route from PR markland-qd2):

```python
    @router.post("/api/me/dismiss-welcome")
    def api_dismiss_welcome(request: Request):
        """Dismiss the dashboard welcome / first-publish panel.
        Year-long cookie. CSRF-protected, session-required.
        Mirrors /api/me/dismiss-connect-claude-code."""
        user_id = _session_user_id(request)
        if user_id is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        csrf = request.headers.get("X-CSRF-Token", "")
        if not verify_csrf_token(csrf, user_id, secret=session_secret):
            return JSONResponse({"error": "csrf"}, status_code=403)
        resp = Response(status_code=204)
        resp.set_cookie(
            key="mk_dismiss_welcome",
            value="1",
            max_age=31_536_000,
            path="/",
            samesite="strict",
            secure=True,
            httponly=False,
        )
        return resp
```

- [ ] **Step 4: Run to verify pass**

```bash
uv run pytest tests/test_identity_routes.py -v -k dismiss_welcome
```

Expected: 3 PASS.

- [ ] **Step 5: Commit + deploy**

```bash
git add src/markland/web/identity_routes.py tests/test_identity_routes.py
git commit -m "feat(api): /api/me/dismiss-welcome dismiss endpoint"

flyctl deploy --remote-only --strategy immediate
```

Manual smoke after deploy: sign out, sign back in as a fresh-ish user (or use the test-account paths), confirm the welcome panel renders on `/dashboard`, click ×, refresh, panel stays gone.

---

# Track E — Trust gates (parallel execution; load-bearing for Track F)

Three existing plans. Execute each independently — they can run in parallel since they touch disjoint files.

## Task E1: Execute self-service deletion **Phase 1 only**

**Why Phase 1 only:** the doc-deletion UI is the customer-visible affordance that matters before launch. Account soft-delete (Phase 2) and cron purge (Phase 3) can wait until first organic signups arrive — until then nobody has an account they'd want to delete.

- [ ] **Step 1: Execute Phase 1 of `docs/plans/2026-05-04-self-service-deletion.md`** (Tasks 1.1–1.3, ~5 tasks)

Follow the plan exactly. Phase 1 is bounded: HTTP route + dashboard button + viewer button + shared modal partial. No schema changes.

- [ ] **Step 2: Verify against prod after deploy**

Sign in to `/dashboard`, click Delete on a test document, type-confirm, verify the doc is gone and the dashboard re-renders without it.

- [ ] **Step 3: Update `docs/plans/2026-05-04-self-service-deletion.md` to mark Phase 1 done**

Mark the Phase 1 checkboxes complete. Phase 2 + Phase 3 stay open.

## Task E2: Execute formal privacy policy

- [ ] **Step 1: Execute `docs/plans/2026-05-04-formal-privacy-policy.md`** (14 tasks)

- [ ] **Step 2: After Task 14 (roadmap update), the plan auto-closes itself**

## Task E3: Execute formal Terms of Service

- [ ] **Step 1: Execute `docs/plans/2026-05-04-formal-terms-of-service.md`** (17 tasks)

- [ ] **Step 2: After Task 17 (roadmap update), the plan auto-closes itself**

---

# Track F — Show HN draft (queue, don't post)

**Why draft now:** when Tracks B + C + D + E ship and the funnel is converting, you want the Show HN already written so the activation energy to post is "open Tab + click submit" — not "spend 90 minutes writing it." Drafting under no pressure produces a better post.

## Task F1: Write the Show HN draft

**Files:**
- Create: `docs/launch/2026-05-29-show-hn-draft.md`.

- [ ] **Step 1: Create the directory + file**

```bash
mkdir -p docs/launch
```

Create `docs/launch/2026-05-29-show-hn-draft.md`:

```markdown
# Show HN Draft — Markland

**Status:** Drafted 2026-05-29. NOT POSTED. Post when: Track B (homepage CRO) shipped + verified converting + Track C (post #2) live + Tracks E1-E3 (deletion Phase 1, privacy, ToS) shipped.

**Best time to post:** Tuesday-Thursday, 8-10am EST (weekday US morning).

---

## Title (max 80 chars)

Show HN: Markland – Publish markdown from your AI agent with one MCP tool call

## URL

https://markland.dev

## Body (text only — Show HN body is optional but recommended for context)

Hi HN — I built Markland because every time Claude Code wrote me a great
spec or report, I lost ten minutes copying it into Notion and fighting
the formatting. Markland is an MCP server that gives Claude Code (and
any other MCP-compatible agent — Cursor, Codex, Claude Desktop) a
`markland_publish` tool: turn the markdown your agent just wrote into
a shareable URL with one tool call.

The full toolkit is around two dozen MCP tools — publish, grant,
revoke, search, fork, update with version control, invite, list, etc.
— and the reader side is a plain HTTPS link that any browser or agent
can fetch. Documents are private by default; you can grant access to
specific humans (by email) or agents (by agent ID). Auth uses RFC 8628
device flow, same primitive `gh auth login` and `vercel login` use.

It's free during public beta. The technical writeup is on the blog:
https://markland.dev/blog/agent-native-publishing

A few specifics I expect HN to ask about:

- **What's the storage?** SQLite + Litestream backup to R2, hosted on
  Fly.io. Built for one writer plus many readers per doc; not trying
  to compete with Notion at the database-of-everything level.
- **What's the auth model?** Magic-link sign-in for humans (no
  passwords), Argon2id-hashed bearer tokens for agents, append-only
  audit log on every mutation. Pre-release security review filed 18
  findings; all 18 are shipped (P0/P1/P2/P3).
- **What about real-time?** Not yet. v1 is advisory presence (badges,
  no live updates). CRDT collaboration is on the v2 roadmap.
- **What's the business model?** Free during beta. Paid tiers
  (Free / Pro / Team / Enterprise) are designed; spec is on the
  roadmap. Won't charge per-agent — agents are first-class, not
  penalized.

It's operated by one developer (me). The privacy and security pages
are explicit about that and about what we do and don't store:
https://markland.dev/privacy, https://markland.dev/security

Code is open: https://github.com/dghiles/markland

Happy to answer questions.

— davey

---

## Canned reply: "Why not GitHub Gist / Notion / Google Docs?"

(Already covered in https://markland.dev/blog/share-claude-code-output —
quick version: Gist has the GitHub login wall on readers; Notion's
block model loses the markdown source-of-truth; Google Docs has no
agent-facing API surface. Markland's whole point is that the
publishing step is one MCP tool call from the agent that wrote the
doc, with bytes preserved exactly.)

## Canned reply: "How is this different from $X MCP server I just installed?"

(I don't know any direct competitor that combines publish + grants +
agent identities + share tokens behind a single MCP surface. If you
do, please link — I'd genuinely like to compare. The closest thing in
spirit is HackMD/markshare for human-to-human markdown sharing, but
those don't have first-class agent identities or an MCP server.)

## Canned reply: "What if I trust agent A to read but not write?"

Per-grant permissions are scoped: each grant is `view`, `edit`, or
`owner`. An agent gets exactly the permission the human granting
access chose. The recent install/onboarding work also gates the
"flip a doc public" path so an agent can't accidentally make
something public on a casually-worded prompt.

## Canned reply: "What does it cost to run, single-developer-style?"

About $30/month total: Fly.io (~$15), Resend (~free at this volume),
Cloudflare R2 backups (~free at this volume), Umami Cloud analytics
(~free at this volume), domain (~$15/year). Almost everything has a
free tier appropriate to the scale.

## Anti-pattern check

- DON'T link the blog post AND say "I wrote a post about it" — let
  HN find the post organically by clicking through.
- DON'T mention the metrics from the soak-window. The 6-users number
  is honest but will read as low even by Show HN beta standards. The
  HN audience will figure out the scale from looking at the site.
- DON'T post the same week a competing high-profile MCP server
  launches on HN. Check the front page first.
- DON'T post when you can't be at the keyboard for the next 4 hours
  to respond to comments. The first 2 hours of comments determine
  whether the post survives.
```

- [ ] **Step 2: Commit**

```bash
git add docs/launch/2026-05-29-show-hn-draft.md
git commit -m "docs(launch): Show HN draft — Markland (queue, don't post)"
```

---

# Track G — Roadmap update

## Task G1: Close out the pre-launch clean-up entry

**Files:**
- Modify: `docs/ROADMAP.md`.

- [ ] **Step 1: Move "Pre-launch clean up" from Now to Shipped, summarizing what landed**

Add at the top of the "Marketing + UX surface" Shipped section:

```markdown
- **2026-05-XX** — **Pre-launch clean up shipped.** Homepage CRO pass on `/` (primary CTA now magic-link sign-in instead of waitlist; killed the "Pre-launch · we'll email when it's ready" copy that was actively misleading 30 days post-launch). Blog post #2 live ("How to share Claude Code output without copy-pasting"). New dashboard welcome / first-publish panel for users with zero owned docs, mirrors the `_connect_claude_code` pattern (dismiss endpoint, cookie, auto-show logic). Phase 0 dogfood completed (steps 4-14). Self-service deletion Phase 1 (doc-delete UI) shipped — Phase 2/3 remain queued. Formal privacy policy and Terms of Service shipped. Show HN draft queued at `docs/launch/2026-05-29-show-hn-draft.md` — post when funnel evidence confirms conversion is fixed. Plan: `docs/plans/2026-05-29-pre-launch-cleanup.md`.
```

(Date stamp the actual ship date when this task runs.)

- [ ] **Step 2: Remove the Now-lane entry**

Delete the `Pre-launch clean up` bullet from the Now lane.

- [ ] **Step 3: Commit + push**

```bash
git add docs/ROADMAP.md
git commit -m "docs(roadmap): pre-launch clean up shipped"
git push origin main
```

---

## Sequencing

Optimal order, with parallelism where possible:

```
Day 1:   Track A (Phase 0 dogfood finish) — validate flow works
Day 2:   Track B (homepage CRO) — fix the leak
         Track F1 (Show HN draft) — write while leak-fix deploys
Day 3:   Track C (blog post #2) — restart content velocity
         Track D (welcome panel) — capture converting users
Day 4-7: Tracks E1, E2, E3 in parallel — trust gates
Day 8:   Track G (roadmap close-out)
         [DECIDE] post Show HN this week or wait one more cycle?
```

Track A blocks Track B (don't optimize a broken flow). Tracks B and F1 can ship in the same day. Tracks C and D can ship in parallel. Tracks E1/E2/E3 are independent of each other and of B/C/D — start them as soon as Track A is done.

## What this plan deliberately does NOT include

- **Account deletion (Self-Service Deletion Phase 2/3)** — out of scope for pre-launch. Doc deletion (Phase 1) is what users notice; account deletion is the gate that becomes important when retention starts mattering. Ship after the first 25 organic signups.
- **`/status` page + incident-response runbook (operational maturity)** — Show HN audience will ask about this; honest answer is "single developer, here's the status page" — but a stub `/status` is worse than no `/status`. Defer until we have ≥1 month of uptime numbers worth publishing.
- **Visibility-change safety rail** — still `[needs brainstorm]`. Real but not Show-HN-critical.
- **Monetization** — explicitly demoted. Stripe wiring with no converting funnel is the wrong order of operations.
- **Sharpen agent-to-agent positioning** — partly addressed by post #2 mentioning the agent-to-agent toolkit; full brainstorm deferred.
- **Claude Desktop + Cowork install paths** — still `[needs brainstorm]`. The footnote link on the existing `_connect_claude_code` panel is good enough for Show HN; full multi-client surface comes after.

---

## Self-review checklist

- Each track ends with a `git commit` and a deploy where relevant ✅
- TDD shape preserved for novel work (Tracks B, C, D); existing plans referenced for repeated work (Tracks A, E) ✅
- Heading text in `test_dashboard_welcome_panel.py::PANEL_MARKER` matches the partial template's `aria-label` exactly (`"Welcome — publish your first doc"`) ✅
- No "TBD" / "TODO" / "fill in" placeholders ✅
- Sequencing reflects dependency: dogfood → leak fix → content + nudge → trust gates → close-out ✅
- Show HN draft is QUEUED, not posted — explicit gating language in F1 ✅
- Anti-CRO-mistake check: Track B keeps a waitlist affordance for users who actually want it; doesn't delete the primitive, just demotes it ✅
- Track G's date stamp is `XX` — executor fills the actual ship date ✅
