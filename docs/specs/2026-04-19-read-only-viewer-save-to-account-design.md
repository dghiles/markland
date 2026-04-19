# Read-only viewer mobile polish + save-to-account

**Date:** 2026-04-19
**Status:** Draft — awaiting implementation plan

## Summary

Markland already renders public docs as read-only HTML at `GET /d/{share_token}` via `src/markland/web/app.py:291` and the `document.html` template. This spec does two things:

1. **Fix mobile render bugs** on the existing viewer so it holds up on a 375px-wide viewport.
2. **Add a "Save to Markland" CTA** for non-owners that offers both **fork** (create an owned copy) and **bookmark** (save a reference).

Logged-out viewers can trigger either action; they're routed through the existing magic-link flow and the action auto-resumes after signup.

## Motivation

- Phone-reading is the common case for shared doc links. A published-2026-04-19 doc with a wide GFM table, a long shell command, or an unbreakable identifier currently causes horizontal page scroll or clips the last column — both make Markland look broken on first touch.
- Once a viewer finds a doc they want to keep, there's no in-product path from "read" to "have it in my own account." The only options today are copy-paste into a terminal and `markland_publish` via MCP, which only works for existing users who already know the MCP story.
- The wedge is "shared knowledge that any agent — yours, a friend's, or automated — can read and write" (see memory: *Markland positioning*). Bookmarks and forks are the two cheapest primitives that let a viewer bring a doc into their own agent's reach.

## Scope

**In:**

- Two CSS fixes + one markdown-it renderer override on the existing read-only viewer.
- New `forked_from_doc_id` column on `documents`.
- New `bookmarks(user_id, doc_id, created_at)` table.
- `POST /d/{share_token}/fork`, `POST /d/{share_token}/bookmark`, `DELETE /d/{share_token}/bookmark`, `GET /resume`.
- Service-layer helpers `fork_document()` and `toggle_bookmark()`.
- `_save_dialog.html` partial rendered in `document.html` for non-owners: sticky bottom bar on mobile, top-right button on desktop, both opening a sheet/popover with **Save a copy** and **Add to library**.
- Pending-intent signed cookie for logged-out resume.
- Fork attribution line ("Forked from [Title] by [owner]") in the fork's meta bar.
- A "Saved" section on `/dashboard` listing bookmarked docs, with a remove control.

**Out:**

- Fork counts, lineage pages, or owner-side fork notifications.
- Preventing forks of public docs (all public docs are forkable).
- Bookmark folders, tags, or ordering.
- A separate inline signup modal (we reuse the existing magic-link landing).
- Any inline editor work (per *Markland launch scope* — MCP remains the editing surface).

## Mobile render bugs (verified via Playwright at 375×667)

At viewport width 375, `document.documentElement.scrollWidth == 474`. Two causes:

1. **Long unbreakable inline tokens.** An inline `<code>` span containing `this_is_a_very_long_command_name_without_breaks` measured 442px. `.content` and `code` have no `overflow-wrap` / `word-break`, so the token forces the column wider than the viewport.
2. **Wide tables are clipped, not scrolled.** A 5-column table measured 413px inside a ~327px column. The `<table>` itself has `border-radius` with `overflow: hidden` (`document.html:169`), so the last column is visibly truncated instead of reachable via horizontal scroll.

Pre blocks, blockquotes, lists, images, and hyphenated long URL labels render correctly at 375px.

### Fixes

In `document.html`:

```css
.content, .content p, .content li, .content td, .content th {
    overflow-wrap: anywhere;
    word-break: break-word;
}
.content code { overflow-wrap: anywhere; }

.content .table-scroll {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin: 1.3rem 0;
    border: 1px solid var(--outline);
    border-radius: var(--radius);
}
.content .table-scroll table {
    margin: 0;
    border: none;
    border-radius: 0;
}
```

In `src/markland/web/renderer.py`, override the `table_open` / `table_close` rules so markdown-it emits:

```html
<div class="table-scroll"><table>…</table></div>
```

### Verification gate

After implementation, re-seed the stress-test doc used during brainstorming and navigate Playwright to `/d/{token}` at 375×667. Pass when:

- `document.documentElement.scrollWidth <= window.innerWidth` (no page-level horizontal scroll).
- The `.table-scroll` wrapper around the wide table has `scrollWidth > clientWidth` (the table is horizontally scrollable inside its wrapper).
- Screenshot shows all 5 table columns reachable by horizontal swipe.

## Data model

```sql
ALTER TABLE documents ADD COLUMN forked_from_doc_id TEXT NULL
    REFERENCES documents(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS bookmarks (
    user_id    TEXT NOT NULL,
    doc_id     TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (user_id, doc_id),
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_user ON bookmarks(user_id);
```

Migrations live in `db.init_db()` alongside existing `_add_column_if_missing` and `CREATE TABLE IF NOT EXISTS` calls. Idempotent on re-run.

