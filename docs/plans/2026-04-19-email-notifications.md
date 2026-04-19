# Email Notifications — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

> **Note:** No git commits during execution — this project is not a git repo at time of writing; the user manages version control manually. Where commit steps would normally appear, a "verification" step is substituted.

**Goal:** Consolidate and professionalize every outbound transactional email in Markland. All triggers from spec §7 are wired through a single Jinja-rendered template module and dispatched through an in-process `EmailDispatcher` with jittered exponential-backoff retries. Grants, magic links, and invite acceptances keep succeeding even when Resend is flaky — email failures never surface to the caller. The email matrix for launch is closed: user grant created, user grant level changed, agent grant (user-owned) created, invite accepted, magic-link login. Every template ships with an HTML body **and** a plaintext fallback (sent as Resend `text`) to reduce spam classification. A stub `/settings/notifications` page is added so the "manage notifications" link in every footer resolves to something explicit ("coming soon") rather than a 404.

**Architecture:** A new `src/markland/email_templates/` directory holds Jinja files per trigger (one `.html` + one `.txt` per template) plus a shared `_layout.html` include that wraps each HTML email in a Markland-branded header and a footer with a settings link and a one-line "why am I getting this?" explanation. `service/email_templates.py` is the pure-Python façade: one function per template (`magic_link`, `user_grant`, `user_grant_level_changed`, `agent_grant`, `invite_accepted`) returning a dict `{subject, html, text}` with the spec §7 subject line verbatim. `service/email.py`'s `EmailClient.send(...)` is extended to accept `text=` and `metadata=` and always pass `text` alongside `html`. A new `EmailDispatcher` class (same module) owns an `asyncio.Queue` and a worker task; `enqueue(to, rendered, metadata=None)` is fire-and-forget. The worker pulls items off the queue, calls `EmailClient.send`, and on failure re-enqueues with jittered backoff (1s, 3s, 10s, then drop with a warning log). Grant/invite/magic-link code switches from direct `EmailClient.send` calls to `dispatcher.enqueue(...)`. The dispatcher is owned by the FastAPI app via a lifespan context inside `create_app` (not `run_app.py`) so that `TestClient(create_app(...))` used inside `with TestClient(app) as c:` triggers startup/shutdown and tests see a running dispatcher. The dispatcher instance is stored on `app.state.email_dispatcher` for route handlers and service functions to reach via `request.app.state`. `EmailDispatcher.enqueue(to, subject, html, text=None, metadata=None)` is a plain **synchronous, non-blocking** method that calls `put_nowait` on an internal `asyncio.Queue` and returns immediately — callers never `await enqueue`. Only the background worker is async. Because `enqueue` is sync, `service.magic_link.send_magic_link(...)` also stays **synchronous**, so Plan 2's sync magic-link route handler keeps working unmodified. **Design choice (documented once, applied consistently below):** `EmailClient` remains a thin wrapper used only by the dispatcher worker to make the outbound Resend call. Service-level triggers (magic-link, grants, invites) call `dispatcher.enqueue(...)` directly — they do not go through `EmailClient`. This keeps a single flow: service → dispatcher.enqueue → worker → EmailClient.send.

**Tech Stack:** Python 3.12, FastAPI lifespan events, Jinja2 (already a dep), `asyncio.Queue`, `resend` SDK, pytest-asyncio for worker tests.

**Scope excluded (this plan):**
- User-configurable notification preferences (no per-user opt-outs; no per-category toggles).
- Digest / batched emails (every trigger sends immediately).
- Real unsubscribe link wiring (the footer link points to a stub page).
- Persistent retry queue backed by Redis or a DB table (in-process only — survives crashes is a post-launch problem; the spec mandates "lightweight in-process").
- Delivery analytics / click tracking (Resend captures opens by default; we do not act on them).
- Localization (all templates English at launch).

---

## File Structure

**New files:**
- `src/markland/email_templates/__init__.py` — empty marker
- `src/markland/email_templates/_layout.html` — shared HTML header + footer wrapper
- `src/markland/email_templates/magic_link.html`
- `src/markland/email_templates/magic_link.txt`
- `src/markland/email_templates/user_grant.html`
- `src/markland/email_templates/user_grant.txt`
- `src/markland/email_templates/user_grant_level_changed.html`
- `src/markland/email_templates/user_grant_level_changed.txt`
- `src/markland/email_templates/agent_grant.html`
- `src/markland/email_templates/agent_grant.txt`
- `src/markland/email_templates/invite_accepted.html`
- `src/markland/email_templates/invite_accepted.txt`
- `src/markland/service/email_templates.py` — renderer functions
- `src/markland/service/email_dispatcher.py` — `EmailDispatcher` class (queue + worker)
- `src/markland/web/settings.py` — `GET /settings/notifications` stub router
- `tests/test_email_templates.py` — unit tests for the renderer
- `tests/test_email_dispatcher.py` — unit tests for the dispatcher + retry
- `tests/test_email_integration.py` — integration test: grant a doc → dispatched → client called
- `tests/test_settings_notifications.py` — smoke test for the stub page

**Modified files:**
- `src/markland/service/email.py` — extend `EmailClient.send` signature with `text` and `metadata`
- `src/markland/service/magic_link.py` — swap inline HTML for `email_templates.magic_link(...)` + dispatcher
- `src/markland/service/grants.py` — swap inline stubs; add `user_grant_level_changed` trigger
- `src/markland/service/invites.py` — swap inline stub for `email_templates.invite_accepted(...)` + dispatcher
- `src/markland/run_app.py` — construct `EmailDispatcher`, pass it into `create_app(...)` (lifecycle owned by `create_app`)
- `src/markland/web/app.py` — accept `email_dispatcher`, define FastAPI `lifespan` that starts/stops it, include `web/settings.py` router, expose dispatcher via `app.state.email_dispatcher`
- `tests/test_magic_link.py`, `tests/test_grants.py`, `tests/test_invites.py` — update existing assertions to cope with dispatcher indirection (still assert the underlying `EmailClient.send` call)

**Unchanged:** all document/tool/DB code, auth middleware, Litestream/Fly infra.

---

## Task 1: Template directory with shared layout + all HTML/text files

**Files:**
- Create: `src/markland/email_templates/__init__.py`
- Create: `src/markland/email_templates/_layout.html`
- Create: `src/markland/email_templates/magic_link.html`
- Create: `src/markland/email_templates/magic_link.txt`
- Create: `src/markland/email_templates/user_grant.html`
- Create: `src/markland/email_templates/user_grant.txt`
- Create: `src/markland/email_templates/user_grant_level_changed.html`
- Create: `src/markland/email_templates/user_grant_level_changed.txt`
- Create: `src/markland/email_templates/agent_grant.html`
- Create: `src/markland/email_templates/agent_grant.txt`
- Create: `src/markland/email_templates/invite_accepted.html`
- Create: `src/markland/email_templates/invite_accepted.txt`

- [x] **Step 1: Create the package marker**

Create `src/markland/email_templates/__init__.py`:

```python
"""Jinja templates for transactional email — HTML + plaintext per trigger."""
```

- [x] **Step 2: Write the shared HTML layout**

Create `src/markland/email_templates/_layout.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ subject }}</title>
</head>
<body style="margin:0;padding:0;background:#f6f6f4;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1a1a1a;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f6f6f4;">
    <tr>
      <td align="center" style="padding:32px 16px;">
        <table role="presentation" width="560" cellpadding="0" cellspacing="0" style="background:#ffffff;border:1px solid #e5e5e2;border-radius:8px;max-width:560px;">
          <tr>
            <td style="padding:24px 32px;border-bottom:1px solid #e5e5e2;">
              <a href="{{ base_url }}" style="text-decoration:none;color:#1a1a1a;font-weight:600;font-size:18px;letter-spacing:-0.01em;">Markland</a>
            </td>
          </tr>
          <tr>
            <td style="padding:32px;line-height:1.55;font-size:15px;">
              {% block content %}{% endblock %}
            </td>
          </tr>
          <tr>
            <td style="padding:20px 32px;border-top:1px solid #e5e5e2;background:#fafaf8;font-size:12px;color:#6b6b68;line-height:1.5;border-radius:0 0 8px 8px;">
              <p style="margin:0 0 6px 0;">You're getting this because {{ footer_reason }}</p>
              <p style="margin:0;">
                <a href="{{ base_url }}/settings/notifications" style="color:#6b6b68;">Manage notifications</a>
                &nbsp;·&nbsp;
                <a href="{{ base_url }}" style="color:#6b6b68;">Markland</a>
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
```

