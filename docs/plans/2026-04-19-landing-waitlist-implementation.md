# Landing Waitlist & Positioning Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the shipped landing page at `/` to capture pre-launch email signups and sharpen positioning, per `docs/specs/2026-04-18-landing-waitlist-design.md`.

**Architecture:** Add a `waitlist` SQLite table and a `POST /api/waitlist` route. Modify `landing.html` to swap the hero CTA for an email form, insert three new sections (Before/After, How-it-works, Get early access CTA), and trim the gallery cap from 8 to 4. No new Python dependencies, no new JavaScript framework, no changes to the design token system in `base.html`.

**Tech Stack:** FastAPI, Jinja2, SQLite (stdlib), Pytest, FastAPI TestClient.

**Note on commits:** The Markland repo is currently not a git repository. `git add` / `git commit` steps in this plan are written as if git is initialized. If it is not, either initialize git first (`git init && git add -A && git commit -m "baseline"`) or skip the commit steps and track progress via the checkboxes.

**Note on existing tests:** `tests/test_web.py::test_landing_renders_empty` asserts the current copy (`"Your agent writes"`, `"first agent-authored docs"`). Task 5 updates this test as part of the hero change — do not skip it.

---

## File Structure

### Files modified

| Path | Responsibility after changes |
|---|---|
| `src/markland/db.py` | Add `waitlist` table + `add_waitlist_email()` function |
| `src/markland/web/app.py` | Add `POST /api/waitlist` route + `_valid_email` helper; update `GET /` to accept `signup` query param and pass `limit=4` to gallery query |
| `src/markland/web/templates/landing.html` | Swap hero CTA for email form; add Before/After, How-it-works, and Get-early-access sections; render signup-state chips |
| `tests/test_db.py` | Add waitlist tests |
| `tests/test_web.py` | Add waitlist-route tests; update existing `test_landing_renders_empty` for new hero copy |
| `scripts/smoke_test.py` | Add waitlist POST + signup chip assertion |

### Files created

None. Every change is an edit to an existing file.

### Files untouched

`src/markland/web/templates/base.html`, `explore.html`, `document.html`; all MCP server / tool code; all existing DB functions operating on `documents`, `users`, `tokens`.

---

## Task 1: Add waitlist table to init_db

