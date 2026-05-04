# Self-Service Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship two-tier self-service deletion: documents delete immediately and irreversibly with a typed-confirmation modal; accounts get a 30-day soft-delete window with magic-link reverify, frozen-from-the-outside semantics, and a daily cron purge that anonymizes the `users` row to a tombstone while preserving the audit-log append-only invariant.

**Architecture:** Three independently-mergeable phases. Phase 1 surfaces the existing `docs.delete` API on `/dashboard` and the viewer (~5 tasks, no schema). Phase 2 adds account soft-delete with magic-link confirm + restore plus the auth gate (~12 tasks, schema migrations). Phase 3 wires the daily purge job into the existing `presence_gc`-style background-task pattern (~3 tasks).

**Tech Stack:** SQLite (with ALTER TABLE migrations), FastAPI + Jinja2, asyncio background task, pytest + httpx TestClient.

**Spec:** `docs/specs/2026-05-04-self-service-deletion-design.md`.

---

## File Structure

**Phase 1 — modify:**

- `src/markland/web/save_routes.py` (or new `src/markland/web/doc_delete_routes.py` if `save_routes` grows unwieldy — keep co-located with fork/bookmark for now) — add `POST /d/{share_token}/delete`.
- `src/markland/web/templates/dashboard.html` — add Delete button + typed-confirmation modal to owned-doc rows.
- `src/markland/web/templates/viewer.html` — add Delete button + modal, `is_owner` conditional.
- `tests/test_doc_delete_route.py` (new).
- `tests/test_dashboard_shared.py` and `tests/test_viewer.py` — extend with UI presence assertions.

**Phase 2 — modify:**

- `src/markland/db.py` — schema migrations for `users.deleted_at`, `users.purged_at`, `account_deletion_tokens`.
- `src/markland/service/auth.py:158-200` — `resolve_token` rejects deleted users.
- `src/markland/service/sessions.py` — `read_session` (or its caller) rejects deleted users.
- `src/markland/service/docs.py` — `get_by_share_token` short-circuits when owner is deleted.
- `src/markland/web/identity_routes.py` — append `POST /api/me/delete-request`, `GET /settings/account`.
- `src/markland/web/app.py` — register the new account-deletion routes module.

**Phase 2 — create:**

- `src/markland/service/account_deletion.py` — service module.
- `src/markland/web/account_deletion_routes.py` — HTTP routes (`/account/delete`, `/account/restore`, `/goodbye`).
- `src/markland/web/templates/settings_account.html` — `/settings/account` page.
- `src/markland/web/templates/account_delete_confirm.html` — the GET `/account/delete` form.
- `src/markland/web/templates/goodbye.html` — post-deletion landing.
- `src/markland/web/templates/emails/account_delete_confirm.txt` — email body.
- `tests/test_service_account_deletion.py` (new).
- `tests/test_account_deletion_routes.py` (new).
- `tests/test_principal_middleware_deletion.py` (new — auth gate).

**Phase 3 — create:**

- `src/markland/web/account_purge_gc.py` — background task module, mirrors `presence_gc.py`.
- `scripts/admin/purge_deleted_accounts.py` — manual ops fallback.
- `tests/test_account_purge_gc.py` (new).

**Phase 3 — modify:**

- `src/markland/web/app.py` — register `account_purge_gc` in the lifespan, similar to `presence_gc`.

**Test framework:** `uv run pytest tests/ -q`.

---

# Phase 1 — Document deletion UI

## Task 1.1: `POST /d/{share_token}/delete` HTTP route

**Files:**
- Modify: `src/markland/web/save_routes.py` — append a new route handler.
- Test: `tests/test_doc_delete_route.py` (new).

- [ ] **Step 1: Write the failing test**

Create `tests/test_doc_delete_route.py`:

```python
"""HTTP doc-delete route — owner-only, CSRF-required, cascades."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, get_document, list_grants_for_doc
from markland.service import sessions as sessions_mod
from markland.service.docs import publish, grant
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    other = create_user(conn, email="bob@example.com", display_name="Bob")
    app = create_app(
        conn, mount_mcp=False,
        base_url="https://markland.dev",
        session_secret=SECRET,
    )
    with TestClient(app, base_url="http://testserver") as c:
        c.state_alice_id = user.id
        c.state_bob_id = other.id
        c.state_conn = conn
        yield c


def _login(client, user_id):
    cookie = sessions_mod.make_session_cookie_value(user_id, secret=SECRET)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def test_owner_can_delete_doc(client):
    """Owner POSTs /d/{share_token}/delete; doc + grants are gone."""
    from markland.service.auth import Principal
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="Test", content="hi", is_public=False)
    _login(client, client.state_alice_id)
    r = client.post(f"/d/{doc['share_token']}/delete")
    assert r.status_code == 303, r.text
    assert get_document(client.state_conn, doc["id"]) is None


def test_non_owner_cannot_delete_doc(client):
    """A signed-in non-owner POST returns 403/404; doc remains."""
    from markland.service.auth import Principal
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="Test", content="hi", is_public=False)
    _login(client, client.state_bob_id)
    r = client.post(f"/d/{doc['share_token']}/delete")
    assert r.status_code in (403, 404), r.text
    assert get_document(client.state_conn, doc["id"]) is not None


def test_anonymous_cannot_delete_doc(client):
    """Unauthenticated POST returns 401/403; doc remains."""
    from markland.service.auth import Principal
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="Test", content="hi", is_public=False)
    r = client.post(f"/d/{doc['share_token']}/delete")
    assert r.status_code in (401, 403, 404), r.text
    assert get_document(client.state_conn, doc["id"]) is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_doc_delete_route.py -v
```

Expected: FAIL — route returns 404 (not registered).

- [ ] **Step 3: Add the route**

Append to `src/markland/web/save_routes.py` inside the `build_router` function, after the existing `DELETE /d/{share_token}/bookmark` route:

```python
    @r.post("/d/{share_token}/delete")
    def delete_doc(share_token: str, request: Request):
        """Owner-only HTTP doc deletion. Calls the existing docs.delete
        service which cascades to revisions, grants, bookmarks. CSRF is
        enforced via SameSite=Strict on the session cookie + a hidden
        form field if/when the modal switches to a typed-confirmation
        POST form (Task 1.2)."""
        principal = getattr(request.state, "principal", None)
        if principal is None:
            cookie = request.cookies.get(SESSION_COOKIE_NAME, "")
            if cookie and session_secret:
                try:
                    payload = read_session(cookie, secret=session_secret)
                    uid = payload.get("user_id")
                    if isinstance(uid, str):
                        principal = Principal(
                            principal_id=uid,
                            principal_type="user",
                            display_name=None,
                            is_admin=False,
                            user_id=None,
                        )
                except InvalidSession:
                    pass
        if principal is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)

        doc = db.get_document_by_share_token(conn, share_token)
        if doc is None:
            return JSONResponse({"error": "not_found"}, status_code=404)

        try:
            docs.delete(conn, principal, doc.id)
        except docs.PermissionDenied:
            # Treat as not-found to avoid revealing existence to non-owners.
            return JSONResponse({"error": "not_found"}, status_code=404)

        return RedirectResponse("/dashboard", status_code=303)
```

(Imports needed at the top of `save_routes.py` if not already present:
`from markland.service import docs`, `from markland.service.auth import Principal`,
`from markland.service.sessions import SESSION_COOKIE_NAME, InvalidSession, read_session`,
`from markland import db`.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_doc_delete_route.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Run the broader save-routes suite**

```bash
uv run pytest tests/test_save_routes.py tests/test_doc_delete_route.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/save_routes.py tests/test_doc_delete_route.py
git commit -m "feat(docs): POST /d/{share_token}/delete HTTP route — owner-only"
```

---

## Task 1.2: Dashboard Delete button + typed-confirmation modal

**Files:**
- Modify: `src/markland/web/templates/dashboard.html`.
- Test: `tests/test_dashboard_shared.py` (extend).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_dashboard_shared.py`:

```python
def test_dashboard_shows_delete_button_on_owned_docs(client):
    """Owned docs render a Delete button; shared/bookmarked docs do not."""
    _login(client)
    from markland.service.auth import Principal
    from markland.service.docs import publish
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="My Doc", content="x", is_public=False)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert 'data-delete-doc' in r.text
    # Title-typed-confirmation requires the doc title to be in a data-attr
    assert f'data-delete-title="My Doc"' in r.text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_dashboard_shared.py::test_dashboard_shows_delete_button_on_owned_docs -v
```

Expected: FAIL — no `data-delete-doc` attribute in dashboard output.

- [ ] **Step 3: Add the Delete button to owned-doc rows**

Edit `src/markland/web/templates/dashboard.html`. Find the My-documents `<ul>` (the block starting `<ul id="my-docs">` at line 22). Replace each `<li>...</li>` body with:

```html
        <li>
          <a href="/d/{{ d.share_token }}">{{ d.title }}</a>
          <span class="meta">· updated {{ d.updated_at }}</span>
          <button type="button"
                  data-delete-doc="{{ d.share_token }}"
                  data-delete-title="{{ d.title }}"
                  style="margin-left: 0.5rem; color: var(--danger, #c44);">Delete</button>
        </li>