Rationale:

- **Bookmarks as a separate table, not a `grants` row.** Grants convey author-initiated permission; bookmarks are viewer-initiated references. Keeping them separate prevents the grant model from being silently overloaded and keeps dashboard queries explicit.
- **`ON DELETE CASCADE` on bookmarks.** If the doc is gone there's nothing to bookmark; the dangling row has no use.
- **`ON DELETE SET NULL` on `forked_from_doc_id`.** A fork should survive origin deletion. It just loses its attribution line.

## Routes

| Method | Path | Auth | Behavior |
|---|---|---|---|
| `POST` | `/d/{share_token}/fork` | User OR anonymous | Logged-in non-owner → create copy, 302 to new `/d/{new_token}`. Owner → 400. Anonymous → stash intent cookie, 302 to `/login?next=/resume`. Private doc → 403. |
| `POST` | `/d/{share_token}/bookmark` | User OR anonymous | Logged-in → upsert `bookmarks` row (idempotent), 200 `{bookmarked: true}`. Anonymous → stash intent, 302 to `/login?next=/resume`. |
| `DELETE` | `/d/{share_token}/bookmark` | User | Remove row, 200 `{bookmarked: false}`. Anonymous → 401. |
| `GET` | `/resume` | User (must be logged in) | Read + clear intent cookie; dispatch to the relevant service call; 302 to the result URL. Missing/expired cookie → flash "session expired" and 302 to dashboard. |

Rate limits: fork/bookmark use the existing `rate_limit_middleware` user bucket (60/min) — no new limits needed.

## Pending-intent cookie

- **Name:** `markland_pending_intent`
- **Attributes:** `HttpOnly`, `Secure` (prod), `SameSite=Lax`, path `/`, 30-minute TTL.
- **Payload:** signed via `session_secret` (reuse the existing signer used by the auth cookie), JSON `{action: "fork" | "bookmark", share_token: str, exp: int}`.
- **Set at:** the `/fork` or `/bookmark` POST handlers when the request has no user principal.
- **Consumed by:** `/resume`. After successful magic-link callback, the auth-landing handler in `auth_routes.py` checks for this cookie and, if present, 302s to `/resume` instead of `/dashboard`.

## UI — `_save_dialog.html`

Included from `document.html` only when `not is_owner`. The existing `is_owner` branch (currently just `_share_dialog.html` at `document.html:218`) gets a sibling `{% else %}` block.

**Desktop (≥641px):**

- Small button in the existing `.meta` row, right of the "Published" date: `Save to Markland ▾`.
- Click toggles a `role="menu"` popover anchored below with:
  - `Save a copy` (submits the fork form)
  - `Add to library` (submits the bookmark form)
- Closes on outside click or `Escape`.

**Mobile (≤640px):**

- `position: fixed; inset-inline: 0; bottom: 0;` bar with one full-width button: `Save to Markland`.
- Tap opens a bottom sheet (`position: fixed; bottom: 0; transform: translateY(0)` with a slide transition from `translateY(100%)`); the sheet contains the same two options plus a Cancel button.
- Safe-area-inset aware (`padding-bottom: max(1rem, env(safe-area-inset-bottom))`).
- Backdrop click / swipe-down closes.