- [x] **Step 3: Write `magic_link.html`**

Create `src/markland/email_templates/magic_link.html`:

```html
{% extends "_layout.html" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-size:22px;font-weight:600;">Your Markland login link</h1>
<p style="margin:0 0 20px 0;">Click the button below to sign in. This link expires in {{ expires_in_minutes }} minutes and can be used once.</p>
<p style="margin:0 0 24px 0;">
  <a href="{{ verify_url }}" style="display:inline-block;background:#1a1a1a;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:500;">Sign in to Markland</a>
</p>
<p style="margin:0 0 8px 0;color:#6b6b68;font-size:13px;">Or paste this URL into your browser:</p>
<p style="margin:0;word-break:break-all;color:#6b6b68;font-size:13px;"><a href="{{ verify_url }}" style="color:#6b6b68;">{{ verify_url }}</a></p>
{% endblock %}
```

- [x] **Step 4: Write `magic_link.txt`**

Create `src/markland/email_templates/magic_link.txt`:

```
Your Markland login link

Click the link below to sign in. It expires in {{ expires_in_minutes }} minutes and can be used once.

{{ verify_url }}

If you didn't request this, you can safely ignore this email.

--
Markland · {{ base_url }}
Manage notifications: {{ base_url }}/settings/notifications
```

- [x] **Step 5: Write `user_grant.html`**

Create `src/markland/email_templates/user_grant.html`:

```html
{% extends "_layout.html" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-size:22px;font-weight:600;">{{ granter_display }} shared a document with you</h1>
<p style="margin:0 0 8px 0;"><strong>{{ doc_title }}</strong></p>
<p style="margin:0 0 20px 0;color:#6b6b68;">{{ level_phrase }}</p>
<p style="margin:0 0 24px 0;">
  <a href="{{ doc_url }}" style="display:inline-block;background:#1a1a1a;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:500;">Open document</a>
</p>
<p style="margin:0;color:#6b6b68;font-size:13px;">Or paste: <a href="{{ doc_url }}" style="color:#6b6b68;">{{ doc_url }}</a></p>
{% endblock %}
```

- [x] **Step 6: Write `user_grant.txt`**

Create `src/markland/email_templates/user_grant.txt`:

```
{{ granter_display }} shared "{{ doc_title }}" with you — {{ level }} access.

Open: {{ doc_url }}

--
Markland · {{ base_url }}
Manage notifications: {{ base_url }}/settings/notifications
```

- [x] **Step 7: Write `user_grant_level_changed.html`**

Create `src/markland/email_templates/user_grant_level_changed.html`:

```html
{% extends "_layout.html" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-size:22px;font-weight:600;">Your access changed</h1>
<p style="margin:0 0 8px 0;">{{ granter_display }} changed your access to <strong>{{ doc_title }}</strong>.</p>
<p style="margin:0 0 20px 0;color:#6b6b68;">New level: <strong>{{ new_level }}</strong> (was {{ old_level }}).</p>
<p style="margin:0 0 24px 0;">
  <a href="{{ doc_url }}" style="display:inline-block;background:#1a1a1a;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:500;">Open document</a>
</p>
{% endblock %}
```

- [x] **Step 8: Write `user_grant_level_changed.txt`**

Create `src/markland/email_templates/user_grant_level_changed.txt`:

```
{{ granter_display }} changed your access to "{{ doc_title }}" to {{ new_level }} (was {{ old_level }}).

Open: {{ doc_url }}

--
Markland · {{ base_url }}
Manage notifications: {{ base_url }}/settings/notifications
```

- [x] **Step 9: Write `agent_grant.html`**

Create `src/markland/email_templates/agent_grant.html`:

```html
{% extends "_layout.html" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-size:22px;font-weight:600;">An agent you own was granted access</h1>
<p style="margin:0 0 8px 0;">{{ granter_display }} granted your agent <strong>{{ agent_name }}</strong> ({{ agent_id }}) <strong>{{ level }}</strong> access to <strong>{{ doc_title }}</strong>.</p>
<p style="margin:0 0 24px 0;">
  <a href="{{ doc_url }}" style="display:inline-block;background:#1a1a1a;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:500;">Open document</a>
</p>
<p style="margin:0;color:#6b6b68;font-size:13px;">If this wasn't expected, you can revoke this grant from the document's sharing panel.</p>
{% endblock %}
```

- [x] **Step 10: Write `agent_grant.txt`**

Create `src/markland/email_templates/agent_grant.txt`:

```
{{ granter_display }} granted your agent {{ agent_name }} ({{ agent_id }}) {{ level }} access to "{{ doc_title }}".

Open: {{ doc_url }}

If this wasn't expected, revoke it from the document's sharing panel.

--
Markland · {{ base_url }}
Manage notifications: {{ base_url }}/settings/notifications
```

- [x] **Step 11: Write `invite_accepted.html`**

Create `src/markland/email_templates/invite_accepted.html`:

```html
{% extends "_layout.html" %}
{% block content %}
<h1 style="margin:0 0 16px 0;font-size:22px;font-weight:600;">Your invite was accepted</h1>
<p style="margin:0 0 20px 0;"><strong>{{ accepter_display }}</strong> accepted your invite to <strong>{{ doc_title }}</strong>.</p>
<p style="margin:0 0 24px 0;">
  <a href="{{ doc_url }}" style="display:inline-block;background:#1a1a1a;color:#ffffff;text-decoration:none;padding:12px 20px;border-radius:6px;font-weight:500;">Open document</a>
</p>
{% endblock %}
```

- [x] **Step 12: Write `invite_accepted.txt`**

Create `src/markland/email_templates/invite_accepted.txt`:

```
{{ accepter_display }} accepted your invite to "{{ doc_title }}".

Open: {{ doc_url }}

--
Markland · {{ base_url }}
Manage notifications: {{ base_url }}/settings/notifications
```

- [x] **Step 13: Verification — files exist**

Run: `ls -1 src/markland/email_templates/`
Expected: 13 files (`__init__.py`, `_layout.html`, five `.html`, five `.txt`).

---

## Task 2: `service/email_templates.py` renderer

**Files:**
- Create: `src/markland/service/email_templates.py`
- Create: `tests/test_email_templates.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_email_templates.py`:

```python
"""Renderer tests: correct subject, html + text populated, key fields present."""

import pytest

from markland.config import reset_config
from markland.service import email_templates as tpl


@pytest.fixture(autouse=True)
def _config(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://markland.dev")
    reset_config()
    yield
    reset_config()


def test_magic_link_renders():
    rendered = tpl.magic_link(
        email="alice@example.com",
        verify_url="https://markland.dev/auth/verify?t=abc",
        expires_in_minutes=15,
    )
    assert rendered["subject"] == "Your Markland login link (expires in 15 minutes)."
    assert "https://markland.dev/auth/verify?t=abc" in rendered["html"]
    assert "https://markland.dev/auth/verify?t=abc" in rendered["text"]
    assert "15 minutes" in rendered["text"]
    assert "Manage notifications" in rendered["html"]
    assert "/settings/notifications" in rendered["text"]


def test_user_grant_renders():
    rendered = tpl.user_grant(
        granter_display="Bob",
        doc_title="Quarterly plan",
        doc_url="https://markland.dev/d/tok",
        level="view",
    )
    assert rendered["subject"] == 'Bob shared "Quarterly plan" with you — view access.'
    assert "Bob" in rendered["html"]
    assert "Quarterly plan" in rendered["html"]
    assert "https://markland.dev/d/tok" in rendered["html"]
    assert "view" in rendered["text"]
    assert "<" not in rendered["text"] or "</" not in rendered["text"]  # no HTML tags


def test_user_grant_level_changed_renders():
    rendered = tpl.user_grant_level_changed(
        granter_display="Bob",
        doc_title="Q plan",
        doc_url="https://markland.dev/d/tok",
        old_level="view",
        new_level="edit",
    )
    assert rendered["subject"] == 'Bob changed your access to "Q plan" to edit.'
    assert "edit" in rendered["html"]
    assert "view" in rendered["html"]
    assert "Q plan" in rendered["text"]


def test_agent_grant_renders():
    rendered = tpl.agent_grant(
        granter_display="Bob",
        agent_name="coder-01",
        agent_id="agt_abc",
        doc_title="Q plan",
        doc_url="https://markland.dev/d/tok",
        level="edit",
    )
    assert rendered["subject"] == 'Bob granted your agent coder-01 edit access to "Q plan".'
    assert "coder-01" in rendered["html"]
    assert "agt_abc" in rendered["html"]
    assert "agt_abc" in rendered["text"]


def test_invite_accepted_renders():
    rendered = tpl.invite_accepted(
        accepter_display="Alice",
        doc_title="Q plan",
        doc_url="https://markland.dev/d/tok",
    )
    assert rendered["subject"] == 'Alice accepted your invite to "Q plan".'
    assert "Alice" in rendered["html"]
    assert "Q plan" in rendered["text"]


def test_all_templates_include_footer_settings_link():
    rendered = tpl.magic_link(
        email="a@b", verify_url="https://x/y", expires_in_minutes=15
    )
    assert "/settings/notifications" in rendered["html"]
    assert "/settings/notifications" in rendered["text"]


def test_html_and_text_are_both_nonempty_for_every_template():
    samples = [
        tpl.magic_link(email="a@b", verify_url="https://x", expires_in_minutes=15),
        tpl.user_grant(granter_display="G", doc_title="T", doc_url="https://x", level="view"),
        tpl.user_grant_level_changed(
            granter_display="G", doc_title="T", doc_url="https://x",
            old_level="view", new_level="edit",
        ),
        tpl.agent_grant(
            granter_display="G", agent_name="n", agent_id="agt_x",
            doc_title="T", doc_url="https://x", level="edit",
        ),
        tpl.invite_accepted(accepter_display="A", doc_title="T", doc_url="https://x"),
    ]
    for r in samples:
        assert r["subject"]
        assert r["html"].strip().startswith("<!DOCTYPE")
        assert r["text"].strip()
        assert "Markland" in r["html"]
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_templates.py -v`
Expected: FAIL — `markland.service.email_templates` does not exist.

- [x] **Step 3: Implement the renderer**

Create `src/markland/service/email_templates.py`:

```python
"""Render transactional email bodies. Each function returns {subject, html, text}.

Subject lines match spec §17 / §7 verbatim. HTML templates extend _layout.html;
text templates stand alone. Every email includes the footer "manage notifications"
link and a one-line "why am I getting this?" explanation.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.config import get_config

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "email_templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)


def _render(name: str, **ctx) -> str:
    return _env.get_template(name).render(**ctx)


def _base_ctx(footer_reason: str) -> dict:
    return {
        "base_url": get_config().base_url,
        "footer_reason": footer_reason,
    }


def magic_link(*, email: str, verify_url: str, expires_in_minutes: int = 15) -> dict:
    subject = f"Your Markland login link (expires in {expires_in_minutes} minutes)."
    ctx = {
        **_base_ctx("you requested a sign-in link for this email address."),
        "subject": subject,
        "email": email,
        "verify_url": verify_url,
        "expires_in_minutes": expires_in_minutes,
    }
    return {
        "subject": subject,
        "html": _render("magic_link.html", **ctx),
        "text": _render("magic_link.txt", **ctx),
    }


def user_grant(
    *,
    granter_display: str,
    doc_title: str,
    doc_url: str,
    level: str,
) -> dict:
    subject = f'{granter_display} shared "{doc_title}" with you — {level} access.'
    level_phrase = f"You have {level} access." if level == "edit" else "You have view access (read-only)."
    ctx = {
        **_base_ctx("someone shared a Markland document with you."),
        "subject": subject,
        "granter_display": granter_display,
        "doc_title": doc_title,
        "doc_url": doc_url,
        "level": level,
        "level_phrase": level_phrase,
    }
    return {
        "subject": subject,
        "html": _render("user_grant.html", **ctx),
        "text": _render("user_grant.txt", **ctx),
    }


def user_grant_level_changed(
    *,
    granter_display: str,
    doc_title: str,
    doc_url: str,
    old_level: str,
    new_level: str,
) -> dict:
    subject = f'{granter_display} changed your access to "{doc_title}" to {new_level}.'
    ctx = {
        **_base_ctx("your access to a shared Markland document changed."),
        "subject": subject,
        "granter_display": granter_display,
        "doc_title": doc_title,
        "doc_url": doc_url,
        "old_level": old_level,
        "new_level": new_level,
    }
    return {
        "subject": subject,
        "html": _render("user_grant_level_changed.html", **ctx),
        "text": _render("user_grant_level_changed.txt", **ctx),
    }


def agent_grant(
    *,
    granter_display: str,
    agent_name: str,
    agent_id: str,
    doc_title: str,
    doc_url: str,
    level: str,
) -> dict:
    subject = f'{granter_display} granted your agent {agent_name} {level} access to "{doc_title}".'
    ctx = {
        **_base_ctx("an agent you own was granted access to a Markland document."),
        "subject": subject,
        "granter_display": granter_display,
        "agent_name": agent_name,
        "agent_id": agent_id,
        "doc_title": doc_title,
        "doc_url": doc_url,
        "level": level,
    }
    return {
        "subject": subject,
        "html": _render("agent_grant.html", **ctx),
        "text": _render("agent_grant.txt", **ctx),
    }


def invite_accepted(
    *,
    accepter_display: str,
    doc_title: str,
    doc_url: str,
) -> dict:
    subject = f'{accepter_display} accepted your invite to "{doc_title}".'
    ctx = {
        **_base_ctx("someone accepted an invite link you created."),
        "subject": subject,
        "accepter_display": accepter_display,
        "doc_title": doc_title,
        "doc_url": doc_url,
    }
    return {
        "subject": subject,
        "html": _render("invite_accepted.html", **ctx),
        "text": _render("invite_accepted.txt", **ctx),
    }
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_email_templates.py -v`
Expected: PASS (7 tests).

---

## Task 3: Extend `EmailClient.send` with `text` + `metadata`

**Files:**
- Modify: `src/markland/service/email.py`
- Modify: `tests/test_email_service.py`

- [x] **Step 1: Update the existing tests + add new coverage**

Open `tests/test_email_service.py` and replace its contents with:

```python
"""Tests for the Resend email wrapper."""

from unittest.mock import patch

import pytest

from markland.service.email import EmailClient, EmailSendError


def test_sends_via_resend_with_html_and_text():
    client = EmailClient(api_key="re_test", from_email="notifications@markland.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "email_abc"}
        msg_id = client.send(
            to="alice@example.com",
            subject="Hi",
            html="<p>hi</p>",
            text="hi",
        )
    assert msg_id == "email_abc"
    sent = send_mock.call_args.args[0] if send_mock.call_args.args else send_mock.call_args.kwargs
    assert sent["to"] == "alice@example.com"
    assert sent["from"] == "notifications@markland.dev"
    assert sent["subject"] == "Hi"
    assert sent["html"] == "<p>hi</p>"
    assert sent["text"] == "hi"


def test_send_forwards_metadata_as_tags_when_provided():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "x"}
        client.send(
            to="a@b",
            subject="s",
            html="<p>x</p>",
            text="x",
            metadata={"template": "user_grant", "doc_id": "d_1"},
        )
    sent = send_mock.call_args.args[0] if send_mock.call_args.args else send_mock.call_args.kwargs
    tags = sent.get("tags") or []
    names = {t["name"] for t in tags}
    assert "template" in names
    assert "doc_id" in names


def test_send_without_text_still_works_backward_compat():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "x"}
        client.send(to="a@b", subject="s", html="<p>x</p>")
    sent = send_mock.call_args.args[0] if send_mock.call_args.args else send_mock.call_args.kwargs
    assert sent["html"] == "<p>x</p>"
    assert "text" not in sent or sent["text"] in (None, "")


def test_noop_when_api_key_empty():
    client = EmailClient(api_key="", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        msg_id = client.send(to="a@b", subject="x", html="<p>x</p>", text="x")
    send_mock.assert_not_called()
    assert msg_id is None


def test_raises_on_resend_failure():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send", side_effect=RuntimeError("resend down")):
        with pytest.raises(EmailSendError):
            client.send(to="a@b", subject="x", html="<p>x</p>", text="x")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_service.py -v`
