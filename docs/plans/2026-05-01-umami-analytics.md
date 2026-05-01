# Umami Cloud Analytics Drop-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Umami Cloud (privacy-first, cookieless, free up to 10k pageviews/month) into Markland so we can see pageviews, unique visitors, top pages, and referrers — without a GDPR cookie banner and without compromising the privacy posture published on `/security`.

**Architecture:** One conditional `<script>` tag in `base.html`, gated by an env-driven `UMAMI_WEBSITE_ID` (and optional `UMAMI_SCRIPT_URL` so self-host migration is one config change). The script only renders when the env var is set, so dev / test / first-deploy stay quiet. Admin/MCP traffic is excluded by `<meta name="umami-domain">` allow-list (only `markland.dev` is tracked) and by leaving `UMAMI_WEBSITE_ID` unset on staging. `/security` page gets a one-line disclosure paragraph.

**Tech Stack:** Umami Cloud (https://cloud.umami.is), FastAPI/Jinja2, existing `Config` dataclass at `src/markland/config.py`.

---

## File Structure

- Modify: `src/markland/config.py` — add `umami_website_id` and `umami_script_url` fields
- Modify: `src/markland/web/templates/base.html` — add conditional script tag in `<head>`
- Modify: `src/markland/web/templates/security.html` — disclose Umami in one line
- Modify: `src/markland/web/app.py` — pass umami config into template context
- Test: `tests/test_umami_analytics.py` — new file with rendering + exclusion tests

---

## Task 1: Add Umami config fields

**Files:**
- Modify: `src/markland/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1.1: Read current config to find the right insertion point**

  ```bash
  grep -n "resend_api_key\|sentry_dsn" src/markland/config.py
  ```

  Expected: lines around 42-44 show the current env-driven fields. Insert Umami fields right after `sentry_dsn`.

- [ ] **Step 1.2: Write failing test**

  Append to `tests/test_config.py`:

  ```python
  def test_config_reads_umami_website_id(monkeypatch):
      monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
      from markland.config import Config
      cfg = Config.from_env()
      assert cfg.umami_website_id == "abcd-1234"


  def test_config_umami_website_id_defaults_empty(monkeypatch):
      monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
      from markland.config import Config
      cfg = Config.from_env()
      assert cfg.umami_website_id == ""


  def test_config_umami_script_url_default(monkeypatch):
      monkeypatch.delenv("UMAMI_SCRIPT_URL", raising=False)
      from markland.config import Config
      cfg = Config.from_env()
      assert cfg.umami_script_url == "https://cloud.umami.is/script.js"
  ```

- [ ] **Step 1.3: Run test to verify failure**

  ```bash
  uv run pytest tests/test_config.py::test_config_reads_umami_website_id tests/test_config.py::test_config_umami_website_id_defaults_empty tests/test_config.py::test_config_umami_script_url_default -v
  ```

  Expected: 3 failures with `AttributeError: 'Config' object has no attribute 'umami_website_id'` (or similar).

- [ ] **Step 1.4: Add fields to Config**

  In `src/markland/config.py`, find the `Config` dataclass / `from_env` factory. Add two new fields:

  ```python
  umami_website_id=os.getenv("UMAMI_WEBSITE_ID", "").strip(),
  umami_script_url=os.getenv("UMAMI_SCRIPT_URL", "https://cloud.umami.is/script.js").strip(),
  ```

  And add corresponding attributes on the `Config` class (mirror the existing pattern used by `sentry_dsn` and `resend_api_key` — both `str` typed, default empty string except `umami_script_url` which defaults to the cloud URL).

- [ ] **Step 1.5: Run test to verify it passes**

  ```bash
  uv run pytest tests/test_config.py::test_config_reads_umami_website_id tests/test_config.py::test_config_umami_website_id_defaults_empty tests/test_config.py::test_config_umami_script_url_default -v
  ```

  Expected: 3 passed.

- [ ] **Step 1.6: Commit**

  ```bash
  git add src/markland/config.py tests/test_config.py
  git commit -m "feat(config): add UMAMI_WEBSITE_ID + UMAMI_SCRIPT_URL"
  ```

---

## Task 2: Render Umami script tag in base template

**Files:**
- Modify: `src/markland/web/app.py` — pass umami config into base template context
- Modify: `src/markland/web/templates/base.html`
- Create: `tests/test_umami_analytics.py`

- [ ] **Step 2.1: Find where base.html context gets globals**

  ```bash
  grep -n "globals\[" src/markland/web/app.py | head -10
  grep -n "templates\.env\.globals" src/markland/web/app.py | head -10
  ```

  Expected: shows the existing globals registration for things like canonical URL, base URL. Umami fields should sit alongside those.

- [ ] **Step 2.2: Write failing tests for rendering**

  Create `tests/test_umami_analytics.py`:

  ```python
  from fastapi.testclient import TestClient

  from markland.web.app import create_app


  def test_landing_renders_umami_script_when_id_set(monkeypatch):
      monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
      client = TestClient(create_app())
      r = client.get("/")
      assert r.status_code == 200
      assert "cloud.umami.is/script.js" in r.text
      assert 'data-website-id="abcd-1234"' in r.text


  def test_landing_omits_umami_script_when_id_unset(monkeypatch):
      monkeypatch.delenv("UMAMI_WEBSITE_ID", raising=False)
      client = TestClient(create_app())
      r = client.get("/")
      assert r.status_code == 200
      assert "cloud.umami.is/script.js" not in r.text
      assert "data-website-id" not in r.text


  def test_admin_pages_omit_umami_script(monkeypatch):
      monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
      client = TestClient(create_app())
      r = client.get("/admin/audit", follow_redirects=False)
      assert "cloud.umami.is/script.js" not in r.text


  def test_custom_script_url_overrides_default(monkeypatch):
      monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
      monkeypatch.setenv("UMAMI_SCRIPT_URL", "https://analytics.markland.dev/script.js")
      client = TestClient(create_app())
      r = client.get("/")
      assert "https://analytics.markland.dev/script.js" in r.text
      assert "cloud.umami.is" not in r.text
  ```

- [ ] **Step 2.3: Run tests to verify they fail**

  ```bash
  uv run pytest tests/test_umami_analytics.py -v
  ```

  Expected: 4 failures — script not in template output yet.

- [ ] **Step 2.4: Wire config into template globals**

  In `src/markland/web/app.py`, find the section where `templates.env.globals[...]` is set (or where `Jinja2Templates` is configured). Add:

  ```python
  templates.env.globals["umami_website_id"] = config.umami_website_id
  templates.env.globals["umami_script_url"] = config.umami_script_url
  ```

  If globals are passed per-request via context-builders instead, mirror the existing pattern (e.g. add to the dict returned by `_base_context(request)` or equivalent).

- [ ] **Step 2.5: Add script tag to base.html**

  Open `src/markland/web/templates/base.html`. Find the closing `</head>` tag. Insert immediately above it:

  ```html
      {% if umami_website_id %}
      <script defer src="{{ umami_script_url }}" data-website-id="{{ umami_website_id }}"></script>
      {% endif %}
  ```

  Use `defer` (not `async`) so the script doesn't block first paint and runs after DOM is parsed — matches Umami's documented best practice.

- [ ] **Step 2.6: Exclude admin pages**

  In `src/markland/web/templates/base.html`, change the conditional to also exclude admin paths:

  ```html
      {% if umami_website_id and not request.url.path.startswith('/admin') %}
      <script defer src="{{ umami_script_url }}" data-website-id="{{ umami_website_id }}"></script>
      {% endif %}
  ```

  This keeps internal admin traffic out of the analytics counts.

- [ ] **Step 2.7: Run tests to verify they pass**

  ```bash
  uv run pytest tests/test_umami_analytics.py -v
  ```

  Expected: 4 passed.

- [ ] **Step 2.8: Run full test suite (regression)**

  ```bash
  uv run pytest tests/ -q
  ```

  Expected: previous baseline + 4 new tests, all passing. Zero failures. Capture count.

- [ ] **Step 2.9: Commit**

  ```bash
  git add src/markland/web/app.py src/markland/web/templates/base.html tests/test_umami_analytics.py
  git commit -m "feat(web): conditional Umami analytics script in base template"
  ```

---

## Task 3: Disclose Umami on /security page

**Files:**
- Modify: `src/markland/web/templates/security.html`
- Test: `tests/test_security_page.py` (or `tests/test_web.py` if security tests live there — check first)

- [ ] **Step 3.1: Locate the security page test file**

  ```bash
  grep -rln "/security\b" tests/ | head -3
  ```

  Expected: probably `tests/test_web.py` or a dedicated `tests/test_security_page.py`. Use whichever exists.

- [ ] **Step 3.2: Write failing test**

  Append to the appropriate test file:

  ```python
  def test_security_page_discloses_umami(monkeypatch):
      monkeypatch.setenv("UMAMI_WEBSITE_ID", "abcd-1234")
      from fastapi.testclient import TestClient
      from markland.web.app import create_app
      client = TestClient(create_app())
      r = client.get("/security")
      assert r.status_code == 200
      assert "Umami" in r.text
      assert "cookie" in r.text.lower()  # confirms the no-cookie note is present
  ```

- [ ] **Step 3.3: Run test to verify failure**

  ```bash
  uv run pytest tests/test_web.py::test_security_page_discloses_umami -v
  ```

  Expected: failure — `assert "Umami" in r.text` fails because page doesn't mention it.

- [ ] **Step 3.4: Add disclosure paragraph to security.html**

  In `src/markland/web/templates/security.html`, find an appropriate section (look for an existing "Logging" or "Privacy" stanza). Add:

  ```html
  <h2>Analytics</h2>
  <p>
    We use <a href="https://umami.is/" rel="noopener">Umami</a> for aggregate
    pageview counts. Umami is privacy-first — it sets no cookies, doesn't
    track individuals across sites, and stores no IP addresses. We use it to
    understand which pages are useful and where readers come from. The script
    is not loaded on admin pages.
  </p>
  ```

- [ ] **Step 3.5: Run test to verify it passes**

  ```bash
  uv run pytest tests/test_web.py::test_security_page_discloses_umami -v
  ```

  Expected: 1 passed.

- [ ] **Step 3.6: Commit**

  ```bash
  git add src/markland/web/templates/security.html tests/test_web.py
  git commit -m "docs(security): disclose Umami analytics, no-cookie posture"
  ```

---

## Task 4: Provision Umami site (OPERATOR ACTION)

**Files:** none — work happens at https://cloud.umami.is.

- [ ] **Step 4.1: Sign up for Umami Cloud**

  Open https://cloud.umami.is. Sign up with `daveyhiles@gmail.com`. Free tier covers 10k pageviews/month, no card required.

- [ ] **Step 4.2: Add a website**

  In the Umami dashboard → "Settings" → "Websites" → "Add Website".
  - Name: `markland`
  - Domain: `markland.dev`

  Save.

- [ ] **Step 4.3: Capture the website ID**

  After save, click "Edit" on the new website row. Copy the `Website ID` (UUID format, e.g. `8c1a2f3d-4567-89ab-cdef-0123456789ab`).

- [ ] **Step 4.4: Set the secret on Fly**

  ```bash
  flyctl secrets set UMAMI_WEBSITE_ID=<paste-the-uuid> -a markland
  ```

  Expected: machine restart triggered. The new secret takes effect after the machine restarts.

- [ ] **Step 4.5: Verify secret is set**

  ```bash
  flyctl secrets list -a markland | grep UMAMI_WEBSITE_ID
  ```

  Expected: line showing `UMAMI_WEBSITE_ID` with a recent `Created at` timestamp (no value shown — Fly hides it).

---

## Task 5: Deploy and verify in production

This step assumes the cutover plan (`docs/plans/2026-04-29-cutover-to-markland-dev.md`) has either been executed or hasn't — both work. If the cutover is done, you're verifying on `https://markland.dev`. If not, verify on `https://markland.fly.dev` with the Umami site domain temporarily set to `markland.fly.dev` instead.

**Files:** none.

- [ ] **Step 5.1: Re-deploy with the launch-group-bug workaround**

  ```bash
  flyctl deploy --build-only -a markland
  IMAGE=$(flyctl image show -a markland --json | jq -r '.image')
  MID=$(flyctl machine list -a markland --json | jq -r '.[] | select(.config.metadata.fly_process_group == "app") | .id' | head -1)
  flyctl machine update "$MID" --image "$IMAGE" -a markland --yes
  ```

  Expected: machine update succeeds, health check passes within 30s.

  (If `--build-only` was already done in a prior step in the same session, just run the `machine update` line with the latest image tag.)

- [ ] **Step 5.2: Verify script tag renders in production**

  ```bash
  curl -s https://markland.dev/ | grep -E "umami|cloud\.umami\.is" | head -3
  ```

  Expected: one line showing the Umami script tag with the configured website ID. If blank, the env var didn't reach the running process — `flyctl ssh console -a markland -C 'env | grep UMAMI'` to confirm.

- [ ] **Step 5.3: Confirm script is absent on /admin pages**

  ```bash
  curl -s -o /tmp/admin-html https://markland.dev/admin/waitlist -H "Authorization: Bearer <admin-token>"
  grep -c "umami" /tmp/admin-html
  ```

  Expected: `0`. (If the route returns JSON not HTML — and `/admin/waitlist` does — the test is moot for that endpoint; substitute `/admin/audit` which returns HTML.)

- [ ] **Step 5.4: Send a test pageview from a real browser (OPERATOR ACTION)**

  Open https://markland.dev/ in a real browser (not curl). Wait 30s.

  In the Umami dashboard, click on the `markland` site. Expected: realtime view shows 1+ visitor in the last minute.

- [ ] **Step 5.5: Capture evidence**

  Screenshot the Umami dashboard showing the test pageview. Save context-free path under `/tmp` or your local notes — not committed to repo. Or just confirm in a follow-up message.

  Pass criteria: realtime counter incremented in Umami dashboard within 60s of the test pageview.

---

## Verification matrix

| Check | Command / Action | Expected |
|---|---|---|
| Config reads env | `uv run pytest tests/test_config.py::test_config_reads_umami_website_id -v` | pass |
| Script renders when set | `uv run pytest tests/test_umami_analytics.py -v` | 4 pass |
| Security page discloses | `uv run pytest tests/test_web.py::test_security_page_discloses_umami -v` | pass |
| Full suite | `uv run pytest tests/ -q` | baseline + 5 new, all pass |
| Production HTML has script | `curl -s https://markland.dev/ \| grep umami` | 1 match |
| Admin pages excluded | `curl -s https://markland.dev/admin/audit -H Auth:... \| grep -c umami` | 0 |
| Realtime view | Umami dashboard | 1+ visitor on test load |

---

## Rollback

If Umami causes any visible issue (e.g. CSP violation, script load failures degrading user experience):

```bash
flyctl secrets unset UMAMI_WEBSITE_ID -a markland
```

Machine restart removes the script tag immediately (template re-renders without it). No code revert required. The Umami site can stay provisioned indefinitely — it's idle when no script reports.

---

## Self-review

**Spec coverage check:**
- Pageview counts → Umami dashboard ✓ (Tasks 4, 5)
- Unique-visitor counts → Umami dashboard ✓ (same — Umami's "Visitors" metric)
- Script in `<head>` → Task 2 ✓
- Privacy-first / no banner → Umami is cookieless; disclosed on `/security` ✓ (Task 3)
- Env-gated (no script in dev/test) → Task 2.7 verifies absence when unset ✓
- Admin traffic excluded → Task 2.6 conditional + Task 5.3 verification ✓
- Self-host migration path → `UMAMI_SCRIPT_URL` env var allows zero-code switch ✓ (Task 1)
- Production verification → Task 5 ✓

**Placeholder scan:** None. The two `<paste-the-uuid>` and `<admin-token>` strings in Task 4 and 5 are explicit operator-substitution placeholders, not plan failures — they require values only the operator has at execution time.

**Type/name consistency:** `umami_website_id` and `umami_script_url` consistent across config (Task 1), template globals (Task 2.4), and template variable use (Task 2.5). Test file `tests/test_umami_analytics.py` referenced consistently in 2.2, 2.7, and the verification matrix.