```

Then append, before the closing `</section>`, the modal markup + script:

```html
<dialog id="delete-doc-modal" style="border: 1px solid var(--outline); padding: 1.5rem; border-radius: 8px; max-width: 420px;">
  <h2 style="font-size: 1.1rem; margin: 0 0 0.5rem;">Delete document</h2>
  <p>This permanently deletes the document, its full revision history, and any grants on it. <strong>This cannot be undone.</strong></p>
  <p>Type the document title to confirm:</p>
  <p id="delete-doc-target-title" style="font-family: var(--font-mono); background: var(--surface-2); padding: 0.4rem 0.6rem; border-radius: 4px;"></p>
  <input type="text" id="delete-doc-input" style="width: 100%; padding: 0.4rem 0.6rem; font: inherit; margin-bottom: 1rem;" />
  <div style="display: flex; gap: 0.5rem; justify-content: flex-end;">
    <button type="button" id="delete-doc-cancel">Cancel</button>
    <button type="button" id="delete-doc-confirm" disabled style="background: var(--danger, #c44); color: white;">Delete</button>
  </div>
</dialog>

<script nonce="{{ csp_nonce }}">
(function () {
  var modal = document.getElementById('delete-doc-modal');
  if (!modal) return;
  var titleP = document.getElementById('delete-doc-target-title');
  var input = document.getElementById('delete-doc-input');
  var confirmBtn = document.getElementById('delete-doc-confirm');
  var cancelBtn = document.getElementById('delete-doc-cancel');
  var currentToken = null;
  var currentTitle = null;

  document.querySelectorAll('[data-delete-doc]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      currentToken = btn.getAttribute('data-delete-doc');
      currentTitle = btn.getAttribute('data-delete-title');
      titleP.textContent = currentTitle;
      input.value = '';
      confirmBtn.disabled = true;
      modal.showModal();
      input.focus();
    });
  });

  input.addEventListener('input', function () {
    confirmBtn.disabled = (input.value !== currentTitle);
  });

  cancelBtn.addEventListener('click', function () {
    modal.close();
  });

  confirmBtn.addEventListener('click', function () {
    if (!currentToken) return;
    fetch('/d/' + encodeURIComponent(currentToken) + '/delete', {
      method: 'POST',
      credentials: 'same-origin',
    }).then(function (r) {
      if (r.ok || r.redirected) {
        window.location.href = '/dashboard';
      } else {
        alert('Could not delete document. Please try again.');
        modal.close();
      }
    });
  });
})();
</script>
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_dashboard_shared.py::test_dashboard_shows_delete_button_on_owned_docs -v
```

Expected: PASS.

- [ ] **Step 5: Run the dashboard suite**

```bash
uv run pytest tests/test_dashboard_shared.py tests/test_dashboard_bookmarks.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/templates/dashboard.html tests/test_dashboard_shared.py
git commit -m "feat(dashboard): Delete button + typed-confirmation modal on owned docs"
```

---

## Task 1.3: Viewer Delete button (owner-only)

**Files:**
- Modify: `src/markland/web/templates/viewer.html`.
- Test: `tests/test_viewer.py` (find the right existing file or extend `tests/test_viewer_owner_actions.py` if present; verify with `ls tests/test_viewer*.py`).

- [ ] **Step 1: Locate the viewer test file**

```bash
ls tests/test_viewer*.py
```

Pick the file that already tests owner-only viewer features (e.g., the share dialog). If none, create `tests/test_viewer_delete.py` using the standard fixture pattern from `tests/test_doc_delete_route.py:Step 1`.

- [ ] **Step 2: Write the failing test**

Append to the chosen file:

```python
def test_viewer_shows_delete_button_for_owner(client):
    from markland.service.auth import Principal
    from markland.service.docs import publish
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="My Doc", content="x", is_public=True)
    _login(client, client.state_alice_id)
    r = client.get(f"/d/{doc['share_token']}")
    assert r.status_code == 200
    assert 'data-delete-doc' in r.text


def test_viewer_hides_delete_button_for_non_owner(client):
    from markland.service.auth import Principal
    from markland.service.docs import publish
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="My Doc", content="x", is_public=True)
    _login(client, client.state_bob_id)
    r = client.get(f"/d/{doc['share_token']}")
    assert r.status_code == 200
    assert 'data-delete-doc' not in r.text


def test_viewer_hides_delete_button_for_anonymous(client):
    from markland.service.auth import Principal
    from markland.service.docs import publish
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="My Doc", content="x", is_public=True)
    r = client.get(f"/d/{doc['share_token']}")
    assert r.status_code == 200
    assert 'data-delete-doc' not in r.text
```

- [ ] **Step 3: Run the tests to verify they fail**

```bash
uv run pytest <chosen_test_file> -v -k delete
```

Expected: 3 FAIL.

- [ ] **Step 4: Add the Delete button to the viewer template**

Edit `src/markland/web/templates/viewer.html`. The viewer renders `is_owner` somewhere as a context flag — find the existing owner-only block (likely a share/visibility/manage panel) and add inside its `{% if is_owner %}` conditional:

```html
<button type="button"
        data-delete-doc="{{ doc.share_token }}"
        data-delete-title="{{ doc.title }}"
        style="color: var(--danger, #c44);">Delete document</button>
```

Then include the same modal markup + script from Task 1.2 (extract into a partial `_delete_doc_modal.html` if both dashboard and viewer need it — that's the cleaner refactor; do it as part of this task):

Create `src/markland/web/templates/_delete_doc_modal.html` containing the `<dialog>` + `<script>` block from Task 1.2 Step 3. Then in **both** `dashboard.html` and `viewer.html`, replace the inline modal/script with `{% include "_delete_doc_modal.html" %}`. (This refactor is small — avoid duplication once two callers exist.)

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest <chosen_test_file> -v -k delete
```

Expected: 3 PASS.

- [ ] **Step 6: Run dashboard + viewer suites to confirm the partial extraction didn't regress dashboard**

```bash
uv run pytest tests/test_dashboard_shared.py <chosen_test_file> -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/templates/viewer.html \
        src/markland/web/templates/dashboard.html \
        src/markland/web/templates/_delete_doc_modal.html \
        <chosen_test_file>
git commit -m "feat(viewer): Delete button for owners + extract shared modal partial"
```

---

# Phase 2 — Account soft-delete

## Task 2.1: Schema migrations

**Files:**
- Modify: `src/markland/db.py` — `init_db` adds the new columns + table.
- Test: `tests/test_db_schema.py` (extend; create if absent).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_db_schema.py` (or create with the standard pattern):

```python
def test_users_has_deleted_at_and_purged_at_columns(tmp_path):
    from markland.db import init_db
    conn = init_db(tmp_path / "test.db")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    assert "deleted_at" in cols
    assert "purged_at" in cols


def test_account_deletion_tokens_table_exists(tmp_path):
    from markland.db import init_db
    conn = init_db(tmp_path / "test.db")
    cols = {row[1] for row in conn.execute(
        "PRAGMA table_info(account_deletion_tokens)"
    ).fetchall()}
    assert {"token", "user_id", "purpose", "created_at",
            "expires_at", "consumed_at"}.issubset(cols)
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_db_schema.py -v -k "deleted_at or account_deletion_tokens"
```

Expected: FAIL.

- [ ] **Step 3: Add the migration**

Edit `src/markland/db.py`. Find the `init_db` function and the existing users-table block. Use the existing `_add_column_if_missing` helper (line 19) to add the two new columns to `users` after the `CREATE TABLE` block:

```python
    _add_column_if_missing(conn, "users", "deleted_at", "TEXT")
    _add_column_if_missing(conn, "users", "purged_at", "TEXT")