Expected: FAIL — `send` does not accept `text=` / `metadata=`.

- [x] **Step 3: Update `EmailClient.send`**

Replace `src/markland/service/email.py` with:

```python
"""Thin wrapper around Resend. No-ops safely when no API key is configured."""

from __future__ import annotations

import logging
from typing import Any

import resend

logger = logging.getLogger("markland.email")


class EmailSendError(RuntimeError):
    """Raised when Resend returns an error."""


class EmailClient:
    """Stateless-ish wrapper — holds api_key and from_email, calls resend.Emails.send."""

    def __init__(self, *, api_key: str, from_email: str) -> None:
        self._api_key = api_key
        self._from = from_email
        if api_key:
            resend.api_key = api_key

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        """Send an email with HTML + optional plaintext.

        `metadata` is forwarded to Resend as `tags` — useful for filtering the
        Resend dashboard by template name or document id. No PII should go here.
        Returns Resend's message id, or None if disabled (no API key).
        """
        if not self._api_key:
            logger.info(
                "Email disabled (no RESEND_API_KEY); would have sent to %s: %s",
                to, subject,
            )
            return None

        payload: dict[str, Any] = {
            "from": self._from,
            "to": to,
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if metadata:
            payload["tags"] = [{"name": k, "value": str(v)} for k, v in metadata.items()]

        try:
            resp = resend.Emails.send(payload)
            return resp.get("id") if isinstance(resp, dict) else None
        except Exception as exc:
            raise EmailSendError(str(exc)) from exc
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_email_service.py -v`
Expected: PASS (5 tests).

---

## Task 4: `EmailDispatcher` with in-process retry queue

**Files:**
- Create: `src/markland/service/email_dispatcher.py`
- Create: `tests/test_email_dispatcher.py`

- [x] **Step 1: Write the failing tests**

Create `tests/test_email_dispatcher.py`:

```python
"""EmailDispatcher unit tests — enqueue, worker, jittered exponential retry, drop."""

import asyncio
from unittest.mock import MagicMock

import pytest

from markland.service.email import EmailSendError
from markland.service.email_dispatcher import EmailDispatcher


class _FakeClient:
    def __init__(self, *, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.fail_times:
            raise EmailSendError("boom")
        return "email_ok"


@pytest.mark.asyncio
async def test_enqueue_and_send_once_on_success():
    client = _FakeClient(fail_times=0)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(
            to="a@b",
            subject="s",
            html="<p>h</p>",
            text="h",
            metadata={"template": "user_grant"},
        )
        await disp.drain()
    finally:
        await disp.stop()

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["to"] == "a@b"
    assert call["subject"] == "s"
    assert call["html"] == "<p>h</p>"
    assert call["text"] == "h"
    assert call["metadata"] == {"template": "user_grant"}


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    client = _FakeClient(fail_times=2)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
        await disp.drain()
    finally:
        await disp.stop()

    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_drops_after_three_retries(caplog):
    client = _FakeClient(fail_times=99)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
        await disp.drain()
    finally:
        await disp.stop()

    # Four total attempts: initial + 3 retries = 4 tries, then dropped.
    assert len(client.calls) == 4
    assert any("dropping email" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_drains_in_flight():
    client = _FakeClient(fail_times=0)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
    await disp.stop()
    await disp.stop()  # second stop is a no-op
    # Enqueue after stop is allowed but not worked on — we just verify no crash.
    disp.enqueue(to="c@d", subject="s", html="<p>h</p>", text="h")
    assert len(client.calls) == 1  # only the first one was processed


@pytest.mark.asyncio
async def test_client_that_returns_none_noop_is_treated_as_success():
    client = MagicMock()
    client.send = MagicMock(return_value=None)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
        await disp.drain()
    finally:
        await disp.stop()
    assert client.send.call_count == 1
```

- [x] **Step 2: Ensure pytest-asyncio is available**

Check `pyproject.toml` dev/test deps. If `pytest-asyncio` is missing, add it:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

And in `[project.optional-dependencies]` dev table (or wherever test deps live), add:

```toml
    "pytest-asyncio>=0.23",
```

Run: `uv sync --all-extras`
Expected: resolves successfully.

