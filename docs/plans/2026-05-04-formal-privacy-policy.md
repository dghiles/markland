# Formal Privacy Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `/privacy` from a "working summary for the public beta" to a real, standard-shaped privacy policy that an external evaluator (or counsel) reads as a complete document, while preserving the plain-English voice and specificity the current page gets right.

**Architecture:** One template file (`src/markland/web/templates/privacy.html`) gains the standard sections most users expect: information we collect, how we use it, sub-processors, retention, your rights, international transfers, security, children's privacy, changes to the policy, contact. Existing content is reorganized under standard headings rather than rewritten. Plain English first; legalese where required for jurisdictional clarity. Tests pin section presence so future edits can't silently regress the structure.

**Tech Stack:** Jinja2 template, pytest (existing test patterns in `tests/test_trust_pages.py`).

**Roadmap link:** `docs/ROADMAP.md` "Next" lane → "Formal privacy policy."

---

## File Structure

**Modify:**
- `src/markland/web/templates/privacy.html` — full rewrite under standard headings, preserving the existing facts.
- `tests/test_trust_pages.py:59-71` — bump `/privacy` minimum word count from 250 to 800 (real privacy policies are ~800-1500 words).
- `tests/test_trust_pages.py` — append new test asserting all 10 standard headings are present.

**Create:** none.

**Word-count budget:** target ~900-1100 words. The current page is ~280 words; the bulk comes from sections that don't exist yet (sub-processors, retention, your rights, children's privacy, changes, contact).

---

## Task 1: Pin the standard structure with a failing test