**Progressive enhancement:** both options are real `<form method="post" action="…">` elements. JS only toggles the popover/sheet visibility. If JS fails, the buttons still submit (the popover just doesn't open; the page shows two inline forms).

## Fork attribution

Renderer: in `view_document()` (`src/markland/web/app.py:291`), when `doc.forked_from_doc_id` is non-null, resolve the parent with a single `get_document()` call. Pass `forked_from` to the template.

Template (below "Published …" in the `.meta` row):

```jinja
{% if forked_from %}
  <span class="forked-from">
    Forked from
    {% if forked_from_visible %}
      <a href="/d/{{ forked_from.share_token }}">{{ forked_from.title }}</a>
    {% else %}
      {{ forked_from.title }}
    {% endif %}
  </span>
{% endif %}
```

`forked_from_visible` is computed at render time by the existing permissions layer — if the viewer can't access the parent (private + no grant), the title renders as text, no link. No PII leak: the title already lives on the fork.

## Error and edge cases

| Case | Behavior |
|---|---|
| Fork a private doc via stale link | Service re-checks visibility + grants at fork time (not at button render time). 403 on failure. |
| Fork own doc | Button hidden when `is_owner`; service also rejects with 400 if posted directly. |
| Bookmark already exists | Primary key makes insert idempotent. Response 200 `{bookmarked: true}`. |
| Bookmark a private doc via stale link | Same as fork: re-check at action time, 403 on failure. |
| Forked-from origin deleted | `ON DELETE SET NULL` clears the pointer; attribution line hides. |
| Forked-from origin made private after fork | Attribution renders title as plain text (no link). |
| Pending-intent cookie expires before login | `/resume` flashes "Login session expired — click Save again" and 302s to the original doc (read from the payload's `share_token`, or dashboard if payload is unreadable). |
| Magic link opened in a different browser than the original click | No cookie present → `/resume` falls through to `/dashboard` with a generic flash. |
| Anonymous DELETE /bookmark | 401 (nothing to delete without a user). |

## Service layer

`src/markland/service/save.py`:

```python
def fork_document(conn, source: Document, new_owner_id: str) -> Document:
    """Copy `source` into a new doc owned by `new_owner_id`. Seeds revision 1.
    Raises PermissionError if source is not viewable by the new owner.
    Raises ValueError if new_owner_id is the source owner."""

def toggle_bookmark(conn, user_id: str, doc_id: str, bookmarked: bool) -> None:
    """Insert or remove a bookmark row. Idempotent."""
```

`fork_document` copies: `title`, `content`, `is_public=False` (forks default to private — user can promote), new `share_token`, new `id`, `forked_from_doc_id=source.id`, and inserts a revision-1 row via the existing `insert_revision`.

## Dashboard

Forked docs appear in the normal "Your docs" list automatically (same as any user-owned doc) — no dashboard change needed for forking.

Bookmarks need a surface or the "Add to library" action is silently dead. Add a **Saved** section on `/dashboard` below the existing owner/shared lists:

- New query in `db.py`: `list_bookmarks_for_user(conn, user_id) -> list[Document]` — joins `bookmarks` → `documents`, filters to docs the user can still view (public, or with a live grant), returns docs ordered by `bookmarks.created_at DESC`.
- Dashboard route (`src/markland/web/dashboard.py`) passes `bookmarks` into the template.
- Template renders each row with title, excerpt (reuse `make_excerpt`), owner, and a small **Remove** button that posts to `DELETE /d/{share_token}/bookmark` (form + hidden `_method=DELETE`, or a small JS fetch — pick whichever matches existing dashboard patterns).
- Docs whose visibility has changed such that the bookmarker can no longer view them are filtered out of the query (not shown as dead rows).

## Test plan

TDD order:

1. **`tests/test_renderer_mobile.py`** — rendering a table produces HTML wrapped in `<div class="table-scroll">`.
2. **`tests/test_db_migrations.py`** — pre-migration DB gains the `forked_from_doc_id` column and `bookmarks` table after `init_db()`; re-running `init_db()` is a no-op.
3. **`tests/test_service_save.py`**
   - `fork_document()` creates a new doc with a new share_token, new owner, `forked_from_doc_id` set to the source, title and content copied, `is_public=False`, revision 1 inserted.
   - `fork_document()` raises `PermissionError` when the source is private and the caller has no grant.
   - `fork_document()` raises `ValueError` when caller is the source owner.
   - `toggle_bookmark(..., bookmarked=True)` twice produces one row.
   - `toggle_bookmark(..., bookmarked=False)` on a missing row is a no-op.
4. **`tests/test_save_routes.py`** (FastAPI TestClient)
   - Anonymous `POST /d/{token}/fork` → 302 to `/login?next=/resume`, `markland_pending_intent` cookie set.
   - `GET /resume` with valid cookie + logged-in session → fork created, 302 to new `/d/{new_token}`, cookie cleared.
   - `GET /resume` with expired cookie → 302 to original doc with flash.
   - Logged-in non-owner `POST /fork` → 302 to new doc.
   - Owner `POST /fork` → 400.
   - Private-doc `POST /fork` from unauthorized user → 403.
   - `POST /bookmark` twice → both 200, single DB row.
   - `DELETE /bookmark` → 200, row gone.
   - Anonymous `DELETE /bookmark` → 401.
5. **`tests/test_dashboard_bookmarks.py`** — logged-in user with two bookmarks sees a "Saved" section containing both docs, ordered newest-first. Bookmark of a doc whose visibility has changed to private (and no grant) is filtered out. Remove button DELETEs and the row disappears on reload.
6. **`tests/test_document_view.py`**
   - Doc with `forked_from_doc_id` pointing to a viewable parent → response contains `Forked from <a>…</a>`.
   - Doc with `forked_from_doc_id` pointing to a private parent → response contains the title text without `<a>`.
   - Doc with no `forked_from_doc_id` → no "Forked from" line.
7. **Mobile verification (manual + Playwright)** — after code is in, re-run the stress-test doc at 375×667:
   - `document.documentElement.scrollWidth <= window.innerWidth`.
   - `.table-scroll` wrapper exhibits `scrollWidth > clientWidth`.
   - Full-page screenshot shows all table columns reachable, no text overflow.

## Rollout

No feature flag. Ship as a single PR. Migration is additive and idempotent. If the `/resume` flow needs tuning post-launch, it can be iterated in place — there's no data contract to break.