- [x] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_email_dispatcher.py -v`
Expected: FAIL — `markland.service.email_dispatcher` does not exist.

- [x] **Step 4: Implement the dispatcher**

Create `src/markland/service/email_dispatcher.py`:

```python
"""In-process email dispatch queue with jittered exponential-backoff retry.

Design notes:
- Fire-and-forget: callers call the synchronous `enqueue(...)` which puts an item
  on the queue via `put_nowait` and returns immediately. Callers never `await enqueue`.
- A single background worker task pulls items and calls EmailClient.send.
- On EmailSendError, the item is re-enqueued with an incrementing attempt counter.
  After `len(retry_delays)` failures, the item is dropped with a WARNING log.
- Retry delays are jittered by ±25% to avoid thundering herds against Resend.
- No persistence: process restart drops any in-flight items. Documented as OK for
  v1 per spec §7 ("lightweight in-process"). Persistent queue lands post-launch
  when Redis/DB-backed retry is justified.
- Grants and writes never fail because of email problems — callers always enqueue
  inside a try/except-and-log-only path.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Protocol

from markland.service.email import EmailSendError

logger = logging.getLogger("markland.email_dispatcher")

# Attempts after initial: 1s, 3s, 10s, then drop. Total 4 attempts including initial.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 10.0)


class _ClientProto(Protocol):
    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str | None: ...


@dataclass
class _Item:
    to: str
    subject: str
    html: str
    text: str | None
    metadata: dict[str, str] | None
    attempt: int = 0


class EmailDispatcher:
    def __init__(
        self,
        client: _ClientProto,
        *,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        jitter_frac: float = 0.25,
    ) -> None:
        self._client = client
        self._retry_delays = retry_delays
        self._jitter_frac = jitter_frac
        self._queue: asyncio.Queue[_Item] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stopped.clear()
        self._worker = asyncio.create_task(self._run(), name="email-dispatcher")
        logger.info("EmailDispatcher started")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._stopped.set()
        # Cancel waiting worker if queue is empty
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None
        logger.info("EmailDispatcher stopped")

    def enqueue(
        self,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Synchronous, non-blocking. Puts the item on the queue and returns.

        Callers must NOT await this method. It is safe to call from sync or async
        contexts. The background worker (async) picks items off the queue and
        calls EmailClient.send.
        """
        item = _Item(
            to=to, subject=subject, html=html, text=text, metadata=metadata,
        )
        # asyncio.Queue.put_nowait is safe to call from a sync context; the
        # queue is unbounded so QueueFull will not be raised in practice.
        self._queue.put_nowait(item)

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait until the queue is empty and the worker is idle. Test helper."""
        async def _wait() -> None:
            await self._queue.join()
        await asyncio.wait_for(_wait(), timeout=timeout)

    async def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    item = await self._queue.get()
                except asyncio.CancelledError:
                    raise
                try:
                    await self._process(item)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            return

    async def _process(self, item: _Item) -> None:
        try:
            # Run blocking resend SDK in a thread so the worker stays responsive.
            await asyncio.to_thread(
                self._client.send,
                to=item.to,
                subject=item.subject,
                html=item.html,
                text=item.text,
                metadata=item.metadata,
            )
        except EmailSendError as exc:
            if item.attempt >= len(self._retry_delays):
                logger.warning(
                    "dropping email to %s after %d attempts: %s",
                    item.to, item.attempt + 1, exc,
                )
                return
            delay = self._retry_delays[item.attempt]
            jitter = delay * self._jitter_frac
            delay = delay + random.uniform(-jitter, jitter)
            delay = max(0.0, delay)
            logger.info(
                "email to %s failed (attempt %d); retrying in %.2fs: %s",
                item.to, item.attempt + 1, delay, exc,
            )
            item.attempt += 1
            # Schedule a delayed re-enqueue without blocking the worker.
            asyncio.create_task(self._requeue_after(item, delay))
        except Exception as exc:
            # Unexpected error — drop, don't poison the queue.
            logger.exception("unexpected error sending email to %s: %s", item.to, exc)

    async def _requeue_after(self, item: _Item, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if self._stopped.is_set():
                return
            self._queue.put_nowait(item)
        except asyncio.CancelledError:
            return
```

- [x] **Step 5: Run tests**

Run: `uv run pytest tests/test_email_dispatcher.py -v`
Expected: PASS (5 tests).

---

## Task 5: Wire `EmailDispatcher` into `create_app` via FastAPI lifespan

**Files:**
- Modify: `src/markland/web/app.py` (accept dispatcher, define `lifespan`, store on `app.state`)
- Modify: `src/markland/run_app.py` (construct dispatcher, pass it into `create_app`)

> **Why the lifespan lives in `create_app`, not `run_app.py`:** tests construct the app via `TestClient(create_app(...))` and enter it with `with TestClient(app) as c:` — `TestClient` only triggers lifespan when entered as a context manager. If the dispatcher start/stop is bolted onto `run_app.py`, tests never get a running dispatcher. Putting the lifespan on the `FastAPI` instance returned by `create_app` means **every** caller (prod entrypoint, TestClient, future ASGI embeds) gets the same start/stop semantics.

- [x] **Step 1: Update `web/app.py` to accept a dispatcher and own its lifecycle**

In `src/markland/web/app.py`, extend `create_app`:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI


def create_app(
    db_conn,
    *,
    mount_mcp: bool = False,
    admin_token: str = "",
    base_url: str = "",
    email_dispatcher=None,
):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if email_dispatcher is not None:
            await email_dispatcher.start()
            app.state.email_dispatcher = email_dispatcher
        try:
            yield
        finally:
            if email_dispatcher is not None:
                await email_dispatcher.stop()

    app = FastAPI(
        title="Markland", docs_url=None, redoc_url=None, lifespan=lifespan,
    )
    app.state.db = db_conn
    # Expose eagerly too — handlers that run before startup (shouldn't happen,
    # but be robust) still see the instance.
    app.state.email_dispatcher = email_dispatcher
    ...
```

(If `web/app.py` already defines a lifespan, merge the dispatcher start/stop into it — do **not** introduce a second lifespan.)

- [x] **Step 2: Update `run_app.py`**

`run_app.py` only constructs the dispatcher and hands it to `create_app`. It does **not** start/stop it — the FastAPI lifespan added in Step 1 handles that when uvicorn (or `TestClient`) enters the app lifecycle.

Replace the body of `src/markland/run_app.py` with:

```python
"""Unified HTTP entrypoint: web viewer + MCP on /mcp, Sentry init, email dispatcher."""

import logging

import uvicorn

from markland.config import get_config
from markland.db import init_db
from markland.service.email import EmailClient
from markland.service.email_dispatcher import EmailDispatcher
from markland.web.app import create_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("markland.app")

config = get_config()

if config.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=config.sentry_dsn,
            traces_sample_rate=0.1,
            send_default_pii=False,
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")

db_conn = init_db(config.db_path)

_email_client = EmailClient(
    api_key=config.resend_api_key,
    from_email=config.resend_from_email,
)
_email_dispatcher = EmailDispatcher(_email_client)

app = create_app(
    db_conn,
    mount_mcp=True,
    admin_token=config.admin_token,
    base_url=config.base_url,
    email_dispatcher=_email_dispatcher,
)


if __name__ == "__main__":
    host = "0.0.0.0" if config.admin_token else "127.0.0.1"
    logger.info(
        "Starting Markland hosted app on %s:%d (db: %s, mcp_enabled=%s, resend=%s)",
        host, config.web_port, config.db_path,
        bool(config.admin_token), bool(config.resend_api_key),
    )
    uvicorn.run(app, host=host, port=config.web_port, log_level="info")
```

- [x] **Step 3: Verification — boot locally**

Run:
```bash
MARKLAND_ADMIN_TOKEN=local_test uv run python src/markland/run_app.py
```
Expected: log line `EmailDispatcher started`. Ctrl-C and expect `EmailDispatcher stopped`.

- [x] **Step 4: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: all existing tests still pass (the dispatcher kwarg is optional).

---

## Task 6: Swap magic-link email path to the new template + dispatcher

**Files:**
- Modify: `src/markland/service/magic_link.py`
- Modify: `tests/test_magic_link.py`

Background: Plan 2 sent magic-link email inline via `EmailClient.send(...)`. We now call `email_templates.magic_link(...)` and route through `EmailDispatcher.enqueue`. The dispatcher comes from the caller (FastAPI route handler reads `request.app.state.email_dispatcher`). `magic_link` service function accepts a dispatcher parameter so tests can inject a fake. **`send_magic_link` stays synchronous** — `dispatcher.enqueue(...)` is sync and non-blocking, so Plan 2's sync magic-link route handler keeps working unchanged.

- [x] **Step 1: Update the existing magic-link test**

Open `tests/test_magic_link.py` and adjust the assertion that the client was called directly — instead, assert the dispatcher received one enqueue. Add/replace the relevant test with:

```python
from markland.service.magic_link import send_magic_link


class _FakeDispatcher:
    def __init__(self):
        self.enqueued: list[dict] = []

    def enqueue(self, to, subject, html, text=None, metadata=None):
        self.enqueued.append({
            "to": to, "subject": subject, "html": html,
            "text": text, "metadata": metadata,
        })


def test_send_magic_link_enqueues_templated_email(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://markland.dev")
    from markland.config import reset_config
    reset_config()

    disp = _FakeDispatcher()
    send_magic_link(
        dispatcher=disp,
        email="alice@example.com",
        verify_url="https://markland.dev/auth/verify?t=abc",
        expires_in_minutes=15,
    )
    assert len(disp.enqueued) == 1
    item = disp.enqueued[0]
    assert item["to"] == "alice@example.com"
    assert item["subject"] == "Your Markland login link (expires in 15 minutes)."
    assert "https://markland.dev/auth/verify?t=abc" in item["html"]
    assert item["metadata"]["template"] == "magic_link"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_magic_link.py -v`
Expected: FAIL — `send_magic_link` does not accept `dispatcher=` or has the old inline-HTML shape.

- [x] **Step 3: Update `service/magic_link.py`**

Locate the existing `service/magic_link.py` magic-link-sending function and replace the email body with a template + dispatcher call. **The function stays synchronous** — `dispatcher.enqueue(...)` is a sync non-blocking call, so no async/await is needed here and Plan 2's sync route handler is unaffected:

```python
"""Magic-link login — send + verify. Email body now delegated to email_templates."""

from __future__ import annotations

import logging

from markland.service import email_templates

logger = logging.getLogger("markland.magic_link")


def send_magic_link(
    *,
    dispatcher,
    email: str,
    verify_url: str,
    expires_in_minutes: int = 15,
) -> None:
    """Enqueue the magic-link email. Does not wait for delivery.

    Synchronous: dispatcher.enqueue(...) is a sync non-blocking call that pushes
    onto an asyncio.Queue and returns immediately.
    """
    rendered = email_templates.magic_link(
        email=email,
        verify_url=verify_url,
        expires_in_minutes=expires_in_minutes,
    )
    dispatcher.enqueue(
        to=email,
        subject=rendered["subject"],
        html=rendered["html"],
        text=rendered.get("text"),
        metadata={"template": "magic_link"},
    )
    logger.info("Magic-link email enqueued for %s", email)
```

Callers (the `POST /api/auth/magic-link` route from Plan 2) read the dispatcher off `request.app.state.email_dispatcher`. **Plan 2's route handler stays sync** — no signature change is required.

- [x] **Step 4: Confirm the route handler in `web/auth.py`** (or wherever Plan 2 placed it)

The route handler stays synchronous. Only the dispatcher kwarg is new:

```python
@router.post("/api/auth/magic-link")
def request_magic_link(request: Request, body: MagicLinkRequest):
    verify_url = ...  # same as before
    send_magic_link(
        dispatcher=request.app.state.email_dispatcher,
        email=body.email,
        verify_url=verify_url,
        expires_in_minutes=15,
    )
    return {"ok": True}
```

- [x] **Step 5: Run tests**

Run: `uv run pytest tests/test_magic_link.py -v`
Expected: PASS.

Run the full suite: `uv run pytest tests/ -v` — all green.

---

## Task 7: Swap user-grant-created to template + dispatcher

**Files:**
- Modify: `src/markland/service/grants.py`
- Modify: `tests/test_grants.py`

- [x] **Step 1: Update grant tests**

In `tests/test_grants.py`, replace the existing stubbed-inline-HTML assertion with an enqueue assertion. **Plan 3's canonical export is `grant`** (with internal `grant_by_principal_id`) — import `grant`, not `grant_to_user`:

```python
from markland.service.grants import grant


class _FakeDispatcher:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, to, subject, html, text=None, metadata=None):
        self.enqueued.append({
            "to": to, "subject": subject, "html": html,
            "text": text, "metadata": metadata,
        })


def test_grant_enqueues_user_grant_email(db_conn, bob, alice, sample_doc):
    disp = _FakeDispatcher()
    # Plan 3 signature preserved; `email_client` is replaced by `dispatcher`
    # for the refactor — see Task 7 Step 3 for the exact signature.
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "user_email", "email": alice.email},
        level="view",
        dispatcher=disp,
    )
    assert len(disp.enqueued) == 1
    item = disp.enqueued[0]
    assert item["to"] == alice.email
    assert item["subject"].startswith(f'{bob.display_name} shared')
    assert 'view access' in item["subject"]
    assert item["metadata"]["template"] == "user_grant"
    assert item["metadata"]["doc_id"] == sample_doc.id


def test_grant_still_succeeds_when_dispatcher_enqueue_raises(
    db_conn, bob, alice, sample_doc,
):
    class _BadDispatcher:
        def enqueue(self, *a, **kw):
            raise RuntimeError("queue full")

    # Should NOT propagate: grant must succeed even when email fails.
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "user_email", "email": alice.email},
        level="view",
        dispatcher=_BadDispatcher(),
    )
    # Assert the grant row was written
    row = db_conn.execute(
        "SELECT level FROM grants WHERE doc_id=? AND grantee_email=?",
        (sample_doc.id, alice.email),
    ).fetchone()
    assert row is not None and row[0] == "view"
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_grants.py -v`
Expected: FAIL — `grant` doesn't accept `dispatcher=` yet.

- [x] **Step 3: Update `service/grants.py` user-grant path**

Plan 3's canonical signature is preserved; this refactor **only** swaps the `email_client` kwarg for `dispatcher` (we skip the `EmailClient` wrapper for grant-related triggers and go straight to `dispatcher.enqueue`, per the design choice documented at the top of this plan):

```python
from markland.service import email_templates

def grant(
    conn,
    *,
    base_url: str,
    principal,
    doc_id: str,
    target: dict,
    level: str,
    dispatcher,
) -> dict:
    # Grant-related triggers skip EmailClient and enqueue directly.
    # (EmailClient stays the thin Resend wrapper used by the dispatcher worker.)

    # 1) Persist grant (existing logic from Plan 3 — keep intact).
    #    Internally delegates to grant_by_principal_id for user/agent branches.
    result = _apply_grant(
        conn, principal=principal, doc_id=doc_id, target=target, level=level,
    )
    doc = result.doc
    grantee_email = result.grantee_email  # None for service-owned agent targets

    if grantee_email is None:
        return result.as_dict()

    # 2) Enqueue notification (best-effort — never raises).
    try:
        rendered = email_templates.user_grant(
            granter_display=principal.display_name or principal.email,
            doc_title=doc.title,
            doc_url=f"{base_url}/d/{doc.share_token}",
            level=level,
        )
        dispatcher.enqueue(
            to=grantee_email,
            subject=rendered["subject"],
            html=rendered["html"],
            text=rendered.get("text"),
            metadata={"template": "user_grant", "doc_id": doc_id},
        )
    except Exception as exc:
        logger.warning("Failed to enqueue user_grant email to %s: %s", grantee_email, exc)

    return result.as_dict()
```

(`_apply_grant` / `grant_by_principal_id` are Plan 3's helpers — preserve their behavior. Only the email path changed.)

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_grants.py::test_grant_enqueues_user_grant_email tests/test_grants.py::test_grant_still_succeeds_when_dispatcher_enqueue_raises -v`
Expected: PASS.

---

## Task 8: Wire the `user_grant_level_changed` trigger

**Files:**
- Modify: `src/markland/service/grants.py`
- Modify: `tests/test_grants.py`

Plan 3 only handled the *new* grant case. Re-granting the same (doc, grantee) pair with a different level must now emit `user_grant_level_changed`.

- [x] **Step 1: Write the failing test**

Append to `tests/test_grants.py`:

```python
def test_regrant_with_different_level_enqueues_level_changed(
    db_conn, bob, alice, sample_doc,
):
    disp = _FakeDispatcher()
    # First grant — view
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "user_email", "email": alice.email},
        level="view",
        dispatcher=disp,
    )
    # Re-grant same pair with edit
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "user_email", "email": alice.email},
        level="edit",
        dispatcher=disp,
    )
    assert len(disp.enqueued) == 2
    assert disp.enqueued[0]["metadata"]["template"] == "user_grant"
    assert disp.enqueued[1]["metadata"]["template"] == "user_grant_level_changed"
    assert disp.enqueued[1]["subject"].endswith('to edit.')


def test_regrant_with_same_level_does_not_reemit(
    db_conn, bob, alice, sample_doc,
):
    disp = _FakeDispatcher()
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "user_email", "email": alice.email},
        level="view",
        dispatcher=disp,
    )
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "user_email", "email": alice.email},
        level="view",
        dispatcher=disp,
    )
    assert len(disp.enqueued) == 1  # second call is a no-op email-wise
```

- [x] **Step 2: Run tests — fail**

Run: `uv run pytest tests/test_grants.py -v`
Expected: FAIL — level-changed branch doesn't exist yet.

- [x] **Step 3: Branch on prior level**

Modify `grant` in `service/grants.py` to branch on the prior level for user-email targets:

```python
def grant(
    conn,
    *,
    base_url: str,
    principal,
    doc_id: str,
    target: dict,
    level: str,
    dispatcher,
) -> dict:
    prior_level = None
    if target.get("kind") == "user_email":
        prior = conn.execute(
            "SELECT level FROM grants WHERE doc_id=? AND grantee_email=?",
            (doc_id, target["email"]),
        ).fetchone()
        prior_level = prior[0] if prior else None

    result = _apply_grant(
        conn, principal=principal, doc_id=doc_id, target=target, level=level,
    )
    doc = result.doc
    grantee_email = result.grantee_email
    if grantee_email is None:
        return result.as_dict()

    try:
        if prior_level is None:
            rendered = email_templates.user_grant(
                granter_display=principal.display_name or principal.email,
                doc_title=doc.title,
                doc_url=f"{base_url}/d/{doc.share_token}",
                level=level,
            )
            meta = {"template": "user_grant", "doc_id": doc_id}
        elif prior_level != level:
            rendered = email_templates.user_grant_level_changed(
                granter_display=principal.display_name or principal.email,
                doc_title=doc.title,
                doc_url=f"{base_url}/d/{doc.share_token}",
                old_level=prior_level,
                new_level=level,
            )
            meta = {"template": "user_grant_level_changed", "doc_id": doc_id}
        else:
            return result.as_dict()

        dispatcher.enqueue(
            to=grantee_email,
            subject=rendered["subject"],
            html=rendered["html"],
            text=rendered.get("text"),
            metadata=meta,
        )
    except Exception as exc:
        logger.warning("Failed to enqueue grant email to %s: %s", grantee_email, exc)

    return result.as_dict()
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_grants.py -v`
Expected: PASS.

---

## Task 9: Swap agent-grant-created to template + dispatcher

**Files:**
- Modify: `src/markland/service/grants.py`
- Modify: `tests/test_grants.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_grants.py`:

```python
def test_grant_to_user_owned_agent_emails_owning_user(
    db_conn, bob, alice, sample_doc, alice_owned_agent,
):
    disp = _FakeDispatcher()
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "agent", "agent_id": alice_owned_agent.agent_id},
        level="edit",
        dispatcher=disp,
    )
    assert len(disp.enqueued) == 1
    item = disp.enqueued[0]
    assert item["to"] == alice.email  # agent's owning user
    assert item["metadata"]["template"] == "agent_grant"
    assert alice_owned_agent.agent_id in item["html"]


def test_grant_to_service_owned_agent_sends_no_email(
    db_conn, bob, sample_doc, service_owned_agent,
):
    disp = _FakeDispatcher()
    grant(
        db_conn,
        base_url="https://markland.dev",
        principal=bob,
        doc_id=sample_doc.id,
        target={"kind": "agent", "agent_id": service_owned_agent.agent_id},
        level="view",
        dispatcher=disp,
    )
    assert disp.enqueued == []
```

- [x] **Step 2: Run tests — fail**

Run: `uv run pytest tests/test_grants.py -v`
Expected: FAIL — agent branch of `grant` still uses inline stub.

- [x] **Step 3: Add the agent branch to `grant`**

Extend `grant` in `service/grants.py` to handle `target["kind"] == "agent"` in the same function — the canonical `grant(...)` signature covers both user-email and agent targets. The existing user-email branch from Task 7/8 stays; add an agent branch before the user-email branch:

```python
def grant(
    conn,
    *,
    base_url: str,
    principal,
    doc_id: str,
    target: dict,
    level: str,
    dispatcher,
) -> dict:
    # ... prior_level lookup (user_email target only) — unchanged from Task 8 ...

    result = _apply_grant(
        conn, principal=principal, doc_id=doc_id, target=target, level=level,
    )
    doc = result.doc

    if target["kind"] == "agent":
        agent_id = target["agent_id"]
        agent = _get_agent(conn, agent_id)
        # Service-owned agents have owner_user_id IS NULL — no email target.
        if agent.owner_user_id is None:
            return result.as_dict()
        owner = _get_user(conn, agent.owner_user_id)
        try:
            rendered = email_templates.agent_grant(
                granter_display=principal.display_name or principal.email,
                agent_name=agent.name,
                agent_id=agent.agent_id,
                doc_title=doc.title,
                doc_url=f"{base_url}/d/{doc.share_token}",
                level=level,
            )
            dispatcher.enqueue(
                to=owner.email,
                subject=rendered["subject"],
                html=rendered["html"],
                text=rendered.get("text"),
                metadata={"template": "agent_grant", "doc_id": doc_id, "agent_id": agent_id},
            )
        except Exception as exc:
            logger.warning("Failed to enqueue agent_grant email for %s: %s", agent_id, exc)
        return result.as_dict()

    # user_email branch — see Task 8 for prior_level handling.
    # ... existing user_grant / user_grant_level_changed code ...
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_grants.py -v`
Expected: PASS.

---

## Task 10: Swap invite-accepted to template + dispatcher

**Files:**
- Modify: `src/markland/service/invites.py`
- Modify: `tests/test_invites.py`

- [x] **Step 1: Write the failing test**

In `tests/test_invites.py` replace the inline-HTML stub assertion with:

```python
from markland.service.invites import accept_invite


class _FakeDispatcher:
    def __init__(self):
        self.enqueued = []
    def enqueue(self, to, subject, html, text=None, metadata=None):
        self.enqueued.append({
            "to": to, "subject": subject, "html": html,
            "text": text, "metadata": metadata,
        })


def test_accept_invite_enqueues_email_to_creator(
    db_conn, bob, alice, invite_by_bob,
):
    disp = _FakeDispatcher()
    accept_invite(
        db_conn, dispatcher=disp,
        invite_token=invite_by_bob.token, accepter=alice,
    )
    assert len(disp.enqueued) == 1
    item = disp.enqueued[0]
    assert item["to"] == bob.email
    assert item["metadata"]["template"] == "invite_accepted"
    assert alice.display_name in item["html"] or alice.email in item["html"]
```

- [x] **Step 2: Run tests — fail**

Run: `uv run pytest tests/test_invites.py -v`
Expected: FAIL.

- [x] **Step 3: Update `service/invites.py`**

Replace the stubbed email in `accept_invite`:

```python
from markland.service import email_templates

def accept_invite(
    db_conn, *, dispatcher, invite_token: str, accepter, base_url=None,
):
    from markland.config import get_config
    base_url = base_url or get_config().base_url

    invite, doc = _consume_invite(db_conn, invite_token=invite_token, accepter=accepter)
    creator = _get_user(db_conn, invite.creator_user_id)

    try:
        rendered = email_templates.invite_accepted(
            accepter_display=accepter.display_name or accepter.email,
            doc_title=doc.title,
            doc_url=f"{base_url}/d/{doc.share_token}",
        )
        dispatcher.enqueue(
            to=creator.email,
            subject=rendered["subject"],
            html=rendered["html"],
            text=rendered.get("text"),
            metadata={"template": "invite_accepted", "doc_id": doc.id},
        )
    except Exception as exc:
        logger.warning("Failed to enqueue invite_accepted email: %s", exc)

    return {"doc_id": doc.id, "accepter": accepter.email}
```

- [x] **Step 4: Run tests**

Run: `uv run pytest tests/test_invites.py -v`
Expected: PASS.

---

## Task 11: `/settings/notifications` stub page

**Files:**
- Create: `src/markland/web/settings.py`
- Create: `tests/test_settings_notifications.py`
- Modify: `src/markland/web/app.py` (include the new router)

- [x] **Step 1: Write the failing test**

Create `tests/test_settings_notifications.py`:

```python
"""Stub settings page so the footer 'Manage notifications' link resolves."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn)
    with TestClient(app) as c:
        yield c