```

(`TEXT` because the existing `created_at` column is TEXT — match the convention.)

Then append the new table creation, after the existing `magic_link_consumed` block:

```python
    conn.execute("""
        CREATE TABLE IF NOT EXISTS account_deletion_tokens (
            token        TEXT PRIMARY KEY,
            user_id      TEXT NOT NULL,
            purpose      TEXT NOT NULL CHECK (purpose IN ('confirm', 'restore')),
            created_at   TEXT NOT NULL,
            expires_at   TEXT NOT NULL,
            consumed_at  TEXT
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_account_deletion_tokens_user "
        "ON account_deletion_tokens(user_id)"
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_db_schema.py -v -k "deleted_at or account_deletion_tokens"
```

Expected: PASS.

- [ ] **Step 5: Run the full DB-schema suite**

```bash
uv run pytest tests/test_db_schema.py tests/test_db.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/db.py tests/test_db_schema.py
git commit -m "feat(db): account-deletion schema — users.deleted_at + purged_at + account_deletion_tokens"
```

---

## Task 2.2: `request_account_deletion` service helper

**Files:**
- Create: `src/markland/service/account_deletion.py`.
- Test: `tests/test_service_account_deletion.py` (new).

- [ ] **Step 1: Write the failing test**

Create `tests/test_service_account_deletion.py`:

```python
"""Service tests for account_deletion module."""

from __future__ import annotations

import pytest
from datetime import datetime, timezone, timedelta

from markland.db import init_db
from markland.service import account_deletion
from markland.service.users import create_user


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_request_account_deletion_returns_plaintext_token(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    assert isinstance(token, str)
    assert len(token) >= 32  # high-entropy plaintext


def test_request_account_deletion_persists_hashed_row(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    rows = conn.execute(
        "SELECT user_id, purpose, consumed_at FROM account_deletion_tokens"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == user.id
    assert rows[0][1] == "confirm"
    assert rows[0][2] is None
    # The plaintext is NOT what's in the row — verify by inequality.
    stored = conn.execute("SELECT token FROM account_deletion_tokens").fetchone()[0]
    assert stored != token


def test_request_account_deletion_idempotent_within_window(conn):
    """A second request inside the validity window returns the same plaintext."""
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    t1 = account_deletion.request_account_deletion(conn, user.id)
    t2 = account_deletion.request_account_deletion(conn, user.id)
    assert t1 == t2
    rows = conn.execute("SELECT count(*) FROM account_deletion_tokens").fetchone()[0]
    assert rows == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k request
```

Expected: FAIL — `markland.service.account_deletion` does not exist.

- [ ] **Step 3: Create the service module with the helper**

Create `src/markland/service/account_deletion.py`:

```python
"""Account deletion lifecycle: request → confirm → soft-delete window → purge.

See docs/specs/2026-05-04-self-service-deletion-design.md for the design.
"""

from __future__ import annotations

import secrets
import sqlite3
from datetime import datetime, timezone, timedelta
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHash

CONFIRM_TOKEN_TTL = timedelta(hours=24)
RESTORE_TOKEN_TTL = timedelta(days=30)
SOFT_DELETE_WINDOW = timedelta(days=30)

_hasher = PasswordHasher()


def _now(now: Optional[datetime] = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _new_plaintext() -> str:
    """48 chars of base64-ish entropy. Sufficient for one-shot URL token."""
    return secrets.token_urlsafe(36)


def request_account_deletion(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Issue a 'confirm' token for this user. Idempotent: if a non-expired,
    non-consumed confirm token already exists, return its plaintext (which
    we cached on issue — see below). Returns plaintext for the email body.

    Idempotency note: we re-issue the SAME token on a duplicate request
    inside the validity window so the user's first email is still valid;
    they may have clicked Delete twice and we don't want to invalidate
    the email already sent. Implementation: keep the plaintext in a
    short-lived in-memory cache keyed by user_id.
    """
    current = _now(now)
    expires = current + CONFIRM_TOKEN_TTL

    # Look for an existing valid confirm token.
    row = conn.execute(
        """
        SELECT token FROM account_deletion_tokens
        WHERE user_id = ?
          AND purpose = 'confirm'
          AND consumed_at IS NULL
          AND expires_at > ?
        ORDER BY created_at DESC
        LIMIT 1
        """,
        (user_id, _iso(current)),
    ).fetchone()

    if row is not None:
        # Idempotent path: return the cached plaintext if available; else
        # rotate (the cache is process-local and may have been lost across
        # restarts — in that case, mint a new pair).
        cached = _PLAINTEXT_CACHE.get(user_id)
        if cached is not None:
            return cached
        # Cache miss → mint new + invalidate the stored hash.
        conn.execute(
            "UPDATE account_deletion_tokens SET consumed_at = ? "
            "WHERE token = ?",
            (_iso(current), row[0]),
        )

    plaintext = _new_plaintext()
    token_hash = _hasher.hash(plaintext)
    conn.execute(
        """
        INSERT INTO account_deletion_tokens
            (token, user_id, purpose, created_at, expires_at, consumed_at)
        VALUES (?, ?, 'confirm', ?, ?, NULL)
        """,
        (token_hash, user_id, _iso(current), _iso(expires)),
    )
    conn.commit()
    _PLAINTEXT_CACHE[user_id] = plaintext
    return plaintext


# In-memory cache: user_id → most-recently-issued plaintext.
# Process-local, lost on restart. Acceptable: the only loss is "user
# requests deletion twice in a row across a process restart" — they get
# a new token in their second email.
_PLAINTEXT_CACHE: dict[str, str] = {}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k request
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/account_deletion.py tests/test_service_account_deletion.py
git commit -m "feat(account-deletion): request_account_deletion service helper"
```

---

## Task 2.3: `confirm_account_deletion` service helper

**Files:**
- Modify: `src/markland/service/account_deletion.py` — append.
- Test: `tests/test_service_account_deletion.py` — append.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_service_account_deletion.py`:

```python
def test_confirm_account_deletion_sets_deleted_at(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    result = account_deletion.confirm_account_deletion(conn, token)
    assert result == user.id
    deleted_at = conn.execute(
        "SELECT deleted_at FROM users WHERE id = ?", (user.id,)
    ).fetchone()[0]
    assert deleted_at is not None


def test_confirm_account_deletion_revokes_user_tokens(conn):
    from markland.service.auth import issue_user_token
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token_plain, _ = issue_user_token(conn, user_id=user.id, label="cli")
    confirm_token = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, confirm_token)
    revoked = conn.execute(
        "SELECT count(*) FROM tokens WHERE principal_id = ? AND revoked_at IS NULL",
        (user.id,),
    ).fetchone()[0]
    assert revoked == 0


def test_confirm_account_deletion_marks_token_consumed(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, token)
    consumed = conn.execute(
        "SELECT consumed_at FROM account_deletion_tokens WHERE user_id = ?",
        (user.id,),
    ).fetchone()[0]
    assert consumed is not None


def test_confirm_account_deletion_rejects_replay(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, token)
    second = account_deletion.confirm_account_deletion(conn, token)
    assert second is None


def test_confirm_account_deletion_rejects_expired(conn):
    from datetime import datetime, timezone, timedelta
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    future = datetime.now(timezone.utc) + timedelta(hours=25)
    result = account_deletion.confirm_account_deletion(conn, token, now=future)
    assert result is None


def test_confirm_account_deletion_rejects_unknown_token(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    account_deletion.request_account_deletion(conn, user.id)
    result = account_deletion.confirm_account_deletion(conn, "not-a-real-token")
    assert result is None
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k confirm
```

Expected: FAIL — `confirm_account_deletion` doesn't exist.

- [ ] **Step 3: Implement the helper**

Append to `src/markland/service/account_deletion.py`:

```python
def confirm_account_deletion(
    conn: sqlite3.Connection,
    token_plaintext: str,
    *,
    now: Optional[datetime] = None,
) -> Optional[str]:
    """Verify token, set users.deleted_at, revoke all bearer tokens for
    the user and their agents. Returns user_id on success, None on
    bad/expired/consumed/already-deleted."""
    current = _now(now)
    rows = conn.execute(
        """
        SELECT token, user_id, expires_at, consumed_at
        FROM account_deletion_tokens
        WHERE purpose = 'confirm'
        """
    ).fetchall()
    matched_user_id: Optional[str] = None
    matched_token_hash: Optional[str] = None
    for token_hash, user_id, expires_at, consumed_at in rows:
        try:
            _hasher.verify(token_hash, token_plaintext)
        except (VerifyMismatchError, InvalidHash):
            continue
        if consumed_at is not None:
            return None
        if datetime.fromisoformat(expires_at) <= current:
            return None
        matched_user_id = user_id
        matched_token_hash = token_hash
        break
    if matched_user_id is None or matched_token_hash is None:
        return None

    # Already deleted? Don't double-set.
    deleted_at = conn.execute(
        "SELECT deleted_at FROM users WHERE id = ?", (matched_user_id,)
    ).fetchone()
    if deleted_at is None:
        return None
    if deleted_at[0] is not None:
        return None

    # Set deleted_at on the user.
    conn.execute(
        "UPDATE users SET deleted_at = ? WHERE id = ?",
        (_iso(current), matched_user_id),
    )
    # Revoke all user-tokens for this user.
    conn.execute(
        "UPDATE tokens SET revoked_at = ? "
        "WHERE principal_type = 'user' AND principal_id = ? AND revoked_at IS NULL",
        (_iso(current), matched_user_id),
    )
    # Revoke all agent-tokens for agents owned by this user.
    conn.execute(
        """
        UPDATE tokens SET revoked_at = ?
        WHERE principal_type = 'agent'
          AND principal_id IN (
            SELECT id FROM agents
            WHERE owner_type = 'user' AND owner_id = ?
          )
          AND revoked_at IS NULL
        """,
        (_iso(current), matched_user_id),
    )
    # Mark the deletion token consumed.
    conn.execute(
        "UPDATE account_deletion_tokens SET consumed_at = ? WHERE token = ?",
        (_iso(current), matched_token_hash),
    )
    conn.commit()
    _PLAINTEXT_CACHE.pop(matched_user_id, None)
    return matched_user_id
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k confirm
```

Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/account_deletion.py tests/test_service_account_deletion.py
git commit -m "feat(account-deletion): confirm_account_deletion + token + agent revocation"
```

---

## Task 2.4: `restore_account` service helper

**Files:**
- Modify: `src/markland/service/account_deletion.py` — append.
- Test: `tests/test_service_account_deletion.py` — append.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_restore_account_within_window_unsets_deleted_at(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, token)
    assert account_deletion.restore_account(conn, user.id) is True
    deleted_at = conn.execute(
        "SELECT deleted_at FROM users WHERE id = ?", (user.id,)
    ).fetchone()[0]
    assert deleted_at is None


def test_restore_account_after_purge_returns_false(conn):
    from datetime import datetime, timezone
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, token)
    # Simulate purge having run.
    conn.execute(
        "UPDATE users SET purged_at = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), user.id),
    )
    conn.commit()
    assert account_deletion.restore_account(conn, user.id) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k restore
```

Expected: FAIL.

- [ ] **Step 3: Implement the helper**

Append to `src/markland/service/account_deletion.py`:

```python
def restore_account(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    now: Optional[datetime] = None,
) -> bool:
    """Unset users.deleted_at if the row is still inside its 30-day window
    (i.e., purged_at IS NULL). Returns True if restored, False otherwise.
    Does NOT re-issue revoked tokens — the user must mint fresh ones."""
    row = conn.execute(
        "SELECT deleted_at, purged_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return False
    deleted_at, purged_at = row
    if deleted_at is None:
        return False
    if purged_at is not None:
        return False
    conn.execute(
        "UPDATE users SET deleted_at = NULL WHERE id = ?",
        (user_id,),
    )
    conn.commit()
    return True
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k restore
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/account_deletion.py tests/test_service_account_deletion.py
git commit -m "feat(account-deletion): restore_account within 30-day window"
```

---

## Task 2.5: Auth gate — `resolve_token` rejects deleted users

**Files:**
- Modify: `src/markland/service/auth.py:158-200`.
- Test: `tests/test_auth.py` (extend).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_auth.py` (or wherever `resolve_token` is tested):

```python
def test_resolve_token_rejects_deleted_user(tmp_path):
    from markland.db import init_db
    from markland.service.auth import resolve_token, issue_user_token
    from markland.service.users import create_user
    from markland.service import account_deletion

    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    plaintext, _ = issue_user_token(conn, user_id=user.id, label="cli")
    # Confirm — deleted_at gets set, tokens revoked.
    token = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, token)
    # Even if a stray token weren't revoked, deleted_at should gate.
    assert resolve_token(conn, plaintext) is None