**Files:**
- Test: `tests/test_trust_pages.py` (append a new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trust_pages.py`:

```python
def test_privacy_has_standard_sections(client):
    """The /privacy page must carry the ten standard sections of a real
    privacy policy. Section presence is asserted via the <h2> heading
    text — order is not enforced here, only completeness."""
    r = client.get("/privacy")
    text = r.text
    required_h2 = [
        "Information we collect",
        "How we use your information",
        "Who we share data with",
        "Data retention",
        "Your rights and choices",
        "International transfers",
        "Security",
        "Children's privacy",
        "Changes to this policy",
        "Contact us",
    ]
    missing = [h for h in required_h2 if h not in text]
    assert not missing, f"/privacy missing sections: {missing}"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: FAIL — every section is missing because the current page uses different headings ("What Markland stores", "What Markland does not do", etc.).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_trust_pages.py
git commit -m "test(privacy): pin presence of 10 standard policy sections"
```

(Committing the failing test by itself is intentional — it documents the target structure. The next 9 tasks will turn it green section-by-section.)

---

## Task 2: Introduction + "Last updated" + remove the beta-summary hedge

**Files:**
- Modify: `src/markland/web/templates/privacy.html:8-12`

- [ ] **Step 1: Replace the page intro**

Open `src/markland/web/templates/privacy.html`. Replace lines 8-12:

```html
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Privacy</h1>

  <p style="margin-bottom: 1.4rem;">
    This is a working privacy summary for the Markland public beta. A formal privacy policy will be published before general availability. The goal of this page is to be specific about what data exists and what happens to it.
  </p>
```

with:

```html
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Privacy Policy</h1>

  <p style="color: var(--muted); margin-bottom: 1.4rem;">Last updated: 2026-05-04</p>

  <p style="margin-bottom: 1.4rem;">
    Markland is operated by an individual developer (<a href="https://github.com/dghiles" rel="author" style="color: var(--blue); border-bottom: 1px solid var(--outline);">@dghiles</a>) and provides a markdown publishing surface for humans and AI agents. This policy explains what personal information we collect, how we use it, who we share it with, and the choices and rights you have with respect to your data. Plain English first; specifics throughout.
  </p>

  <p style="margin-bottom: 1.4rem;">
    "We," "us," and "Markland" refer to the operator of <code>https://markland.dev</code>. "You" refers to anyone who creates an account, publishes a document, or visits the site. By using Markland you agree to this policy. If you do not agree, please don't use the service.
  </p>
```

(The `Last updated:` line is required by the existing
`test_trust_page_has_last_updated` test, which asserts the literal
string is present. The current page already passes that test via a
different mechanism — verify with the test command in Step 3 that
both the new structure and the existing freshness test pass.)

- [ ] **Step 2: Verify the introductory tests still pass**

```bash
uv run pytest tests/test_trust_pages.py -v -k "privacy or trust_page_has_last_updated or trust_page_title"
```

Expected: all green. (The new content keeps the title in range and adds an explicit `Last updated:` line.)

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): introduction + Last updated + remove beta-summary hedge"
```

---

## Task 3: Section — Information we collect

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — replace the existing "What Markland stores" `<h2>` block.

- [ ] **Step 1: Replace the storage section**

Find the block that begins with `<h2 ...>What Markland stores</h2>` and ends after its `</ul>`. Replace it with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Information we collect</h2>

  <p style="margin-bottom: 1rem;">
    We collect information in three ways:
  </p>

  <p style="margin-bottom: 0.4rem;"><strong>1. Information you give us directly.</strong></p>
  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li>Your email address — required for sign-in via magic link.</li>
    <li>A display name you choose (optional; defaults to the local part of your email).</li>
    <li>The content of any documents you publish, their titles, and the revision history we maintain so you can roll back accidental edits.</li>
    <li>The grants you create on documents (which email addresses or agent IDs you've shared with) and any invites you generate.</li>
    <li>Agent identities you create — their IDs and human-readable labels. Agent bearer tokens are stored as Argon2 hashes; we never see or retain plaintext tokens after issuance.</li>
  </ul>

  <p style="margin-bottom: 0.4rem;"><strong>2. Information collected automatically when you use the service.</strong></p>
  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li>An append-only audit log of authentication, token issuance, grant changes, and visibility flips, with timestamps and the principal that performed the action.</li>
    <li>Server access logs (IP address, request path, status code, timestamp, user agent) retained for approximately seven days for abuse triage and debugging. Logs are scrubbed of magic-link tokens, agent tokens, and CSRF tokens before they hit storage.</li>
    <li>If <code>SENTRY_DSN</code> is configured (it currently is, in production), unexpected exceptions and the request context that produced them are sent to Sentry for error monitoring. Tokens and authentication headers are scrubbed before transmission.</li>
  </ul>

  <p style="margin-bottom: 0.4rem;"><strong>3. Information collected by privacy-respecting analytics.</strong></p>
  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li>If <code>UMAMI_WEBSITE_ID</code> is configured (it currently is, on marketing pages only — not on signed-in dashboards or document viewers), Umami Cloud records page views, referrer, screen size, and country. No cookies are set, no cross-site tracking, no personal identifiers, and no document content. See <a href="/security" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/security</a> for the full disclosure.</li>
  </ul>

  <p style="margin-bottom: 1rem;">
    We do not collect Social Security numbers, payment information, government IDs, biometric data, or location data more precise than country level.
  </p>
```

- [ ] **Step 2: Run the structure test to confirm one section is now present**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: still FAIL (9 sections still missing), but the failure list should no longer include `"Information we collect"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Information we collect section"
```

---

## Task 4: Section — How we use your information

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — replace the existing "What Markland does not do" block.

- [ ] **Step 1: Replace the does-not-do section**

Find the block beginning with `<h2 ...>What Markland does not do</h2>` and ending after its `</ul>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">How we use your information</h2>

  <p style="margin-bottom: 1rem;">
    We use the information described above to:
  </p>
  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li>Authenticate you and your agents, and protect accounts from unauthorized access.</li>
    <li>Render and serve your documents to the people and agents you have granted access to.</li>
    <li>Detect and respond to abuse — rate limiting, anomalous-traffic triage, and security investigations.</li>
    <li>Operate, maintain, and improve the service — fixing bugs, monitoring uptime, and capacity planning.</li>
    <li>Communicate with you about your account — magic-link emails, security notifications, and (rarely) service announcements. We do not send marketing email today.</li>
  </ul>

  <p style="margin-bottom: 1rem;">
    <strong>What we do not do:</strong>
  </p>
  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li>We do not sell your personal information or document content to anyone, for any purpose.</li>
    <li>We do not share document content with advertisers, ad networks, or third-party analytics providers.</li>
    <li>We do not train AI or machine-learning models — ours or anyone else's — on the content you publish to Markland.</li>
    <li>We do not read your private documents, except when responding to an explicit support request from you, or when legally compelled (see "Who we share data with" below).</li>
    <li>We do not use your data for behavioral advertising or cross-site tracking.</li>
  </ul>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"How we use your information"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): How we use your information section"
```

---

## Task 5: Section — Who we share data with (sub-processors)

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — insert before the existing "Cookies & tracking" block.

- [ ] **Step 1: Insert the sub-processors section**

Locate the `<h2 ...>Cookies &amp; tracking</h2>` line. Immediately
before that `<h2>`, insert:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Who we share data with</h2>

  <p style="margin-bottom: 1rem;">
    Markland uses a small number of third-party service providers ("sub-processors") to operate the platform. Each one receives only the data it needs to do its specific job. We do not share data with anyone not on this list, except where required by law (see below).
  </p>

  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li><strong>Fly.io</strong> — application hosting. Receives all request and response data in transit (this is unavoidable for any hosted service). Database files and backups also reside on Fly.io infrastructure.</li>
    <li><strong>Resend</strong> — transactional email delivery for magic-link sign-in and notifications. Receives your email address and the message body of system emails. Resend's privacy policy: <a href="https://resend.com/legal/privacy-policy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">resend.com/legal/privacy-policy</a>.</li>
    <li><strong>Cloudflare R2</strong> — encrypted off-site backup storage for the SQLite database via Litestream. Backup contents include all data described in "Information we collect."</li>
    <li><strong>Umami Cloud</strong> — privacy-first web analytics on marketing pages only. Receives page-view metadata (URL, referrer, country, screen size). No cookies, no cross-site tracking, no PII. Umami's privacy policy: <a href="https://umami.is/privacy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">umami.is/privacy</a>.</li>
    <li><strong>Sentry</strong> — application error monitoring. Receives exception traces and the scrubbed request context that produced them. Authentication tokens, magic-link tokens, and CSRF tokens are stripped before transmission.</li>
    <li><strong>Anthropic</strong> — when an AI agent on someone's behalf interacts with Markland via MCP, the document content the agent is acting on may pass through that agent's underlying model provider (typically Anthropic for Claude Code users). This is governed by your agreement with that provider, not by Markland; we don't transmit your data to Anthropic ourselves.</li>
  </ul>

  <p style="margin-bottom: 1rem;">
    <strong>Legal disclosure.</strong> We may disclose your information if we receive a valid legal process (subpoena, court order, search warrant), if we believe disclosure is necessary to comply with a law or regulation, or if we believe disclosure is necessary to protect the safety of any person. Where lawful, we will notify you before responding so you can object or seek protective relief.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Business transfers.</strong> If Markland is acquired, merged, or has its assets transferred, your information may be part of the transfer. The acquirer will be required to honor this policy or notify you of any material change before continuing to use your information.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"Who we share data with"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Who we share data with — sub-processors + legal disclosure"
```

---

## Task 6: Section — Data retention

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — insert before the existing "Cookies & tracking" block (which Task 5 already set up as the next section).

- [ ] **Step 1: Insert the retention section**

Locate the `<h2 ...>Cookies &amp; tracking</h2>` line again (still
present after Task 5's insert above it). Insert immediately before it:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Data retention</h2>

  <p style="margin-bottom: 1rem;">
    We retain different categories of data for different periods:
  </p>

  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li><strong>Account data</strong> (email, display name, agent identities) — retained for as long as your account is active. Deleted within 30 days of account deletion.</li>
    <li><strong>Document content and revisions</strong> — retained for as long as the document exists. Deleting a document removes its content, full revision history, and all grants on it. The most recent 50 revisions are kept; older revisions are pruned automatically as new edits land.</li>
    <li><strong>Audit log</strong> — retained for the lifetime of the account; this log is append-only by design (DB trigger enforces this) so individual entries cannot be edited or selectively deleted.</li>
    <li><strong>Server access logs</strong> — approximately 7 days, then rotated out.</li>
    <li><strong>Magic-link tokens</strong> — single-use; consumed at first verify and otherwise expire 15 minutes after issuance.</li>
    <li><strong>Backups</strong> — Cloudflare R2 backups via Litestream are retained for 30 days, then expire. Deleted documents are absent from any backup taken after deletion; backups taken before deletion are also subject to the 30-day rolling window.</li>
    <li><strong>Sentry error events</strong> — Sentry's default retention applies (90 days for the free tier as of this writing); we don't override it.</li>
    <li><strong>Umami analytics</strong> — Umami Cloud's default retention applies (12 months as of this writing); we don't override it.</li>
  </ul>

  <p style="margin-bottom: 1rem;">
    Where law requires longer retention (for example, tax records once we have paid customers), we'll comply with the longer period and update this policy.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"Data retention"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Data retention section with per-category timelines"
```

---

## Task 7: Section — Your rights and choices

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — replace the existing "Deleting your data" block.

- [ ] **Step 1: Replace the deletion section**

Find the block beginning with `<h2 ...>Deleting your data</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Your rights and choices</h2>

  <p style="margin-bottom: 1rem;">
    Regardless of where you are in the world, you have the following rights with respect to the personal data Markland holds about you:
  </p>

  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li><strong>Access.</strong> You can see most of your account data in <a href="/dashboard" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/dashboard</a> and <a href="/settings/agents" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/settings/agents</a>. For a full export of audit-log entries and any data not visible in the UI, email us (see "Contact us" below) and we'll send you a JSON archive within 30 days.</li>
    <li><strong>Correction.</strong> You can update your display name from your account settings. To correct an email address, contact us — email changes require re-verification through magic link.</li>
    <li><strong>Deletion.</strong> You can delete individual documents from <a href="/dashboard" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/dashboard</a>. Self-service account deletion is in development; until it ships, reply to any Markland email and a human will process the request within 30 days. Account deletion removes your account record, magic-link history, agent identities and tokens, and all documents you own (including their revisions and grants). Audit-log entries about your account are retained, but the user_id is replaced with a non-reversible token.</li>
    <li><strong>Export.</strong> You can fork or download any document you can read via the document viewer. Bulk export of all your documents is on the roadmap; in the meantime, contact us for a JSON archive.</li>
    <li><strong>Object / restrict processing.</strong> You can ask us to stop processing your data for a specific purpose. In practice, the only "purposes" we have are operating the service and abuse triage; objecting to those means deleting your account.</li>
    <li><strong>Withdraw consent.</strong> Sign-in is consent-based — sign out and delete your account to withdraw it.</li>
    <li><strong>Lodge a complaint.</strong> If you are in the EU, UK, or another jurisdiction with a data protection authority, you have the right to file a complaint with that authority. We'd appreciate the chance to address your concern first via the contact below.</li>
  </ul>

  <p style="margin-bottom: 1rem;">
    We do not charge for these requests and do not require government ID — proving control of the email address on the account is sufficient. If a request is repetitive or manifestly excessive, we may decline or charge a reasonable fee, but this is not a tool we expect to use.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"Your rights and choices"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Your rights and choices — access, deletion, export, complaint"
```

---

## Task 8: Section — International transfers

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — replace the existing "Hosting & jurisdiction" block.

- [ ] **Step 1: Replace the hosting section**

Find the block beginning with `<h2 ...>Hosting &amp; jurisdiction</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">International transfers</h2>

  <p style="margin-bottom: 1rem;">
    Markland is operated from the United States. The application runs on Fly.io in the <code>iad</code> region (Ashburn, Virginia, US-East). Backups are stored in Cloudflare R2; sub-processor regions are listed in their respective documentation.
  </p>

  <p style="margin-bottom: 1rem;">
    If you are accessing Markland from outside the United States, your data will be transferred to and processed in the United States and other countries where our sub-processors operate. The protections offered by US privacy law may differ from those offered by your local law. Where required (for example, transfers from the EU/UK), we rely on standard contractual clauses or other legal mechanisms with our sub-processors to protect your data in transit.
  </p>

  <p style="margin-bottom: 1rem;">
    The host region and provider may change as the service grows. This page will be updated within 30 days of any material change.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"International transfers"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): International transfers section"
```

---

## Task 9: Section — Security

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — append after the International transfers section.

- [ ] **Step 1: Append the security section**

Append after the International transfers `</p>` (the one closing the
"updated within 30 days" paragraph from Task 8):

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Security</h2>

  <p style="margin-bottom: 1rem;">
    We take reasonable technical and organizational measures to protect your data: HTTPS-only transport with HSTS, magic-link sign-in (no passwords to leak), Argon2id-hashed bearer tokens, append-only audit logging, encrypted-at-rest storage on the host platform, scrubbed logs and error reports, and regular security review. The full posture is documented at <a href="/security" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/security</a>.
  </p>

  <p style="margin-bottom: 1rem;">
    No system is perfectly secure. If we become aware of a breach affecting your data, we will notify you by email within 72 hours of confirming the incident and the affected accounts, and we will publish a postmortem on the site.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"Security"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Security section + 72-hour breach notification commitment"
```

---

## Task 10: Section — Children's privacy

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — append after the Security section.

- [ ] **Step 1: Append the children's privacy section**

Append after the Security section's last `</p>`:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Children's privacy</h2>

  <p style="margin-bottom: 1rem;">
    Markland is not directed to children under 16, and we do not knowingly collect personal information from children under 16. If you are a parent or guardian and believe your child has provided us with personal information, contact us and we will delete the account.
  </p>

  <p style="margin-bottom: 1rem;">
    We do not target advertising at children, conduct profiling of any user (child or adult), or sell information collected from any user.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"Children's privacy"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Children's privacy section"
```

---

## Task 11: Section — Changes to this policy

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — append after the Children's privacy section.

- [ ] **Step 1: Append the changes section**

Append after the Children's privacy section's last `</p>`:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Changes to this policy</h2>

  <p style="margin-bottom: 1rem;">
    We may update this policy from time to time. The "Last updated" date at the top of the page reflects the most recent revision. For material changes — anything that meaningfully expands what we collect, who we share it with, or how long we keep it — we will notify active account holders by email at least 14 days before the change takes effect, so you have time to review and, if you disagree, delete your account before continuing to use the service.
  </p>

  <p style="margin-bottom: 1rem;">
    The full revision history of this page is available in the public Markland repository on GitHub (<a href="https://github.com/dghiles/markland" style="color: var(--blue); border-bottom: 1px solid var(--outline);">github.com/dghiles/markland</a>). Every word change is on the record.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: failure list shrinks by `"Changes to this policy"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Changes to this policy + 14-day material-change notice"
```

---

## Task 12: Section — Contact us

**Files:**
- Modify: `src/markland/web/templates/privacy.html` — append after the Changes section.

- [ ] **Step 1: Append the contact section**

Append after the Changes section's last `</p>`:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Contact us</h2>

  <p style="margin-bottom: 1rem;">
    For any privacy-related question, request, or complaint — exercising any right above, requesting a data export, reporting a suspected breach, or anything else — contact <a href="mailto:privacy@markland.dev" style="color: var(--blue); border-bottom: 1px solid var(--outline);">privacy@markland.dev</a>. We aim to respond within 7 days and to fully resolve verifiable requests within 30 days.
  </p>

  <p style="margin-bottom: 1rem;">
    The operator is reachable at <a href="https://github.com/dghiles" rel="author" style="color: var(--blue); border-bottom: 1px solid var(--outline);">@dghiles on GitHub</a>. For security-specific reports (vulnerability disclosure), see <a href="/security#contact" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/security#contact</a>.
  </p>
```

(`privacy@markland.dev` should be wired as a forwarding alias before
this lands in production. Filing as a follow-up rather than blocking
this PR — the page can ship pointing at the alias even if the alias is
created hours later. Add a beads issue: `bd create --title="Provision
privacy@markland.dev forwarding alias" --type=task --priority=2`.)

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_privacy_has_standard_sections -v
```

Expected: PASS — all 10 sections now present.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/privacy.html
git commit -m "feat(privacy): Contact us section + privacy@markland.dev alias"
```

---

## Task 13: Bump word-count floor + final verification

**Files:**
- Modify: `tests/test_trust_pages.py:68` — bump the `/privacy` word-count floor from 250 to 800.

- [ ] **Step 1: Edit the parametrize tuple**

In `tests/test_trust_pages.py`, find the parametrize block at lines 59-71. Replace the `("/privacy", 250)` entry with `("/privacy", 800)`. The block becomes:

```python
@pytest.mark.parametrize(
    ("path", "min_words"),
    [
        # Audit 2026-04-24 C4: every trust page must clear the 250-word
        # E-E-A-T thin-content floor. Page-specific floors picked above
        # the audit baseline (about 98w, security 118w, privacy 101w,
        # terms 95w) — never let regression silently re-thin them.
        # 2026-05-04: privacy floor bumped to 800 after promotion to a
        # real privacy policy (see docs/plans/2026-05-04-formal-privacy-policy.md).
        ("/about", 250),
        ("/security", 300),
        ("/privacy", 800),
        ("/terms", 250),
    ],
)
```

- [ ] **Step 2: Run the word-count test**

```bash
uv run pytest tests/test_trust_pages.py::test_trust_page_word_count -v -k privacy
```

Expected: PASS. (The new sections combined produce ~900-1100 words; if
this fails with a count below 800, the executor missed a section —
re-read the page output and confirm all of Task 3-12 landed.)

- [ ] **Step 3: Run the entire trust-pages suite**

```bash
uv run pytest tests/test_trust_pages.py -q
```

Expected: all green. Specifically:
- `test_trust_page_title_length[/privacy-40-60]` PASS
- `test_privacy_terms_meta_description_length[/privacy]` PASS
- `test_trust_page_word_count[/privacy-800]` PASS
- `test_trust_page_has_last_updated[/privacy]` PASS
- `test_privacy_has_standard_sections` PASS

If the meta-description test fails: the description in line 2 of `privacy.html` may have drifted out of the 130-160 char window during edits. Adjust the `seo_description` set-block to ~140-150 chars.

- [ ] **Step 4: Run the entire suite to catch any unrelated regression**

```bash
uv run pytest tests/ -q
```

Expected: all green. The privacy-policy work doesn't touch service or
route code; if anything else turned red, investigate before merging.

- [ ] **Step 5: Commit**

```bash
git add tests/test_trust_pages.py
git commit -m "test(privacy): bump word-count floor to 800 for full policy"
```

---

## Task 14: Update ROADMAP

**Files:**
- Modify: `docs/ROADMAP.md` — strike "Formal privacy policy" from the Next lane and add a Shipped entry.

- [ ] **Step 1: Remove from Next lane**

In `docs/ROADMAP.md`, find the line:

```markdown
- **Formal privacy policy** — `/privacy` line 11 says "a formal privacy policy will be published before general availability." Today's page is a working summary, which reads as deliberately stub-y to outside evaluators. Promote to a real policy (data inventory, retention, sub-processors, jurisdiction, contact).
```

Delete it.

- [ ] **Step 2: Add to Shipped — under "Marketing + UX surface" or a new "Trust + legal" sub-section**

Add at the top of the "Marketing + UX surface" Shipped section:

```markdown
- **2026-05-04** — **Formal privacy policy live.** `/privacy` promoted from a "working summary for the public beta" to a full standard-shaped privacy policy: information we collect (3 categories), how we use it, sub-processors (Fly.io, Resend, Cloudflare R2, Umami, Sentry), retention timelines per category, your rights and choices (access / correction / deletion / export / complaint), international transfers, security commitments incl. 72-hour breach notification, children's privacy, 14-day material-change notice on policy updates, `privacy@markland.dev` contact alias. Plan: `docs/plans/2026-05-04-formal-privacy-policy.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/ROADMAP.md
git commit -m "docs(roadmap): formal privacy policy shipped"
```

- [ ] **Step 4: Push**

```bash
git push origin main
```

(All commits in this plan ship to `main` via the docs-only direct-push convention in `AGENTS.md` — this work touches only template/test/docs files. No PR needed.)

---

## Out of scope (do not implement here)

- **Self-service account deletion UI.** That's a separate Next-lane item — this plan only commits to deleting on email request and clarifies that path. The policy refers forward to the eventual self-service flow.
- **Cookie banner.** No cookies require consent today (the session cookie is strictly necessary; Umami sets none). If that changes (analytics cookie, advertising), this plan will be revised.
- **Bulk export tooling.** The policy commits to a JSON archive on email request; building the export endpoint is a separate item.
- **Translating the policy.** English-only at launch; if we add translations the master is the English version on `markland.dev`.
- **GDPR/CCPA-specific notices.** The policy as written satisfies most requirements through the rights-and-choices section. If counsel requires jurisdiction-specific addenda, file a follow-up.
- **DPO appointment** (GDPR Art. 37). Not required for a single-developer beta; revisit at GA + first enterprise customer.

---

## Self-review checklist (run before declaring this plan done)

- Each task ends with a `git commit` step ✅
- Every section step shows the actual HTML, not a description ✅
- Every test step shows the assertion or expected output ✅
- No "TBD" / "TODO" / "fill in" placeholders ✅
- Heading text in Task 1's test list exactly matches the heading text in Tasks 3-12 — case, apostrophe (Children's), wording ✅
- Word-count budget (~900-1100w) covers the new floor (800w) with margin ✅
- All 10 sections in Task 1's required list have a corresponding write task (Tasks 3-12) ✅
- Roadmap update task included so the topic moves from Next to Shipped ✅