def test_settings_notifications_returns_coming_soon(client):
    r = client.get("/settings/notifications")
    assert r.status_code == 200
    assert "coming soon" in r.text.lower()
    assert "notification" in r.text.lower()


def test_settings_notifications_is_html(client):
    r = client.get("/settings/notifications")
    assert r.headers["content-type"].startswith("text/html")
```

- [x] **Step 2: Run tests — fail**

Run: `uv run pytest tests/test_settings_notifications.py -v`
Expected: FAIL — route does not exist.

- [x] **Step 3: Create the router**

Create `src/markland/web/settings.py`:

```python
"""Settings pages. Only /settings/notifications is implemented at launch — stub."""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_NOTIFICATIONS_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Notification settings — Markland</title>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f6f6f4; color: #1a1a1a; margin: 0; padding: 48px 16px; }}
  main {{ max-width: 560px; margin: 0 auto; background: #fff;
          border: 1px solid #e5e5e2; border-radius: 8px; padding: 32px; }}
  h1 {{ margin: 0 0 12px 0; font-size: 22px; }}
  p  {{ line-height: 1.55; color: #3a3a38; }}
  .muted {{ color: #6b6b68; font-size: 13px; }}
  a {{ color: #1a1a1a; }}
</style>
</head>
<body>
<main>
  <h1>Notification settings</h1>
  <p><strong>Coming soon.</strong> Per-user notification preferences are not available at launch.</p>
  <p>For now, Markland sends transactional email only: magic-link login, grant created,
     grant level changed, agent-grant to the agent's owner, and invite accepted. These
     are required for the product to function and cannot be disabled.</p>
  <p class="muted">If you're receiving mail you didn't expect, reply to this email or
     contact support and we'll investigate.</p>
  <p><a href="/">&larr; Back to Markland</a></p>
</main>
</body>
</html>
"""


@router.get("/settings/notifications", response_class=HTMLResponse)
def notifications_settings() -> HTMLResponse:
    return HTMLResponse(_NOTIFICATIONS_PAGE)
```

- [x] **Step 4: Register the router**

In `src/markland/web/app.py`, inside `create_app` (after the existing routes are declared, before `if mount_mcp:`):

```python
from markland.web.settings import router as settings_router
app.include_router(settings_router)
```

- [x] **Step 5: Run tests**

Run: `uv run pytest tests/test_settings_notifications.py -v`
Expected: PASS (2 tests).

---

## Task 12: End-to-end integration tests

**Files:**
- Create: `tests/test_email_integration.py`

Two scenarios: (a) happy path — granting a doc results in exactly one `EmailClient.send` call with the right subject/to; (b) resilience — when `EmailClient.send` raises repeatedly, the dispatcher drops the message and the grant still succeeded.

- [x] **Step 1: Write the tests**

Create `tests/test_email_integration.py`:

```python
"""End-to-end: service call → dispatcher → EmailClient.send."""

import asyncio
from unittest.mock import MagicMock

import pytest

from markland.config import reset_config
from markland.db import init_db
from markland.service.email import EmailClient, EmailSendError
from markland.service.email_dispatcher import EmailDispatcher
from markland.service.grants import grant


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://markland.dev")
    reset_config()
    yield tmp_path
    reset_config()


@pytest.mark.asyncio
async def test_grant_triggers_one_client_send_with_correct_subject(env, seed_users_and_doc):
    bob, alice, doc = seed_users_and_doc
    db = init_db(env / "t.db")
    # seed: re-insert bob/alice/doc into this DB (helper from conftest)
    seed_users_and_doc.install(db)

    client = MagicMock(spec=EmailClient)
    client.send = MagicMock(return_value="email_1")
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        grant(
            db,
            base_url="https://markland.dev",
            principal=bob,
            doc_id=doc.id,
            target={"kind": "user_email", "email": alice.email},
            level="view",
            dispatcher=disp,
        )
        await disp.drain()
    finally:
        await disp.stop()

    assert client.send.call_count == 1
    kwargs = client.send.call_args.kwargs
    assert kwargs["to"] == alice.email
    assert kwargs["subject"].startswith(f'{bob.display_name} shared')
    assert "view access" in kwargs["subject"]
    assert kwargs["text"]  # plaintext was sent alongside html
    assert kwargs["html"].startswith("<!DOCTYPE")
    assert kwargs["metadata"]["template"] == "user_grant"


@pytest.mark.asyncio
async def test_grant_succeeds_even_when_client_always_fails(env, seed_users_and_doc, caplog):
    bob, alice, doc = seed_users_and_doc
    db = init_db(env / "t.db")
    seed_users_and_doc.install(db)

    client = MagicMock(spec=EmailClient)
    client.send = MagicMock(side_effect=EmailSendError("resend down"))
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        grant(
            db,
            base_url="https://markland.dev",
            principal=bob,
            doc_id=doc.id,
            target={"kind": "user_email", "email": alice.email},
            level="edit",
            dispatcher=disp,
        )
        await disp.drain()
    finally:
        await disp.stop()

    # Grant row persisted regardless of email outcome.
    row = db.execute(
        "SELECT level FROM grants WHERE doc_id=? AND grantee_email=?",
        (doc.id, alice.email),
    ).fetchone()
    assert row is not None and row[0] == "edit"

    # 1 initial + 3 retries = 4 attempts, then drop.
    assert client.send.call_count == 4
    assert any("dropping email" in r.message.lower() for r in caplog.records)
```

- [x] **Step 2: Provide the `seed_users_and_doc` fixture**

In `tests/conftest.py` (create or extend):

```python
from dataclasses import dataclass
from types import SimpleNamespace

import pytest


@dataclass
class _Seed:
    bob: SimpleNamespace
    alice: SimpleNamespace
    doc: SimpleNamespace

    def install(self, db):
        """Insert these rows into the given DB connection."""
        db.execute(
            "INSERT INTO users (id, email, display_name) VALUES (?, ?, ?)",
            (self.bob.id, self.bob.email, self.bob.display_name),
        )
        db.execute(
            "INSERT INTO users (id, email, display_name) VALUES (?, ?, ?)",
            (self.alice.id, self.alice.email, self.alice.display_name),
        )
        db.execute(
            "INSERT INTO documents (id, title, content, share_token, owner_user_id, is_public) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (self.doc.id, self.doc.title, self.doc.content,
             self.doc.share_token, self.bob.id),
        )
        db.commit()

    def __iter__(self):
        return iter((self.bob, self.alice, self.doc))


@pytest.fixture
def seed_users_and_doc():
    bob = SimpleNamespace(id="u_bob", email="bob@example.com", display_name="Bob")
    alice = SimpleNamespace(id="u_alice", email="alice@example.com", display_name="Alice")
    doc = SimpleNamespace(
        id="d_1", title="Quarterly plan", content="# Hi",
        share_token="tok_1", owner_user_id="u_bob",
    )
    return _Seed(bob=bob, alice=alice, doc=doc)
```

(If Plan 3/4/5 already set up user/doc schema fixtures, reuse and trim this.)

- [x] **Step 3: Run the integration tests**

Run: `uv run pytest tests/test_email_integration.py -v`
Expected: PASS (2 tests).

- [x] **Step 4: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: all prior tests + new tests pass. Total new test files: `test_email_templates.py`, `test_email_dispatcher.py`, `test_email_integration.py`, `test_settings_notifications.py` + updates to `test_email_service.py`, `test_magic_link.py`, `test_grants.py`, `test_invites.py`.

---

## Completion criteria

- `uv run pytest tests/ -v` passes with the new test files: `test_email_templates.py` (7 tests), `test_email_dispatcher.py` (5 tests), `test_email_integration.py` (2 tests), `test_settings_notifications.py` (2 tests). Existing `test_email_service.py`, `test_magic_link.py`, `test_grants.py`, `test_invites.py` pass with updated assertions.
- Every row of the spec §7 email matrix is implemented: `user_grant`, `user_grant_level_changed`, `agent_grant` (user-owned only), `invite_accepted`, `magic_link`. Grant-revoked and token/agent-revoked emit no email (asserted implicitly — no code path dispatches them).
- Service-owned agents receive no email when granted — explicit branch in `grant` (agent target).
- Every sent email includes both `html` and `text` bodies, plus `Manage notifications` footer link to `/settings/notifications`.
- `GET /settings/notifications` returns HTTP 200 with a "coming soon" notice.
- `MARKLAND_ADMIN_TOKEN=t uv run python src/markland/run_app.py` logs `EmailDispatcher started` at boot and `EmailDispatcher stopped` on shutdown.
- Grants succeed even when `EmailClient.send` raises repeatedly — integration test asserts the grant row persists after 4 failed send attempts.
- Retry schedule is 1s / 3s / 10s with ±25% jitter (verified by reading `DEFAULT_RETRY_DELAYS` and `_jitter_frac` in `email_dispatcher.py`).

## What this plan does NOT deliver

- **User notification preferences.** The footer link goes to a stub page. There is no per-user opt-out, no per-category toggle, no unsubscribe-link-with-signed-token. A future plan (`2026-??-??-notification-preferences.md`) adds a preferences table, a "why did I get this?" page per email, and real unsubscribe link wiring.
- **Digest / batching.** Every trigger sends immediately. No once-per-day rollup.
- **Persistent retry queue.** The in-process queue is lost on process restart — acceptable for v1 per spec §7 ("lightweight in-process"). When Resend outages or deploy-triggered drops become operationally painful, a follow-up plan moves the queue to Redis or a `pending_emails` SQLite table. Per spec §17, that lands only when the pain is measurable.
- **Delivery analytics.** Resend provides open/click metrics in its own dashboard; we don't ingest them.
- **Localization.** Templates are English only. i18n arrives post-launch if a non-English user base emerges.
- **Grant-revoked / token-revoked emails.** Spec §7 explicitly excludes them ("low value, noisy"). Not implemented here and not planned.