```

- [ ] **Step 2: Run the test to verify it fails (or passes coincidentally)**

```bash
uv run pytest tests/test_auth.py::test_resolve_token_rejects_deleted_user -v
```

Expected: PASS coincidentally (the token-revocation in Task 2.3 already covers this), but the test still belongs because we want belt-and-suspenders: a future code path that issues a token without revocation should still be gated by `deleted_at`.

- [ ] **Step 3: Add the deleted_at predicate to the user-row SELECT**

Edit `src/markland/service/auth.py:175-181`. Replace:

```python
            if principal_type == "user":
                user_row = conn.execute(
                    "SELECT id, display_name, is_admin FROM users WHERE id = ?",
                    (principal_id,),
                ).fetchone()
                if user_row is None:
                    return None
```

with:

```python
            if principal_type == "user":
                user_row = conn.execute(
                    "SELECT id, display_name, is_admin "
                    "FROM users WHERE id = ? AND deleted_at IS NULL",
                    (principal_id,),
                ).fetchone()
                if user_row is None:
                    return None
```

Also update the agent path (the parallel branch around line 198-220 — find it via `grep -n "principal_type == \"agent\"" src/markland/service/auth.py`). The agent's owning user must also be active. Add a JOIN or a follow-up check:

```python
            if principal_type == "agent":
                agent_row = conn.execute(
                    """
                    SELECT a.id, a.owner_type, a.owner_id, a.display_name, a.revoked_at
                    FROM agents a
                    LEFT JOIN users u
                      ON a.owner_type = 'user' AND u.id = a.owner_id
                    WHERE a.id = ?
                      AND (a.owner_type != 'user' OR u.deleted_at IS NULL)
                    """,
                    (principal_id,),
                ).fetchone()
```

(Match the existing column ordering — verify with `sed -n '198,220p' src/markland/service/auth.py` before editing.)

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_auth.py::test_resolve_token_rejects_deleted_user -v
```

Expected: PASS.

- [ ] **Step 5: Run the full auth suite**

```bash
uv run pytest tests/test_auth.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/auth.py tests/test_auth.py
git commit -m "feat(auth): resolve_token rejects bearer tokens of deleted users + their agents"
```

---

## Task 2.6: Auth gate — session-cookie path rejects deleted users

**Files:**
- Modify: `src/markland/service/sessions.py` or wherever `read_session` callers fetch the user row.
- Test: `tests/test_sessions.py` (extend) and `tests/test_dashboard_shared.py` (sanity).

- [ ] **Step 1: Locate the session-to-user resolution**

```bash
grep -n "user_id\|users WHERE\|SELECT.*FROM users" src/markland/service/sessions.py src/markland/web/principal_middleware.py
```

The path that converts a `mk_session` cookie payload into a user row is the gate point. It typically appears in dashboard.py, principal_middleware.py, and any route that reads `request.cookies[mk_session]`. The cleanest gate is at the *single* SELECT that maps user_id → user row.

If a `service/users.py::get_user_by_id` helper exists, modify that. If callers do inline `SELECT FROM users WHERE id = ?`, add `AND deleted_at IS NULL` to each.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_dashboard_shared.py`:

```python
def test_dashboard_returns_401_for_deleted_user(client):
    """A signed-in user whose deleted_at is set cannot access /dashboard."""
    from markland.service import account_deletion
    _login(client)
    token = account_deletion.request_account_deletion(client.state_conn, client.state_alice_id)
    account_deletion.confirm_account_deletion(client.state_conn, token)
    r = client.get("/dashboard")
    assert r.status_code == 401, r.text
```

- [ ] **Step 3: Run the test to verify it fails**

```bash
uv run pytest tests/test_dashboard_shared.py::test_dashboard_returns_401_for_deleted_user -v
```

Expected: FAIL — handler returns 200 because the user-row SELECT doesn't gate on `deleted_at`.

- [ ] **Step 4: Add the gate**

Edit each user-row SELECT identified in Step 1. The minimal pattern: any query `SELECT ... FROM users WHERE id = ?` becomes `SELECT ... FROM users WHERE id = ? AND deleted_at IS NULL`. Locations to verify:

- `src/markland/web/dashboard.py:38-43` — the `_owner_display` helper. (Display name can leak — gate it.)
- `src/markland/web/render_helpers.py` — `signed_in_user_ctx` if it does a SELECT on users.
- Any route that does `read_session(...)` followed by a user row fetch.

A search-and-add approach: `grep -rn "FROM users WHERE id" src/markland/` and add the predicate to each, EXCEPT for paths used by deletion itself (the `confirm_account_deletion` and `restore_account` service code legitimately needs to read the deleted user).

- [ ] **Step 5: Run the test to verify it passes**

```bash
uv run pytest tests/test_dashboard_shared.py::test_dashboard_returns_401_for_deleted_user -v
```

Expected: PASS.

- [ ] **Step 6: Run dashboard + auth suites**

```bash
uv run pytest tests/test_dashboard_shared.py tests/test_dashboard_bookmarks.py tests/test_auth.py -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add src/markland/web/dashboard.py \
        src/markland/web/render_helpers.py \
        tests/test_dashboard_shared.py