**Files:**
- Modify: `src/markland/db.py` (inside `init_db`, after the existing `tokens` table block, before `conn.commit()`)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db.py`:

```python
def test_init_db_creates_waitlist_table(db):
    # PRAGMA table_info returns an empty list for non-existent tables.
    rows = db.execute("PRAGMA table_info(waitlist)").fetchall()
    assert rows, "waitlist table should exist after init_db"
    columns = {row[1] for row in rows}
    assert columns == {"email", "created_at", "source"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_db.py::test_init_db_creates_waitlist_table -v`
Expected: FAIL with `AssertionError: waitlist table should exist after init_db`.

- [ ] **Step 3: Add the table**

Edit `src/markland/db.py` inside the `init_db` function, after the two `conn.execute(...)` blocks that create the `users` and `tokens` tables, and before `conn.commit()`. Insert:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS waitlist (
            email      TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            source     TEXT
        )
    """)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_db.py::test_init_db_creates_waitlist_table -v`
Expected: PASS.

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

Run: `uv run pytest tests/ -q`
Expected: all existing tests still pass; one new PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/db.py tests/test_db.py
git commit -m "feat(db): add waitlist table to init_db"
```

---

## Task 2: Add add_waitlist_email function

**Files:**
- Modify: `src/markland/db.py` (append to end of file)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_db.py`:

```python
def test_add_waitlist_email_inserts_new_row(db):
    from markland.db import add_waitlist_email

    inserted = add_waitlist_email(db, "ada@example.com", source="hero")
    assert inserted is True

    row = db.execute(
        "SELECT email, source, created_at FROM waitlist WHERE email = ?",
        ("ada@example.com",),
    ).fetchone()
    assert row is not None
    assert row[0] == "ada@example.com"
    assert row[1] == "hero"
    assert row[2]  # created_at is non-empty


def test_add_waitlist_email_is_idempotent_on_duplicate(db):
    from markland.db import add_waitlist_email

    first = add_waitlist_email(db, "ada@example.com", source="hero")
    second = add_waitlist_email(db, "ada@example.com", source="cta-section")
    assert first is True
    assert second is False

    count = db.execute("SELECT COUNT(*) FROM waitlist").fetchone()[0]
    assert count == 1

    # Original source preserved (INSERT OR IGNORE doesn't overwrite).
    source = db.execute("SELECT source FROM waitlist WHERE email = ?", ("ada@example.com",)).fetchone()[0]
    assert source == "hero"


def test_add_waitlist_email_accepts_null_source(db):
    from markland.db import add_waitlist_email

    inserted = add_waitlist_email(db, "lovelace@example.com")
    assert inserted is True

    source = db.execute(
        "SELECT source FROM waitlist WHERE email = ?", ("lovelace@example.com",)
    ).fetchone()[0]
    assert source is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_db.py -k "waitlist_email" -v`
Expected: 3 FAIL with `ImportError: cannot import name 'add_waitlist_email'`.

- [ ] **Step 3: Implement the function**

`src/markland/db.py` already imports `Document` from `markland.models`. Add this at the top of the file (line 4 area), after `from pathlib import Path`:

```python
from datetime import datetime, timezone
```

Then append to the end of `src/markland/db.py`:

```python
def add_waitlist_email(
    conn: sqlite3.Connection,
    email: str,
    source: str | None = None,
) -> bool:
    """
    Insert email into waitlist. Returns True if inserted, False if already present.
    Uses INSERT OR IGNORE so duplicate submits are idempotent.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT OR IGNORE INTO waitlist (email, created_at, source) VALUES (?, ?, ?)",
        (email, created_at, source),
    )
    conn.commit()
    return cur.rowcount > 0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_db.py -k "waitlist_email" -v`
Expected: 3 PASS.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/db.py tests/test_db.py
git commit -m "feat(db): add add_waitlist_email function with idempotent insert"
```

---

## Task 3: Add _valid_email helper and POST /api/waitlist route

**Files:**
- Modify: `src/markland/web/app.py` (inside `create_app`, after the existing `GET /` and `GET /explore` routes; add `_valid_email` at module scope near `_load_mcp_snippet`)
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
def test_waitlist_post_happy_path(client):
    response = client.post(
        "/api/waitlist",
        data={"email": "ada@example.com", "source": "hero"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?signup=ok"


def test_waitlist_post_invalid_email_redirects_to_invalid(client):
    response = client.post(
        "/api/waitlist",
        data={"email": "not-an-email", "source": "hero"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?signup=invalid"


def test_waitlist_post_duplicate_still_redirects_to_ok(client):
    client.post("/api/waitlist", data={"email": "ada@example.com"}, follow_redirects=False)
    response = client.post(
        "/api/waitlist",
        data={"email": "ada@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?signup=ok"


def test_waitlist_post_missing_email_returns_422(client):
    # FastAPI's Form(...) raises a 422 for missing required fields.
    response = client.post("/api/waitlist", data={}, follow_redirects=False)
    assert response.status_code == 422


def test_waitlist_post_lowercases_and_strips_email(client):
    response = client.post(
        "/api/waitlist",
        data={"email": "  Ada@Example.COM  "},
        follow_redirects=False,
    )
    assert response.status_code == 303
    # Confirm the canonical form was stored via a duplicate submit.
    second = client.post(
        "/api/waitlist",
        data={"email": "ada@example.com"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    assert second.headers["location"] == "/?signup=ok"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -k "waitlist_post" -v`
Expected: 5 FAIL — the `/api/waitlist` route does not exist, so all POSTs return 405 or 404.

- [ ] **Step 3: Add the email-validation helper**

Edit `src/markland/web/app.py`. Add `import re` to the imports (if not already present), and add this after the `_load_mcp_snippet` function at module scope:

```python
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _valid_email(email: str) -> bool:
    return 3 <= len(email) <= 254 and bool(_EMAIL_RE.match(email))
```

- [ ] **Step 4: Add the route**

Update the imports at the top of `src/markland/web/app.py`:

```python
from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
```

Update the `from markland.db import (...)` block to include `add_waitlist_email`:

```python
from markland.db import (
    add_waitlist_email,
    get_document_by_token,
    list_featured_and_recent_public,
    list_public_documents,
)
```

Inside `create_app`, after the existing `view_document` route handler and before the `app.include_router(build_auth_router(...))` call, add:

```python
    @app.post("/api/waitlist")
    def join_waitlist(
        email: str = Form(...),
        source: str | None = Form(None),
    ):
        normalized = email.strip().lower()
        if not _valid_email(normalized):
            return RedirectResponse("/?signup=invalid", status_code=303)
        add_waitlist_email(db_conn, normalized, source)
        return RedirectResponse("/?signup=ok", status_code=303)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -k "waitlist_post" -v`
Expected: 5 PASS.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/app.py tests/test_web.py
git commit -m "feat(web): add POST /api/waitlist route"
```

---

## Task 4: Update GET / route to accept signup param and reduce gallery cap

**Files:**
- Modify: `src/markland/web/app.py` (inside `create_app`, the `landing()` handler around lines 99–105)
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
def test_landing_passes_signup_param_to_template(client):
    response = client.get("/?signup=ok")
    assert response.status_code == 200
    assert "signup=ok" not in response.text  # we read the param, not echo it
    # Will be asserted more concretely in Task 5 once the chip is rendered.


def test_landing_signup_param_is_whitelisted(client):
    # Bogus values should be ignored; the page should still render normally.
    response = client.get("/?signup=xyz")
    assert response.status_code == 200
    assert "xyz" not in response.text


def test_landing_gallery_caps_at_four(tmp_path):
    from markland.db import init_db, insert_document
    from markland.web.app import create_app

    db_path = tmp_path / "cap.db"
    conn = init_db(db_path)
    # Seed 6 public docs — pre-change default would show 6 (all), new default shows 4.
    for i in range(6):
        insert_document(
            conn,
            doc_id=f"d{i}",
            title=f"Doc {i}",
            content=f"Body {i}",
            share_token=f"tok{i}",
            is_public=True,
        )
    app = create_app(conn)
    tc = TestClient(app)

    response = tc.get("/")
    assert response.status_code == 200
    # Titles Doc 0..3 must appear; Doc 4/5 must not (ordered by updated_at DESC —
    # all inserted in the same millisecond, so the query ordering is stable by
    # insertion order reversed; we only assert count, not which four).
    visible = sum(1 for i in range(6) if f"Doc {i}" in response.text)
    assert visible == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_web.py -k "signup_param or gallery_caps" -v`
Expected: `test_landing_gallery_caps_at_four` FAILs (visible == 6, not 4). The two `signup` tests pass trivially because the handler ignores the param today.

- [ ] **Step 3: Update the landing handler**

Edit `src/markland/web/app.py`. Replace the existing `landing()` handler:

```python
    @app.get("/", response_class=HTMLResponse)
    def landing():
        docs = list_featured_and_recent_public(db_conn, limit=8)
        cards = [_doc_to_card(d) for d in docs]
        return HTMLResponse(
            landing_tpl.render(docs=cards, mcp_config_json=mcp_snippet_json)
        )
```

with:

```python
    @app.get("/", response_class=HTMLResponse)
    def landing(signup: str | None = None):
        docs = list_featured_and_recent_public(db_conn, limit=4)
        cards = [_doc_to_card(d) for d in docs]
        signup_state = signup if signup in ("ok", "invalid") else None
        return HTMLResponse(
            landing_tpl.render(
                docs=cards,
                mcp_config_json=mcp_snippet_json,
                signup=signup_state,
            )
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -k "signup_param or gallery_caps" -v`
Expected: all 3 PASS.

- [ ] **Step 5: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green. (The existing `test_landing_renders_empty` still passes because the hero copy is unchanged at this point.)

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/app.py tests/test_web.py
git commit -m "feat(web): signup query param + gallery cap 8->4"
```

---

## Task 5: Update the hero — swap CTA for email form and add signup chip

This task is larger than earlier ones because it combines template copy changes with CSS additions. Broken into sub-steps.

**Files:**
- Modify: `src/markland/web/templates/landing.html` (`{% block head_extra %}` CSS and the `<section class="hero">` markup)
- Modify: `tests/test_web.py` — update the existing `test_landing_renders_empty` for the new copy, add hero-form assertions

- [ ] **Step 1: Update the existing `test_landing_renders_empty` and add new hero tests**

In `tests/test_web.py`, replace the existing `test_landing_renders_empty` function with:

```python
def test_landing_renders_empty(client):
    response = client.get("/")
    assert response.status_code == 200
    # New tagline copy
    assert "Your agent publishes" in response.text
    assert "You share the link" in response.text
    # Signature period accents preserved
    assert "period-red" in response.text
    assert "period-blue" in response.text
    # Empty gallery state still appears
    assert "Nothing yet." in response.text


def test_landing_hero_has_waitlist_form(client):
    response = client.get("/")
    assert response.status_code == 200
    # Form posts to the waitlist endpoint
    assert 'action="/api/waitlist"' in response.text
    # Primary CTA copy
    assert ">Get started<" in response.text
    # Hidden source field for the hero form
    assert 'name="source"' in response.text
    assert 'value="hero"' in response.text


def test_landing_signup_ok_renders_success_chip(client):
    response = client.get("/?signup=ok")
    assert response.status_code == 200
    assert "You&#39;re on the list" in response.text or "You're on the list" in response.text


def test_landing_signup_invalid_renders_error_chip(client):
    response = client.get("/?signup=invalid")
    assert response.status_code == 200
    assert "That doesn&#39;t look like a valid email" in response.text or "That doesn't look like a valid email" in response.text


def test_landing_no_signup_param_no_chip(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "You're on the list" not in response.text
    assert "That doesn't look like a valid email" not in response.text
```

Run: `uv run pytest tests/test_web.py -k "landing_renders_empty or hero_has_waitlist_form or signup_ok_renders or signup_invalid_renders or no_signup_param" -v`

Expected: all 5 FAIL — the hero still shows old copy, no form exists, no chip rendering.

- [ ] **Step 2: Add CSS for the email form and signup chip**

Edit `src/markland/web/templates/landing.html`. Inside `{% block head_extra %}`, after the existing `.cta-hint { ... }` block (around line 92), insert:

```css
        /* --- Waitlist email form (hero + cta-section) --- */
        .waitlist-form {
            display: inline-flex;
            align-items: stretch;
            gap: 0.5rem;
            flex-wrap: wrap;
            justify-content: center;
            margin: 0;
        }
        .waitlist-form input[type="email"] {
            min-width: 280px;
            padding: 0.85rem 1.15rem;
            border-radius: var(--radius-pill);
            border: 1.5px solid var(--outline);
            background: var(--surface);
            color: var(--text);
            font-family: var(--font-display);
            font-size: 0.98rem;
            transition: border-color 0.18s ease;
        }
        .waitlist-form input[type="email"]::placeholder {
            color: var(--muted);
            font-family: var(--font-mono);
            font-size: 0.92rem;
        }
        .waitlist-form input[type="email"]:focus {
            outline: none;
            border-color: var(--text);
        }
        .hero-secondary-link {
            display: inline-block;
            margin-top: 1.1rem;
            font-family: var(--font-display);
            font-size: 0.92rem;
            color: var(--muted);
            text-decoration: none;
            border-bottom: 1px solid var(--outline-hairline);
            padding-bottom: 2px;
            transition: border-color 0.18s ease, color 0.18s ease;
        }
        .hero-secondary-link:hover {
            color: var(--text);
            border-bottom-color: var(--text);
        }

        /* --- Signup-state chip --- */
        .signup-chip {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.4rem 0.9rem;
            border: 1.5px solid var(--outline);
            border-radius: var(--radius-pill);
            font-family: var(--font-mono);
            font-size: 0.78rem;
            color: var(--text-2);
            letter-spacing: 0.04em;
            margin-bottom: 1.2rem;
        }
        .signup-chip::before {
            content: '';
            display: inline-block;
            width: 0.5rem;
            height: 0.5rem;
            border-radius: 50%;
        }
        .signup-chip.ok::before { background: var(--green); }
        .signup-chip.err::before { background: var(--red); }
```

- [ ] **Step 3: Replace the hero markup**

Edit `src/markland/web/templates/landing.html`. Replace the entire `<section class="hero">...</section>` block (lines 304–318 in the current file — from `<section class="hero">` through `</section>` immediately before the Why-Markland section) with:

```html
<section class="hero">
    {% if signup == "ok" %}
    <div class="signup-chip ok">You're on the list. We'll be in touch.</div>
    {% elif signup == "invalid" %}
    <div class="signup-chip err">That doesn't look like a valid email.</div>
    {% endif %}

    <span class="hero-chip">
        <span class="chip-dot" aria-hidden="true"></span>
        Agent-native publishing &middot; v0.1
    </span>

    <h1>Your agent publishes<span class="period-red">.</span><br>You share the link<span class="period-blue">.</span></h1>
    <p class="lede">Markdown from your agent, hosted and shareable in one MCP call. No copy-paste, no editor.</p>

    <form class="waitlist-form" method="post" action="/api/waitlist">
        <input type="email" name="email" required placeholder="you@company.com" aria-label="Email address">
        <input type="hidden" name="source" value="hero">
        <button type="submit" class="btn primary">Get started</button>
    </form>

    <a href="/explore" class="hero-secondary-link">See a sample doc &rarr;</a>
    <span class="cta-hint">Pre-launch &middot; we'll email when it's ready</span>
</section>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py -k "landing_renders_empty or hero_has_waitlist_form or signup_ok_renders or signup_invalid_renders or no_signup_param" -v`
Expected: all 5 PASS.

- [ ] **Step 5: Manual smoke check**

Run the web server:

```bash
uv run python src/markland/run_web.py
```

Open http://127.0.0.1:8950 in a browser. Verify:
- Headline reads `Your agent publishes.` / `You share the link.` with red and blue periods.
- Email form appears with a white pill `Get started` button.
- Submitting a valid email redirects to `/?signup=ok` and the green chip renders above the hero.
- Submitting `not-an-email` redirects to `/?signup=invalid` and the red chip renders.
- `See a sample doc →` link points to `/explore`.

Stop the server (Ctrl-C).

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/templates/landing.html tests/test_web.py
git commit -m "feat(landing): hero email form + signup-state chip"
```

---

## Task 6: Add Before/After section

**Files:**
- Modify: `src/markland/web/templates/landing.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
def test_landing_has_before_after_section(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "THE OLD WAY VS. MARKLAND" in response.text or "The old way vs. Markland" in response.text.lower()
    assert "Stop copy-pasting your agent" in response.text
    # Both asymmetric bodies present
    assert "~2 min of manual work" in response.text
    assert "~3 seconds" in response.text
    # CTA anchors to the how-it-works section
    assert 'href="#how-it-works"' in response.text
```

Run: `uv run pytest tests/test_web.py::test_landing_has_before_after_section -v`
Expected: FAIL.

- [ ] **Step 2: Add CSS for the before/after 2-up**

Edit `src/markland/web/templates/landing.html`. Inside `{% block head_extra %}`, after the `.nav-card .btn { ... }` block (around line 214), insert:

```css
        /* --- Before / After 2-up (reuses nav-card sizing) --- */
        .beforeafter {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1rem;
        }
        .beforeafter .card-tile {
            background: var(--surface);
            border: 1.5px solid var(--outline);
            border-radius: var(--radius-xl);
            padding: 2.2rem 2rem 2rem;
            min-height: 320px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: border-color 0.18s ease, transform 0.18s ease;
        }
        .beforeafter .card-tile:hover {
            border-color: var(--text);
            transform: translateY(-3px);
        }
        .beforeafter .num {
            display: inline-block;
            font-family: var(--font-mono);
            font-size: 0.78rem;
            font-weight: 500;
            letter-spacing: 0.1em;
            margin-bottom: 0.9rem;
        }
        .beforeafter .tile-before .num { color: var(--red); }
        .beforeafter .tile-after .num { color: var(--green); }
        .beforeafter ul {
            list-style: none;
            padding: 0;
            margin: 0 0 1.2rem;
        }
        .beforeafter li {
            font-family: var(--font-display);
            font-size: 1rem;
            line-height: 1.45;
            color: var(--text-2);
            padding: 0.15rem 0;
        }
        .beforeafter .tile-meta {
            font-family: var(--font-mono);
            font-size: 0.74rem;
            color: var(--muted);
            letter-spacing: 0.05em;
            padding-top: 0.8rem;
            border-top: 1px solid var(--outline-hairline);
        }
        .beforeafter .tile-after .tile-cta {
            margin-top: 1rem;
            align-self: flex-start;
        }
        .section-eyebrow.eb-blue::before { background: var(--blue); }
```

- [ ] **Step 3: Add the Before/After section markup**

Edit `src/markland/web/templates/landing.html`. Insert the following new `<section>` block immediately after the existing "Why Markland" pillars section (closing `</section>` tag around line 342 — right before the existing `<section class="section">` that contains the "Get started" nav cards):

```html
<section class="section" id="before-after">
    <div class="section-head">
        <div class="section-eyebrow eb-blue">The old way vs. Markland</div>
        <h2 class="section-title">Stop copy-pasting your agent's work.</h2>
    </div>
    <div class="beforeafter">
        <div class="card-tile tile-before">
            <div>
                <span class="num">01 Before</span>
                <ul>
                    <li>Your agent writes markdown.</li>
                    <li>You copy it out.</li>
                    <li>You open Notion or Docs.</li>
                    <li>You paste.</li>
                    <li>You fix the formatting.</li>
                    <li>You share the link.</li>
                </ul>
            </div>
            <div class="tile-meta">~2 min of manual work</div>
        </div>
        <div class="card-tile tile-after">
            <div>
                <span class="num">02 After</span>
                <ul>
                    <li>Your agent writes markdown.</li>
                    <li>Your agent publishes it.</li>
                    <li>You get a shareable link.</li>
                </ul>
                <a href="#how-it-works" class="btn tile-cta">See the MCP call &rarr;</a>
            </div>
            <div class="tile-meta">~3 seconds</div>
        </div>
    </div>
</section>
```

Note the new eyebrow class `eb-blue` overrides the default green-dot behavior inherited from `.section-eyebrow::before`. Because CSS specificity between `.section-eyebrow::before` and `.section-eyebrow.eb-blue::before` is equal and the later-declared rule wins, the `eb-blue` dot will render blue. (If you prefer explicit override, you can add `!important` to the background, but it is unnecessary here — the CSS file is single-origin.)

- [ ] **Step 4: Add responsive collapse at 960px**

Edit `src/markland/web/templates/landing.html`. In the existing `@media (max-width: 960px) { ... }` block near the bottom of `{% block head_extra %}` (around line 292–296), add:

```css
            .beforeafter { grid-template-columns: 1fr; }
```

Final state of that block should look like:

```css
        @media (max-width: 960px) {
            .cards { column-count: 2; }
            .pillars { grid-template-columns: 1fr; }
            .nav-cards { grid-template-columns: 1fr; }
            .beforeafter { grid-template-columns: 1fr; }
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py::test_landing_has_before_after_section -v`
Expected: PASS.

- [ ] **Step 6: Manual smoke check**

Run the web server:

```bash
uv run python src/markland/run_web.py
```

Open http://127.0.0.1:8950. Verify:
- New section appears between "Why Markland" and "Get started".
- Left tile shows `01 Before` in red, 6 steps, `~2 min of manual work` meta.
- Right tile shows `02 After` in green, 3 steps, ghost `See the MCP call →` button, `~3 seconds` meta.
- Clicking the After-tile button scrolls to `#how-it-works` (will not exist until Task 7 — for now the click will jump to top of page, which is acceptable).

Stop the server.

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/markland/web/templates/landing.html tests/test_web.py
git commit -m "feat(landing): before/after section"
```

---

## Task 7: Add How-it-works (MCP snippet) section

**Files:**
- Modify: `src/markland/web/templates/landing.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
def test_landing_has_how_it_works_section(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="how-it-works"' in response.text
    assert "HOW IT WORKS" in response.text or "How it works" in response.text
    assert "One MCP call. One link." in response.text
    # The result state copy
    assert ">Published<" in response.text
    # A result meta phrase
    assert "2,340 words" in response.text
```

Run: `uv run pytest tests/test_web.py::test_landing_has_how_it_works_section -v`
Expected: FAIL.

- [ ] **Step 2: Add CSS for the split code/result card**

Edit `src/markland/web/templates/landing.html`. Inside `{% block head_extra %}`, after the `.beforeafter` CSS block from Task 6, insert:

```css
        /* --- How it works split card --- */
        .howto {
            background: var(--surface);
            border: 1.5px solid var(--outline);
            border-radius: var(--radius-lg);
            overflow: hidden;
            display: grid;
            grid-template-columns: 1.05fr 1fr;
        }
        .howto .howto-code {
            background: #000;
            padding: 1.6rem 1.8rem;
            border-right: 1px solid var(--outline-hairline);
            font-family: var(--font-mono);
            font-size: 0.88rem;
            line-height: 1.65;
            color: var(--text-2);
            white-space: pre;
            overflow-x: auto;
        }
        .howto .howto-code .tok-comment { color: var(--muted); font-style: italic; }
        .howto .howto-code .tok-keyword { color: var(--red); }
        .howto .howto-code .tok-string  { color: var(--green); }
        .howto .howto-code .tok-number  { color: var(--yellow); }
        .howto .howto-code .tok-name    { color: var(--blue); }
        .howto .howto-result {
            padding: 2rem 1.8rem;
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 1rem;
        }
        .howto .result-status {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            font-family: var(--font-display);
            font-weight: 700;
            font-size: 1.05rem;
            color: var(--text);
        }
        .howto .result-status::before {
            content: '';
            display: inline-block;
            width: 0.55rem;
            height: 0.55rem;
            border-radius: 50%;
            background: var(--green);
        }
        .howto .result-meta {
            font-family: var(--font-display);
            font-size: 0.95rem;
            color: var(--muted);
            line-height: 1.5;
        }
        .howto .result-link-row {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.55rem 0.9rem 0.55rem 1.1rem;
            border-radius: var(--radius-pill);
            border: 1.5px solid var(--outline);
            background: var(--surface-2);
            color: var(--text);
            font-family: var(--font-mono);
            font-size: 0.88rem;
            max-width: fit-content;
        }
        .howto .result-link-row button {
            all: unset;
            cursor: default;
            padding: 0.15rem 0.6rem;
            border-radius: var(--radius-pill);
            border: 1px solid var(--outline);
            color: var(--text-2);
            font-family: var(--font-display);
            font-size: 0.82rem;
        }
        .section-eyebrow.eb-green::before { background: var(--green); }
```

- [ ] **Step 3: Add the How-it-works section markup**

Edit `src/markland/web/templates/landing.html`. Insert this new `<section>` block immediately after the Before/After section added in Task 6 (and before the existing "Get started" nav-cards section):

```html
<section class="section" id="how-it-works">
    <div class="section-head">
        <div class="section-eyebrow eb-green">How it works</div>
        <h2 class="section-title">One MCP call. One link.</h2>
    </div>
    <div class="howto">
        <div class="howto-code"><span class="tok-comment"># In your MCP client config:</span>
{
  <span class="tok-string">"markland"</span>: {
    <span class="tok-string">"command"</span>: <span class="tok-string">"uvx"</span>,
    <span class="tok-string">"args"</span>: [<span class="tok-string">"--with"</span>, <span class="tok-string">"mcp[cli]"</span>, <span class="tok-string">"mcp"</span>, <span class="tok-string">"run"</span>, <span class="tok-string">"markland"</span>]
  }
}

<span class="tok-comment"># Then your agent just:</span>
<span class="tok-name">markland_publish</span>(<span class="tok-name">content</span>)</div>
        <div class="howto-result">
            <span class="result-status">Published</span>
            <p class="result-meta">Your architecture notes &middot; 2,340 words &middot; 3m read</p>
            <div class="result-link-row">
                <span>mkl.to/a7f2-x</span>
                <button type="button" tabindex="-1">Copy link &rarr;</button>
            </div>
        </div>
    </div>
</section>
```

**Whitespace in the code block is load-bearing** — `.howto-code` uses `white-space: pre`, so the code block must remain as-is without re-indentation by any formatter. If your editor auto-indents the interior of `<div class="howto-code">`, turn it off for this block or your code panel will have leading spaces on every line.

- [ ] **Step 4: Add responsive collapse at 720px**

Edit `src/markland/web/templates/landing.html`. Below the existing `@media (max-width: 560px) { ... }` block, add a new media query:

```css
        @media (max-width: 720px) {
            .howto { grid-template-columns: 1fr; }
            .howto .howto-code { border-right: none; border-bottom: 1px solid var(--outline-hairline); }
        }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py::test_landing_has_how_it_works_section -v`
Expected: PASS.

Run: `uv run pytest tests/test_web.py::test_landing_has_before_after_section -v`
Expected: PASS (the `href="#how-it-works"` anchor now has a target).

- [ ] **Step 6: Manual smoke check**

Run: `uv run python src/markland/run_web.py`

Open http://127.0.0.1:8950. Verify:
- New section `HOW IT WORKS` eyebrow (green dot) + `One MCP call. One link.` title below Before/After.
- Left panel is pure black, showing code with colored tokens: comment muted italic, strings green, function name `markland_publish` blue.
- Right panel shows `Published` with a green dot, the meta line, and a mono pill with `mkl.to/a7f2-x` and a `Copy link →` button.
- Clicking the `See the MCP call →` button in the After tile scrolls smoothly (or jumps) to this section.

Stop the server.

- [ ] **Step 7: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/markland/web/templates/landing.html tests/test_web.py
git commit -m "feat(landing): how-it-works section with MCP snippet + result card"
```

---

## Task 8: Add Get early access CTA section

**Files:**
- Modify: `src/markland/web/templates/landing.html`
- Test: `tests/test_web.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_web.py`:

```python
def test_landing_has_get_early_access_section(client):
    response = client.get("/")
    assert response.status_code == 200
    # Eyebrow and title
    assert "GET EARLY ACCESS" in response.text or "Get early access" in response.text
    assert "Be the first to publish" in response.text
    # A second email form exists with source=cta-section
    assert response.text.count('action="/api/waitlist"') >= 2
    assert 'value="cta-section"' in response.text
    # Repeats the primary CTA copy
    assert response.text.count(">Get started<") >= 2
```

Run: `uv run pytest tests/test_web.py::test_landing_has_get_early_access_section -v`
Expected: FAIL.

- [ ] **Step 2: Add CSS for the CTA section layout**

Edit `src/markland/web/templates/landing.html`. Inside `{% block head_extra %}`, after the `.howto` CSS block, insert:

```css
        /* --- Get early access (centered CTA, no container card) --- */
        .cta-center {
            text-align: center;
            padding: 3rem 0 1rem;
        }
        .cta-center .section-eyebrow {
            justify-content: center;
        }
        .cta-center .section-title {
            margin: 0 auto 1rem;
            max-width: 26ch;
        }
        .cta-center .cta-subtext {
            max-width: 48ch;
            margin: 0 auto 1.6rem;
            font-size: 1rem;
            line-height: 1.55;
            color: var(--muted);
        }
        .section-eyebrow.eb-red::before { background: var(--red); }
```

Note `.section-eyebrow` uses `display: inline-flex` and the `::before` dot is the first flex item. Centering the eyebrow itself requires the parent to center it — the `.cta-center .section-eyebrow { justify-content: center; }` rule sets the dot + text to center within the inline-flex. You may also need to give the container `text-align: center` which is already applied to `.cta-center`.

- [ ] **Step 3: Add the CTA section markup**

Edit `src/markland/web/templates/landing.html`. Insert this new `<section>` immediately after the How-it-works section from Task 7 (and before the existing "Get started" nav-cards section — that section will remain unchanged):

```html
<section class="section cta-center">
    <div class="section-eyebrow eb-red">Get early access</div>
    <h2 class="section-title">Be the first to publish.</h2>
    <p class="cta-subtext">We'll email you when hosted Markland is live, with install instructions and your early access link.</p>

    <form class="waitlist-form" method="post" action="/api/waitlist">
        <input type="email" name="email" required placeholder="you@company.com" aria-label="Email address">
        <input type="hidden" name="source" value="cta-section">
        <button type="submit" class="btn primary">Get started</button>
    </form>
    <span class="cta-hint">No spam &middot; we'll email when it's ready</span>
</section>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_web.py::test_landing_has_get_early_access_section -v`
Expected: PASS.

- [ ] **Step 5: Manual smoke check**

Run: `uv run python src/markland/run_web.py`

Open http://127.0.0.1:8950. Verify:
- New centered CTA section appears between How-it-works and the "Get started" nav-cards section.
- Eyebrow has a red dot.
- Title is `Be the first to publish.`.
- Email form matches the hero form visually.
- Submitting a valid email redirects to `/?signup=ok` and the chip renders at the top of the page (in the hero, as in Task 5).
- Submitting from this form vs the hero form both redirect to the hero-mounted chip (expected — there's one chip position).

Stop the server.

- [ ] **Step 6: Run the full test suite**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/templates/landing.html tests/test_web.py
git commit -m "feat(landing): get-early-access CTA section"
```

---

## Task 9: Update smoke test

**Files:**
- Modify: `scripts/smoke_test.py`

- [ ] **Step 1: Read the current smoke test**

Run: `cat scripts/smoke_test.py`

Review to identify where the existing flow finishes. The goal is to append a waitlist-POST block at the end without touching existing assertions.

- [ ] **Step 2: Append waitlist assertions**

Append the following block to the end of `scripts/smoke_test.py`, preserving any existing `if __name__ == "__main__":` footer logic. If the existing smoke test uses a `requests`-style client or `httpx`, mirror that. The block below uses `httpx` as a reasonable default — swap in the existing pattern if different:

```python
    # --- Waitlist smoke ---
    test_email = f"smoke+{int(time.time())}@example.com"
    resp = client.post(
        f"{BASE_URL}/api/waitlist",
        data={"email": test_email, "source": "hero"},
        follow_redirects=False,
    )
    assert resp.status_code == 303, f"expected 303, got {resp.status_code}"
    assert resp.headers["location"] == "/?signup=ok", resp.headers

    resp = client.get(f"{BASE_URL}/?signup=ok")
    assert resp.status_code == 200
    assert "You're on the list" in resp.text

    print("✓ waitlist POST + signup chip")
```

If the existing file doesn't use `client` / `BASE_URL` variable names, adapt to the existing convention. The essential assertions are: POST returns 303 to `/?signup=ok`, and GET `/?signup=ok` renders `You're on the list`.

- [ ] **Step 3: Run the smoke test**

In one terminal:

```bash
uv run python src/markland/run_web.py
```

In another:

```bash
uv run python scripts/smoke_test.py
```

Expected: all existing checks pass, plus `✓ waitlist POST + signup chip`.

Stop the web server.

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke_test.py
git commit -m "test(smoke): add waitlist post + chip assertion"
```

---

## Final verification

- [ ] **Run the full test suite one more time**

Run: `uv run pytest tests/ -q`
Expected: all green.

- [ ] **Manual end-to-end walkthrough**

Run: `uv run python src/markland/run_web.py`

Open http://127.0.0.1:8950 and verify the full page top-to-bottom:

1. Hero: new tagline, email form, `Get started` button, `See a sample doc →` link, muted hint.
2. Submit a valid email from the hero form — lands on `/?signup=ok` with the green chip at the top of the hero.
3. Back to `/` — no chip visible (no query param).
4. Submit `garbage` — lands on `/?signup=invalid` with the red chip.
5. Scroll through: Why Markland pillars (unchanged) → Before/After (new) → How it works (new, with colored code) → Get early access (new, second email form) → Get started nav cards (unchanged) → Published from agents (existing, max 4 cards) → footer.
6. Click `See the MCP call →` in the After tile; the page jumps to the How-it-works section.
7. Submit an email from the second (CTA-section) form; returns to `/?signup=ok` just like the hero form.

Stop the server.

---

## Spec coverage audit

This plan's tasks cover every spec section in `docs/specs/2026-04-18-landing-waitlist-design.md`:

| Spec section | Covered by task(s) |
|---|---|
| 2. Hero (MODIFIED) | Task 5 |
| Signup-state chips | Task 4 (param) + Task 5 (template + tests) |
| 3. Why Markland (UNCHANGED) | n/a — no change required |
| 4. Before / After (NEW) | Task 6 |
| 5. How it works (NEW) | Task 7 |
| 6. Get early access (NEW) | Task 8 |
| 7. Gallery cap 8→4 (MODIFIED) | Task 4 |
| 8. Footer (UNCHANGED) | n/a |
| Waitlist schema | Task 1 |
| `add_waitlist_email` | Task 2 |
| `POST /api/waitlist` + `_valid_email` | Task 3 |
| `GET /` signup param | Task 4 |
| Unit tests: db | Tasks 1, 2 |
| Integration tests: web | Tasks 3, 4, 5, 6, 7, 8 |
| Smoke test | Task 9 |

No spec section is left unimplemented. No task references a symbol that isn't defined in this plan.