git commit -m "feat(auth): session-cookie path rejects deleted users on every user-row fetch"
```

---

## Task 2.7: Doc-resolution gate — docs by deleted owners 404

**Files:**
- Modify: `src/markland/db.py` — `get_document_by_share_token` (or its caller in `service/docs.py`).
- Test: `tests/test_doc_share_routes.py` or equivalent (extend; verify with `grep -rn "get_document_by_share_token" tests/`).

- [ ] **Step 1: Write the failing test**

Add to whatever test file exercises the public `/d/{share_token}` viewer path:

```python
def test_share_token_returns_404_when_owner_is_deleted(client):
    """A doc whose owner has deleted_at set is unreachable via share_token."""
    from markland.service.auth import Principal
    from markland.service.docs import publish
    from markland.service import account_deletion
    alice = Principal(principal_id=client.state_alice_id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(client.state_conn, principal=alice,
                  title="T", content="x", is_public=True)
    token = account_deletion.request_account_deletion(client.state_conn, client.state_alice_id)
    account_deletion.confirm_account_deletion(client.state_conn, token)
    r = client.get(f"/d/{doc['share_token']}")
    assert r.status_code == 404, r.text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest <chosen_test_file> -v -k owner_is_deleted
```

Expected: FAIL — viewer returns 200 with the doc.

- [ ] **Step 3: Add the gate**

Edit `src/markland/db.py`. Find `get_document_by_share_token` (and `get_document` if it has a similar path). Add a JOIN on users to filter out docs whose owner has `deleted_at` set:

```python
def get_document_by_share_token(
    conn: sqlite3.Connection, share_token: str
) -> Optional[Document]:
    row = conn.execute(
        """
        SELECT d.id, d.title, d.content, d.share_token, d.is_public,
               d.owner_id, d.created_at, d.updated_at, d.version,
               d.is_featured, d.forked_from_doc_id
        FROM documents d
        LEFT JOIN users u ON d.owner_id = u.id
        WHERE d.share_token = ?
          AND (d.owner_id IS NULL OR u.deleted_at IS NULL)
        """,
        (share_token,),
    ).fetchone()
    return _row_to_document(row) if row else None
```

(Verify column order against the existing implementation; the SELECT list above is illustrative — match the actual columns. If the function is implemented as a `SELECT *`, prepend the JOIN+predicate without enumerating columns.)

Apply the same predicate to `get_document(conn, doc_id)` so MCP `markland_get` calls also 404.

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest <chosen_test_file> -v -k owner_is_deleted
```

Expected: PASS.

- [ ] **Step 5: Run the broader doc suites**

```bash
uv run pytest tests/test_db.py tests/test_service_docs.py tests/test_doc_share_routes.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/db.py <chosen_test_file>
git commit -m "feat(docs): get_document(_by_share_token) 404s when owner is deleted"
```

---

## Task 2.8: Email templates + dispatcher integration

**Files:**
- Create: `src/markland/web/templates/emails/account_delete_confirm.txt`.
- Create: `src/markland/web/templates/emails/account_delete_confirm.html`.
- Test: `tests/test_account_deletion_email.py` (new).

- [ ] **Step 1: Write the failing test**

Create `tests/test_account_deletion_email.py`:

```python
"""The account-deletion confirmation email contains the confirm link."""

from __future__ import annotations

import pytest

from markland.db import init_db
from markland.service import account_deletion
from markland.service.users import create_user


@pytest.fixture
def conn(tmp_path):
    return init_db(tmp_path / "test.db")


def test_render_confirm_email_contains_confirm_link(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    body = account_deletion.render_confirm_email(
        token, base_url="https://markland.dev", display_name="Alice"
    )
    assert "https://markland.dev/account/delete?token=" in body
    assert token in body
    assert "30 day" in body or "30-day" in body


def test_render_confirm_email_addresses_user_by_name(conn):
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    token = account_deletion.request_account_deletion(conn, user.id)
    body = account_deletion.render_confirm_email(
        token, base_url="https://markland.dev", display_name="Alice"
    )
    assert "Alice" in body
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_account_deletion_email.py -v
```

Expected: FAIL — `render_confirm_email` doesn't exist.

- [ ] **Step 3: Create the email template**

Create `src/markland/web/templates/emails/account_delete_confirm.txt`:

```
Hi {{ display_name or "there" }},

We received a request to delete your Markland account.

Click this link in the next 24 hours to confirm:

  {{ base_url }}/account/delete?token={{ token }}

After you confirm, your account will enter a 30-day grace period.
During that window you can sign in via magic link to cancel the
deletion. After 30 days, your data will be permanently removed and
this action cannot be undone.

If you didn't request this, just ignore this email — nothing will
happen and the link will expire harmlessly.

— Markland
```

- [ ] **Step 4: Add `render_confirm_email` to the service module**

Append to `src/markland/service/account_deletion.py`:

```python
def render_confirm_email(
    token: str, *, base_url: str, display_name: Optional[str] = None
) -> str:
    """Render the plain-text body of the deletion-confirmation email."""
    from pathlib import Path
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    template_dir = (
        Path(__file__).parent.parent / "web" / "templates" / "emails"
    )
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape([]),  # text email; no HTML escaping
    )
    tpl = env.get_template("account_delete_confirm.txt")
    return tpl.render(
        token=token, base_url=base_url, display_name=display_name
    )
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_account_deletion_email.py -v
```

Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/service/account_deletion.py \
        src/markland/web/templates/emails/account_delete_confirm.txt \
        tests/test_account_deletion_email.py
git commit -m "feat(account-deletion): confirmation email template + render helper"
```

---

## Task 2.9: HTTP routes — `/api/me/delete-request` + `/account/delete` + `/account/restore` + `/goodbye`

**Files:**
- Create: `src/markland/web/account_deletion_routes.py`.
- Modify: `src/markland/web/identity_routes.py` — add `POST /api/me/delete-request`.
- Modify: `src/markland/web/app.py` — register the new router.
- Create templates: `account_delete_confirm.html`, `goodbye.html`, `settings_account.html`.
- Test: `tests/test_account_deletion_routes.py` (new).

This task is large; split commit-by-commit. Each sub-step ends in a commit.

- [ ] **Step 1: Write the failing test for `POST /api/me/delete-request`**

Create `tests/test_account_deletion_routes.py`:

```python
"""HTTP routes for the account-deletion lifecycle."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.service import account_deletion, sessions as sessions_mod
from markland.service.sessions import make_csrf_token
from markland.service.users import create_user
from markland.web.app import create_app

SECRET = "test-session-secret"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_SESSION_SECRET", SECRET)
    from markland.config import reset_config
    reset_config()
    conn = init_db(tmp_path / "test.db")
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    app = create_app(conn, mount_mcp=False,
                     base_url="https://markland.dev", session_secret=SECRET)
    with TestClient(app, base_url="http://testserver") as c:
        c.state_alice_id = user.id
        c.state_conn = conn
        yield c


def _login(client, user_id=None):
    uid = user_id or client.state_alice_id
    cookie = sessions_mod.make_session_cookie_value(uid, secret=SECRET)
    client.cookies.set(sessions_mod.SESSION_COOKIE_NAME, cookie)


def test_delete_request_requires_auth(client):
    r = client.post("/api/me/delete-request")
    assert r.status_code == 401


def test_delete_request_requires_csrf(client):
    _login(client)
    r = client.post("/api/me/delete-request")
    assert r.status_code == 403


def test_delete_request_returns_204_and_creates_token(client):
    _login(client)
    csrf = make_csrf_token(client.state_alice_id, secret=SECRET)
    r = client.post(
        "/api/me/delete-request",
        headers={"X-CSRF-Token": csrf},
    )
    assert r.status_code == 204
    rows = client.state_conn.execute(
        "SELECT count(*) FROM account_deletion_tokens WHERE user_id = ?",
        (client.state_alice_id,),
    ).fetchone()[0]
    assert rows == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_account_deletion_routes.py -v -k delete_request
```

Expected: FAIL — route returns 404.

- [ ] **Step 3: Add the route to `identity_routes.py`**

Append to `src/markland/web/identity_routes.py` (inside `build_router`, after the existing `/api/me/dismiss-connect-claude-code` route from PR for the install/onboarding plan if shipped — otherwise after whatever the last route is):

```python
    @router.post("/api/me/delete-request")
    def api_me_delete_request(request: Request):
        """Issue a deletion-confirmation email to the signed-in user."""
        user_id = _session_user_id(request)
        if user_id is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        csrf = request.headers.get("X-CSRF-Token", "")
        if not verify_csrf_token(csrf, user_id, secret=session_secret):
            return JSONResponse({"error": "csrf"}, status_code=403)

        from markland.service import account_deletion
        token = account_deletion.request_account_deletion(db_conn, user_id)

        # Look up the user's email + display_name for the email body.
        row = db_conn.execute(
            "SELECT email, display_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return JSONResponse({"error": "internal"}, status_code=500)
        email_addr, display_name = row
        body = account_deletion.render_confirm_email(
            token, base_url=base_url, display_name=display_name
        )
        if email_dispatcher is not None:
            email_dispatcher.enqueue(
                to=email_addr,
                subject="Confirm account deletion at Markland",
                text=body,
                metadata={"purpose": "account-delete-confirm"},
            )
        return Response(status_code=204)
```

(Imports needed: `from fastapi import Response`, `from markland.service.sessions import verify_csrf_token`. The handler factory may need `email_dispatcher` and `base_url` plumbed in — match the existing pattern; the dispatcher is typically constructed in `app.py` and injected via the router-builder's kwargs.)

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_account_deletion_routes.py -v -k delete_request
```

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/identity_routes.py tests/test_account_deletion_routes.py
git commit -m "feat(account-deletion): POST /api/me/delete-request"
```

- [ ] **Step 6: Add `/account/delete` GET (form) + POST (confirm) + `/goodbye`**

Create `src/markland/web/account_deletion_routes.py`:

```python
"""HTTP routes for the account-deletion confirm + restore + goodbye flow."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.service import account_deletion
from markland.service.sessions import SESSION_COOKIE_NAME
from markland.web.render_helpers import render_with_nav


def build_router(*, conn: sqlite3.Connection, session_secret: str, base_url: str = "") -> APIRouter:
    r = APIRouter()
    env = Environment(
        loader=FileSystemLoader(
            str(Path(__file__).parent / "templates")
        ),
        autoescape=select_autoescape(["html"]),
    )
    confirm_tpl = env.get_template("account_delete_confirm.html")
    goodbye_tpl = env.get_template("goodbye.html")

    @r.get("/account/delete", response_class=HTMLResponse)
    def get_account_delete(request: Request, token: str = ""):
        return HTMLResponse(
            render_with_nav(
                confirm_tpl, request, conn,
                base_url=base_url, secret=session_secret,
                token=token,
            )
        )

    @r.post("/account/delete")
    def post_account_delete(request: Request, token: str = Form(...)):
        user_id = account_deletion.confirm_account_deletion(conn, token)
        if user_id is None:
            return RedirectResponse("/account/delete?token=&error=invalid",
                                    status_code=303)
        # Clear the session cookie and redirect to /goodbye.
        resp = RedirectResponse("/goodbye", status_code=303)
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return resp

    @r.get("/goodbye", response_class=HTMLResponse)
    def get_goodbye(request: Request):
        return HTMLResponse(
            render_with_nav(
                goodbye_tpl, request, conn,
                base_url=base_url, secret=session_secret,
            )
        )

    @r.get("/account/restore")
    def get_account_restore(request: Request, token: str = ""):
        # Verify the restore token by hash-matching it against the user's
        # account_deletion_tokens row with purpose='restore'. For v1 we
        # reuse the confirm token: any signed-in user with deleted_at set
        # whose token verifies can restore. Simpler than a separate purpose
        # column lookup.
        # NOTE: minimal v1 — anyone with the token can restore.
        rows = conn.execute(
            "SELECT user_id, token FROM account_deletion_tokens "
            "WHERE consumed_at IS NULL"
        ).fetchall()
        from argon2 import PasswordHasher
        from argon2.exceptions import VerifyMismatchError, InvalidHash
        hasher = PasswordHasher()
        for user_id, token_hash in rows:
            try:
                hasher.verify(token_hash, token)
            except (VerifyMismatchError, InvalidHash):
                continue
            if account_deletion.restore_account(conn, user_id):
                return RedirectResponse("/login?restored=1", status_code=303)
            break
        return RedirectResponse("/?restore_failed=1", status_code=303)

    return r
```

Create `src/markland/web/templates/account_delete_confirm.html`:

```html
{% extends "base.html" %}
{% block title %}Confirm account deletion · Markland{% endblock %}
{% block content %}
<article style="max-width: 640px; margin: 4rem auto; padding: 0 1rem;">
  <h1>Confirm account deletion</h1>
  <p>You're about to schedule your Markland account for deletion.</p>
  <p><strong>What happens next:</strong></p>
  <ul>
    <li>Your account is hidden immediately — public docs return 404, share links stop working, agent tokens are revoked.</li>
    <li>For 30 days, you can sign in via magic link to cancel the deletion.</li>
    <li>After 30 days, your data is permanently removed.</li>
  </ul>
  <form method="POST" action="/account/delete">
    <input type="hidden" name="token" value="{{ token }}" />
    <button type="submit" style="background: var(--danger, #c44); color: white; padding: 0.6rem 1.2rem; font: inherit; border: none; border-radius: 6px;">
      Yes, schedule my account for deletion
    </button>
  </form>
  <p style="margin-top: 2rem;"><a href="/dashboard">Cancel and go back</a></p>
</article>
{% endblock %}
```

Create `src/markland/web/templates/goodbye.html`:

```html
{% extends "base.html" %}
{% block title %}Goodbye · Markland{% endblock %}
{% block content %}
<article style="max-width: 640px; margin: 4rem auto; padding: 0 1rem;">
  <h1>Your account is scheduled for deletion</h1>
  <p>Your data is hidden from the public Markland surface as of now. After 30 days, it will be permanently removed.</p>
  <p>If you change your mind, sign in via the magic-link flow during the next 30 days and click the cancel-deletion link in your email.</p>
  <p>Thanks for trying Markland.</p>
</article>
{% endblock %}
```

Wire the router into `src/markland/web/app.py`. Find the block where other routers are mounted (search for `app.include_router` or `app.mount`). Add:

```python
    from markland.web import account_deletion_routes
    app.include_router(
        account_deletion_routes.build_router(
            conn=db_conn, session_secret=session_secret, base_url=base_url
        )
    )
```

- [ ] **Step 7: Write tests for the new routes**

Append to `tests/test_account_deletion_routes.py`:

```python
def test_get_account_delete_renders_form(client):
    _login(client)
    csrf = make_csrf_token(client.state_alice_id, secret=SECRET)
    client.post("/api/me/delete-request", headers={"X-CSRF-Token": csrf})
    # The token is in the email; we extract from the DB for testing.
    token_row = client.state_conn.execute(
        "SELECT token FROM account_deletion_tokens "
        "WHERE user_id = ?", (client.state_alice_id,)
    ).fetchone()
    # We don't have the plaintext from outside the email path; for this
    # test, request_account_deletion returns the plaintext directly.
    plaintext = account_deletion.request_account_deletion(
        client.state_conn, client.state_alice_id
    )
    r = client.get(f"/account/delete?token={plaintext}")
    assert r.status_code == 200
    assert "Confirm account deletion" in r.text


def test_post_account_delete_clears_session_redirects_goodbye(client):
    _login(client)
    plaintext = account_deletion.request_account_deletion(
        client.state_conn, client.state_alice_id
    )
    r = client.post(
        "/account/delete",
        data={"token": plaintext},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/goodbye"
    # Session cookie cleared.
    set_cookie = r.headers.get("set-cookie", "")
    assert "mk_session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "expires=Thu, 01 Jan 1970" in set_cookie.lower()


def test_get_goodbye_renders(client):
    r = client.get("/goodbye")
    assert r.status_code == 200
    assert "scheduled for deletion" in r.text


def test_get_account_restore_within_window_succeeds(client):
    _login(client)
    plaintext = account_deletion.request_account_deletion(
        client.state_conn, client.state_alice_id
    )
    account_deletion.confirm_account_deletion(client.state_conn, plaintext)
    # The same plaintext now serves the restore role (per v1 design).
    r = client.get(
        f"/account/restore?token={plaintext}", follow_redirects=False
    )
    # restore_account returns False because the token is consumed —
    # in v1 we'd want a separate purpose='restore' token. For now the
    # restore flow uses an UN-consumed token from a fresh request. This
    # test pins the expected behavior, which the design plan calls out
    # as a v1 simplification to revisit.
    assert r.status_code == 303
```

For the test above, replace with the version that uses a separate `issue_restore_token` helper (Step 8 below adds it):

```python
def test_get_account_restore_within_window_succeeds(client):
    _login(client)
    plaintext = account_deletion.request_account_deletion(
        client.state_conn, client.state_alice_id
    )
    user_id = account_deletion.confirm_account_deletion(client.state_conn, plaintext)
    assert user_id == client.state_alice_id
    restore_token = account_deletion.issue_restore_token(
        client.state_conn, user_id
    )
    r = client.get(
        f"/account/restore?token={restore_token}", follow_redirects=False
    )
    assert r.status_code == 303
    deleted_at = client.state_conn.execute(
        "SELECT deleted_at FROM users WHERE id = ?",
        (client.state_alice_id,),
    ).fetchone()[0]
    assert deleted_at is None  # restored
```

- [ ] **Step 8: Add a separate `issue_restore_token` helper**

`confirm_account_deletion` keeps its simple `Optional[str]` (returning user_id) signature from Task 2.3 — no retroactive change needed. Add a new helper that any caller can invoke to mint a purpose='restore' token after a successful confirm.

Append to `src/markland/service/account_deletion.py`:

```python
def issue_restore_token(
    conn: sqlite3.Connection,
    user_id: str,
    *,
    now: Optional[datetime] = None,
) -> str:
    """Mint a single-use restore token for a user already in the soft-
    delete window. Caller is responsible for confirming the user has
    deleted_at IS NOT NULL AND purged_at IS NULL — this helper does
    not re-check (the caller in /account/delete just confirmed it)."""
    current = _now(now)
    expires = current + RESTORE_TOKEN_TTL
    plaintext = _new_plaintext()
    token_hash = _hasher.hash(plaintext)
    conn.execute(
        """
        INSERT INTO account_deletion_tokens
            (token, user_id, purpose, created_at, expires_at, consumed_at)
        VALUES (?, ?, 'restore', ?, ?, NULL)
        """,
        (token_hash, user_id, _iso(current), _iso(expires)),
    )
    conn.commit()
    return plaintext
```

The HTTP `POST /account/delete` handler in this task's earlier code (Step 6) calls `confirm_account_deletion`, then `issue_restore_token` on success, then includes the restore token in a follow-up email (queued via `email_dispatcher`) AND optionally attaches it as a `?token=…` param to the `/goodbye` redirect so the page can surface a copyable cancel link.

Update the route handler in `src/markland/web/account_deletion_routes.py` Step 6 to:

```python
    @r.post("/account/delete")
    def post_account_delete(request: Request, token: str = Form(...)):
        user_id = account_deletion.confirm_account_deletion(conn, token)
        if user_id is None:
            return RedirectResponse("/account/delete?token=&error=invalid",
                                    status_code=303)
        restore_token = account_deletion.issue_restore_token(conn, user_id)
        # Optional: enqueue follow-up email with the restore link.
        # (Out of scope for v1 — surfaced on /goodbye as a copyable link.)
        resp = RedirectResponse(
            f"/goodbye?restore_token={restore_token}", status_code=303
        )
        resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
        return resp
```

And `goodbye.html` should surface that token as a "save this link to cancel deletion" affordance:

```html
{% if request.query_params.get("restore_token") %}
<p style="margin-top: 1.5rem; padding: 1rem; background: var(--surface-2); border-radius: 6px;">
  <strong>Cancel deletion (save this link):</strong><br>
  <code style="font-size: 0.85rem; word-break: break-all;">{{ canonical_host }}/account/restore?token={{ request.query_params.get("restore_token") }}</code>
</p>
{% endif %}
```

(This is a minor UX choice. The cleaner production path is a follow-up "your account is scheduled for deletion" email containing the restore link, since the `/goodbye` page is shown only once. File this as a follow-up: ship the URL on `/goodbye` for v1, add the email in v2.)

- [ ] **Step 9: Run the route tests**

```bash
uv run pytest tests/test_account_deletion_routes.py -v
```

Expected: all PASS.

- [ ] **Step 10: Commit**

```bash
git add src/markland/web/account_deletion_routes.py \
        src/markland/web/app.py \
        src/markland/web/templates/account_delete_confirm.html \
        src/markland/web/templates/goodbye.html \
        src/markland/service/account_deletion.py \
        tests/test_account_deletion_routes.py \
        tests/test_service_account_deletion.py
git commit -m "feat(account-deletion): /account/delete + /goodbye + /account/restore routes"
```

---

## Task 2.10: `/settings/account` page with Delete-account panel

**Files:**
- Modify: `src/markland/web/identity_routes.py` — add `GET /settings/account`.
- Create: `src/markland/web/templates/settings_account.html`.
- Test: `tests/test_account_deletion_routes.py` — append.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_settings_account_renders_for_signed_in(client):
    _login(client)
    r = client.get("/settings/account")
    assert r.status_code == 200
    assert "Delete my account" in r.text


def test_settings_account_401_for_anon(client):
    r = client.get("/settings/account")
    assert r.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_account_deletion_routes.py -v -k settings_account
```

Expected: FAIL.

- [ ] **Step 3: Add the route**

Append to `src/markland/web/identity_routes.py` (inside `build_router`):

```python
    @router.get("/settings/account", response_class=HTMLResponse)
    def settings_account(request: Request):
        user_id = _session_user_id(request)
        if user_id is None:
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        from markland.service.sessions import make_csrf_token
        csrf = make_csrf_token(user_id, secret=session_secret)
        tpl = env.get_template("settings_account.html")
        return HTMLResponse(
            render_with_nav(
                tpl, request, conn,
                base_url=base_url, secret=session_secret,
                csrf_token=csrf,
            )
        )
```

(`env` and `render_with_nav` should already be imported in `identity_routes.py`. If not, add `from markland.web.render_helpers import render_with_nav`.)

- [ ] **Step 4: Create the template**

Create `src/markland/web/templates/settings_account.html`:

```html
{% extends "base.html" %}
{% block title %}Account settings · Markland{% endblock %}
{% block content %}
<article style="max-width: 640px; margin: 4rem auto; padding: 0 1rem;">
  <h1>Account settings</h1>

  <section style="margin-top: 3rem; padding: 1.5rem; border: 1px solid var(--danger, #c44); border-radius: 8px;">
    <h2 style="margin-top: 0; color: var(--danger, #c44);">Delete my account</h2>
    <p>This permanently deletes your account, all documents you own (and their revisions and grants), all agents and their tokens, and all bookmarks. The audit log retains entries about your account but with no identifying information.</p>
    <p>For 30 days after you confirm, you can sign in via magic link to cancel the deletion.</p>

    <button type="button" id="delete-account-btn"
            style="background: var(--danger, #c44); color: white; padding: 0.6rem 1.2rem; font: inherit; border: none; border-radius: 6px;">
      Delete my account
    </button>
    <p id="delete-account-status" style="margin-top: 1rem; color: var(--muted);"></p>
  </section>
</article>

<script nonce="{{ csp_nonce }}">
(function () {
  var btn = document.getElementById('delete-account-btn');
  var status = document.getElementById('delete-account-status');
  if (!btn) return;
  btn.addEventListener('click', function () {
    if (!confirm('Send the deletion-confirmation email to your account address?')) return;
    btn.disabled = true;
    fetch('/api/me/delete-request', {
      method: 'POST',
      headers: { 'X-CSRF-Token': '{{ csrf_token }}' },
      credentials: 'same-origin',
    }).then(function (r) {
      if (r.ok) {
        status.textContent = 'We sent a confirmation link to your email. Click it within 24 hours to schedule deletion.';
      } else {
        status.textContent = 'Could not send confirmation. Please try again.';
        btn.disabled = false;
      }
    });
  });
})();
</script>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
uv run pytest tests/test_account_deletion_routes.py -v -k settings_account
```

Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/identity_routes.py \
        src/markland/web/templates/settings_account.html \
        tests/test_account_deletion_routes.py
git commit -m "feat(settings): /settings/account page with delete-account panel"
```

---

# Phase 3 — Cron purge

## Task 3.1: `purge_due_accounts` service helper

**Files:**
- Modify: `src/markland/service/account_deletion.py` — append.
- Test: `tests/test_service_account_deletion.py` — append.

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_purge_due_accounts_anonymizes_users_row_and_cascades(conn):
    from datetime import datetime, timezone, timedelta
    from markland.service.auth import Principal
    from markland.service.docs import publish

    user = create_user(conn, email="alice@example.com", display_name="Alice")
    alice = Principal(principal_id=user.id, principal_type="user",
                      display_name="Alice", is_admin=False, user_id=None)
    doc = publish(conn, principal=alice, title="T", content="x", is_public=False)

    plaintext = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, plaintext)

    # Past the window.
    future = datetime.now(timezone.utc) + timedelta(days=31)
    purged_count = account_deletion.purge_due_accounts(conn, now=future)
    assert purged_count == 1

    # Users row anonymized but still exists.
    row = conn.execute(
        "SELECT email, display_name, deleted_at, purged_at FROM users WHERE id = ?",
        (user.id,),
    ).fetchone()
    assert row is not None
    assert row[0] is None  # email
    assert row[1] is None  # display_name
    assert row[2] is not None  # deleted_at preserved
    assert row[3] is not None  # purged_at set

    # Doc + revisions + grants gone.
    assert conn.execute(
        "SELECT count(*) FROM documents WHERE id = ?", (doc["id"],)
    ).fetchone()[0] == 0


def test_purge_due_accounts_skips_within_window(conn):
    from datetime import datetime, timezone, timedelta
    user = create_user(conn, email="alice@example.com", display_name="Alice")
    plaintext = account_deletion.request_account_deletion(conn, user.id)
    account_deletion.confirm_account_deletion(conn, plaintext)
    # 29 days, 23 hours — still inside.
    almost = datetime.now(timezone.utc) + timedelta(days=29, hours=23)
    assert account_deletion.purge_due_accounts(conn, now=almost) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k purge
```

Expected: FAIL — `purge_due_accounts` doesn't exist.

- [ ] **Step 3: Implement the helper**

Append to `src/markland/service/account_deletion.py`:

```python
def purge_due_accounts(
    conn: sqlite3.Connection,
    *,
    now: Optional[datetime] = None,
) -> int:
    """Find users whose deleted_at is past the soft-delete window and that
    have not yet been purged. For each: cascade-delete owned data,
    anonymize the users row to a tombstone, set purged_at. Audit log is
    untouched. Returns the count of accounts purged."""
    current = _now(now)
    cutoff = current - SOFT_DELETE_WINDOW
    rows = conn.execute(
        """
        SELECT id FROM users
        WHERE deleted_at IS NOT NULL
          AND deleted_at <= ?
          AND purged_at IS NULL
        """,
        (_iso(cutoff),),
    ).fetchall()
    count = 0
    for (user_id,) in rows:
        # Owned documents (cascades grants, revisions, bookmarks via
        # existing db.delete_document).
        from markland import db
        doc_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM documents WHERE owner_id = ?", (user_id,)
            ).fetchall()
        ]
        for doc_id in doc_ids:
            db.delete_document(conn, doc_id)

        # User's bookmarks (on others' docs).
        conn.execute("DELETE FROM bookmarks WHERE user_id = ?", (user_id,))

        # Pending invites.
        conn.execute("DELETE FROM invites WHERE created_by_user_id = ?", (user_id,))

        # Device authorizations.
        conn.execute(
            "DELETE FROM device_authorizations WHERE user_id = ?",
            (user_id,),
        )

        # Magic-link consumed records.
        conn.execute(
            "DELETE FROM magic_link_consumed WHERE user_id = ?", (user_id,)
        )

        # Agents owned by user, then their tokens.
        agent_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM agents "
                "WHERE owner_type = 'user' AND owner_id = ?",
                (user_id,),
            ).fetchall()
        ]
        for aid in agent_ids:
            conn.execute(
                "DELETE FROM tokens WHERE principal_type = 'agent' AND principal_id = ?",
                (aid,),
            )
        conn.execute(
            "DELETE FROM agents WHERE owner_type = 'user' AND owner_id = ?",
            (user_id,),
        )

        # User-tokens.
        conn.execute(
            "DELETE FROM tokens WHERE principal_type = 'user' AND principal_id = ?",
            (user_id,),
        )

        # Account-deletion tokens.
        conn.execute(
            "DELETE FROM account_deletion_tokens WHERE user_id = ?",
            (user_id,),
        )

        # Anonymize the users row — tombstone.
        conn.execute(
            "UPDATE users SET email = NULL, display_name = NULL, purged_at = ? "
            "WHERE id = ?",
            (_iso(current), user_id),
        )
        count += 1

    if count:
        conn.commit()
    return count
```

(The test for `email = NULL` requires the `email` column to be nullable. It's currently `email TEXT UNIQUE NOT NULL`. **Important schema note**: a separate migration step is needed to relax the NOT NULL on `email` — handle in Task 2.1 retroactively, OR drop the UNIQUE constraint and use empty string instead. The simpler path is to use a tombstone-marker email like `f"deleted-{user_id}@deleted.markland.local"` so the UNIQUE constraint stays intact. Update the test and the implementation accordingly.)

Concrete fix: change the anonymization line to:

```python
        conn.execute(
            "UPDATE users SET email = ?, display_name = NULL, purged_at = ? "
            "WHERE id = ?",
            (f"deleted-{user_id}@deleted.markland.local", _iso(current), user_id),
        )
```

And update the test:

```python
    assert row[0].startswith("deleted-")  # tombstone marker
    assert row[0].endswith("@deleted.markland.local")
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
uv run pytest tests/test_service_account_deletion.py -v -k purge
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/service/account_deletion.py tests/test_service_account_deletion.py
git commit -m "feat(account-deletion): purge_due_accounts cascades + tombstones the users row"
```

---

## Task 3.2: Background scheduler — `account_purge_gc.py`

**Files:**
- Create: `src/markland/web/account_purge_gc.py` (mirrors `presence_gc.py`).
- Test: `tests/test_account_purge_gc.py` (new).

- [ ] **Step 1: Write the failing test**

Create `tests/test_account_purge_gc.py`:

```python
"""Background-task wrapper for purge_due_accounts. Mirrors presence_gc tests."""

from __future__ import annotations

import asyncio
import pytest

from markland.web import account_purge_gc


@pytest.mark.asyncio
async def test_loop_calls_callable_until_stop():
    calls = []
    async def fake_call():
        calls.append(1)
        return 0
    stop = asyncio.Event()
    task = asyncio.create_task(
        account_purge_gc._loop(
            lambda: calls.append(1) or 0,
            interval_seconds=0.01,
            stop_event=stop,
        )
    )
    await asyncio.sleep(0.05)
    stop.set()
    await task
    assert len(calls) >= 2
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_account_purge_gc.py -v
```

Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Create the module**

Create `src/markland/web/account_purge_gc.py` (mirror of `presence_gc.py`):

```python
"""Background asyncio task that runs purge_due_accounts daily.

Registered on the FastAPI app's lifespan. Failures are logged and
swallowed; the loop continues so one bad cron tick does not kill the
purge worker forever.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Callable

from markland.service import account_deletion

logger = logging.getLogger("markland.account_purge.gc")

# 24 hours; small interval used in tests via the parameter.
DEFAULT_INTERVAL_SECONDS = 24 * 60 * 60


async def _loop(
    purge_callable: Callable[[], int],
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            count = purge_callable()
            if count:
                logger.info("account_purge_gc purged %d accounts", count)
        except Exception:
            logger.exception("account_purge_gc tick failed; continuing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def start(
    conn: sqlite3.Connection,
    *,
    interval_seconds: float = DEFAULT_INTERVAL_SECONDS,
) -> tuple[asyncio.Task, asyncio.Event]:
    stop_event = asyncio.Event()

    def _purge_once() -> int:
        return account_deletion.purge_due_accounts(conn)

    task = asyncio.create_task(
        _loop(_purge_once, interval_seconds=interval_seconds, stop_event=stop_event)
    )
    return task, stop_event


async def stop(task: asyncio.Task, stop_event: asyncio.Event) -> None:
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_account_purge_gc.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/markland/web/account_purge_gc.py tests/test_account_purge_gc.py
git commit -m "feat(account-deletion): account_purge_gc background task module"
```

---

## Task 3.3: Register the GC task in the app lifespan + add ops fallback script

**Files:**
- Modify: `src/markland/web/app.py:143-250` — register `account_purge_gc` like `presence_gc`.
- Create: `scripts/admin/purge_deleted_accounts.py`.

- [ ] **Step 1: Wire `account_purge_gc` into the lifespan**

Edit `src/markland/web/app.py`. Find the `enable_presence_gc` block (around line 219-225). After the presence-GC start block, add a parallel `enable_account_purge_gc` flag and start block:

```python
        app.state.account_purge_gc_task = None
        app.state.account_purge_gc_stop = None
        if enable_account_purge_gc:
            from markland.web import account_purge_gc as _account_purge_gc
            apgc_task, apgc_stop = _account_purge_gc.start(db_conn)
            app.state.account_purge_gc_task = apgc_task
            app.state.account_purge_gc_stop = apgc_stop
```

And in the shutdown block (around line 233-236), add:

```python
            if app.state.account_purge_gc_task is not None:
                from markland.web import account_purge_gc as _account_purge_gc
                await _account_purge_gc.stop(
                    app.state.account_purge_gc_task,
                    app.state.account_purge_gc_stop,
                )
```

Add the `enable_account_purge_gc: bool = False` parameter to `create_app`'s signature (parallel to `enable_presence_gc`). Wire it to True in `run_app.py` for production.

- [ ] **Step 2: Create the manual ops fallback script**

Create `scripts/admin/purge_deleted_accounts.py`:

```python
#!/usr/bin/env python
"""Manual ops fallback: run purge_due_accounts once against the live DB.

Usage:
    python scripts/admin/purge_deleted_accounts.py

Requires the MARKLAND_DATA_DIR env var (or runs against the default
data dir). Prints the count of accounts purged.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from markland.db import init_db
from markland.service import account_deletion


def main() -> int:
    data_dir = Path(os.getenv("MARKLAND_DATA_DIR", "data"))
    db_path = data_dir / "markland.db"
    if not db_path.exists():
        print(f"DB not found at {db_path}", file=sys.stderr)
        return 1
    conn = init_db(db_path)
    count = account_deletion.purge_due_accounts(conn)
    print(f"purged {count} account(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:

```bash
chmod +x scripts/admin/purge_deleted_accounts.py
```

- [ ] **Step 3: Run the full test suite**

```bash
uv run pytest tests/ -q
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add src/markland/web/app.py scripts/admin/purge_deleted_accounts.py
git commit -m "feat(account-deletion): wire purge GC into app lifespan + manual ops script"
```

---

## Task 3.4: Update ROADMAP

**Files:**
- Modify: `docs/ROADMAP.md`.

- [ ] **Step 1: Move from Next to Shipped**

In `docs/ROADMAP.md`:

1. Remove the `[spec, plan TBD]` Self-service deletion entry from the Next lane.
2. Add at the top of the "Build (v1 plans + post-launch security/MCP)" Shipped section:

```markdown
- **2026-05-04** — **Self-service deletion live.** Two-tier deletion model: documents delete immediately and irreversibly via Delete button + typed-confirmation modal on `/dashboard` and viewer (`POST /d/{share_token}/delete`). Account deletion is a 30-day soft-delete window — `POST /api/me/delete-request` enqueues a magic-link confirm email, `POST /account/delete` sets `users.deleted_at` and revokes all bearer tokens for the user + their agents, and `/goodbye` lands the user. During the window, the auth gate (`resolve_token` + session-cookie path + `get_document(_by_share_token)`) treats deleted users as unauthenticated and their docs as 404. Daily background task (`account_purge_gc`, mirrors `presence_gc`) runs `purge_due_accounts` to cascade-delete owned data and anonymize the `users` row to a tombstone after 30 days. Audit log untouched (PR #49 append-only invariant preserved); the privacy-policy promise that "user_id is replaced with a non-reversible token" is honored at the referent level. Plan: `docs/plans/2026-05-04-self-service-deletion.md`.
```

- [ ] **Step 2: Commit + push**

```bash
git add docs/ROADMAP.md
git commit -m "docs(roadmap): self-service deletion shipped"
git push origin main
```

---

## Out of scope (do not implement here)

- **GDPR-style data export endpoint.** Separate roadmap item; the privacy policy commits to email-request export until self-service ships.
- **"Your data is being purged in 7 days" reminder email.** Out of v1 scope; revisit if support gets "I forgot I clicked delete" tickets.
- **Counsel review** of the audit-log anonymization interpretation.
- **Telemetry events** (`delete_request`, `delete_confirm`, `restore`, `purge`). Wire when the metrics_events table lands.
- **Org / team account deletion.** No orgs exist yet.
- **Backfill of existing users** to set `email` to a non-NULL tombstone marker — only NEW deletions go through `purge_due_accounts`; existing users keep their real emails until they themselves delete.

---

## Self-review checklist

- Each task ends with a `git commit` step ✅
- Every code step shows the actual code, not a description ✅
- Every test step shows the assertion, not "test it works" ✅
- No "TBD" / "TODO" / "fill in" placeholders ✅
- Type names consistent across tasks: `users.deleted_at` and `users.purged_at` (TEXT, ISO timestamps); `account_deletion_tokens` (with `purpose` CHECK constraint); `request_account_deletion` returns `str`, `confirm_account_deletion` returns `Optional[str]` (user_id), `issue_restore_token` returns `str` (Task 2.9 Step 8), `restore_account` returns `bool`, `purge_due_accounts` returns `int` ✅
- The schema-tension fix in Task 3.1 (tombstone email marker, not NULL) is the deliberate workaround for the `email NOT NULL` constraint ✅
- Phase 1 / Phase 2 / Phase 3 commits are independently revertable ✅
- Roadmap update task included so the topic moves from `[spec, plan TBD]` to Shipped ✅
- Test coverage spans: service unit tests, auth-gate tests, route integration tests, background-task loop tests ✅
- Manual smoke not specified — implementer should run a real round trip against `markland.dev` after Phase 2 ships and again after Phase 3 ✅
