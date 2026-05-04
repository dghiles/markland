# Formal Terms of Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `/terms` from a "working terms summary for the public beta" to a real, standard-shaped Terms of Service that an external evaluator (or counsel) reads as a complete agreement, while preserving the plain-English voice and the beta-honest framing the current page gets right.

**Architecture:** One template file (`src/markland/web/templates/terms.html`) gains the standard sections most users and reviewers expect: introduction & acceptance, definitions, account & eligibility, acceptable use, your content & license, our service (beta posture, availability, changes), termination, disclaimers & warranty, limitation of liability, indemnification, governing law & disputes, general (entire agreement, severability, etc.), changes to these terms, contact. Existing content is preserved under standard headings rather than rewritten. Plain English first; necessary legal terms inline. Tests pin section presence so future edits cannot silently regress the structure.

**Tech Stack:** Jinja2 template, pytest (existing test patterns in `tests/test_trust_pages.py`).

**Roadmap link:** `docs/ROADMAP.md` "Next" lane → "Formal Terms of Service."

**Sibling plan:** `docs/plans/2026-05-04-formal-privacy-policy.md` (same shape, same workflow). Land them in either order.

---

## File Structure

**Modify:**
- `src/markland/web/templates/terms.html` — full rewrite under standard headings, preserving the existing facts.
- `tests/test_trust_pages.py:59-71` — bump `/terms` minimum word count from 250 to 900 (real ToS docs typically run 900-1500 words).
- `tests/test_trust_pages.py` — append new test asserting the 14 standard headings are present.

**Create:** none.

**Word-count budget:** target ~1000-1200 words. The current page is ~290 words; the bulk comes from sections that don't exist yet (definitions, account & eligibility, your content & license, indemnification, governing law & disputes, general provisions, changes, contact).

---

## Task 1: Pin the standard structure with a failing test

**Files:**
- Test: `tests/test_trust_pages.py` (append a new test)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trust_pages.py`:

```python
def test_terms_has_standard_sections(client):
    """The /terms page must carry the 14 standard sections of a real
    terms-of-service document. Section presence is asserted via the
    <h2> heading text — order is not enforced here, only completeness."""
    r = client.get("/terms")
    text = r.text
    required_h2 = [
        "Introduction and acceptance",
        "Definitions",
        "Your account",
        "Acceptable use",
        "Your content",
        "Our service",
        "Termination",
        "Disclaimers",
        "Limitation of liability",
        "Indemnification",
        "Governing law and disputes",
        "General",
        "Changes to these terms",
        "Contact",
    ]
    missing = [h for h in required_h2 if h not in text]
    assert not missing, f"/terms missing sections: {missing}"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: FAIL — every section is missing because the current page uses different headings ("Beta-stage software", "What you can publish", etc.).

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_trust_pages.py
git commit -m "test(terms): pin presence of 14 standard ToS sections"
```

(Committing the failing test by itself is intentional — it documents the target structure. The next 13 tasks will turn it green section-by-section.)

---

## Task 2: Introduction and acceptance + "Last updated" + remove the beta-summary hedge

**Files:**
- Modify: `src/markland/web/templates/terms.html:8-12`

- [ ] **Step 1: Replace the page intro**

Open `src/markland/web/templates/terms.html`. Replace lines 8-12:

```html
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Terms of Service</h1>

  <p style="margin-bottom: 1.4rem;">
    This is a working terms summary for the Markland public beta. Formal terms of service will be published before general availability. Plain English first; legalese later.
  </p>
```

with:

```html
  <h1 style="font-family: var(--font-display); font-size: clamp(2rem, 5vw, 3rem); letter-spacing: -0.03em; line-height: 1.05; margin-bottom: 1.5rem; color: var(--text);">Terms of Service</h1>

  <p style="color: var(--muted); margin-bottom: 1.4rem;">Last updated: 2026-05-04</p>

  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Introduction and acceptance</h2>

  <p style="margin-bottom: 1rem;">
    Welcome to Markland. These Terms of Service ("Terms") form a binding agreement between you and the operator of <code>https://markland.dev</code> regarding your use of the Markland service. Read them carefully — they cover what you can and can't do on Markland, what we do and don't promise, and how disputes are handled.
  </p>

  <p style="margin-bottom: 1rem;">
    By creating an account, publishing a document, or otherwise using Markland, you agree to these Terms and to our <a href="/privacy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">Privacy Policy</a>, which is incorporated by reference. If you don't agree, please don't use the service.
  </p>

  <p style="margin-bottom: 1rem;">
    Plain English is the goal. Where legal terms appear, they are there because removing them would create real ambiguity, not for ceremony.
  </p>
```

(The `Last updated:` line is required by the existing
`test_trust_page_has_last_updated` test, which asserts the literal
string is present.)

- [ ] **Step 2: Verify intro-related tests still pass**

```bash
uv run pytest tests/test_trust_pages.py -v -k "terms or trust_page_has_last_updated or trust_page_title"
```

Expected: title length test passes (current title `Terms of Service — Markland Beta` is 32 chars, in the 30-60 range) and the `Last updated:` test passes.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): introduction and acceptance + Last updated"
```

---

## Task 3: Section — Definitions

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Introduction section.

- [ ] **Step 1: Append the definitions section**

Append after the closing `</p>` of the "Plain English is the goal" paragraph (the last paragraph from Task 2):

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Definitions</h2>

  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li><strong>"Markland," "we," "us," "our"</strong> — the operator of <code>https://markland.dev</code>, a single individual developer (<a href="https://github.com/dghiles" rel="author" style="color: var(--blue); border-bottom: 1px solid var(--outline);">@dghiles</a>) operating the service in their personal capacity.</li>
    <li><strong>"You," "your"</strong> — the natural person or legal entity using Markland under an account.</li>
    <li><strong>"Service"</strong> — the Markland website, the MCP server at <code>/mcp</code>, the document-publishing API, and any related software or infrastructure operated by Markland.</li>
    <li><strong>"Account"</strong> — a record created by signing in with a verified email address. Each Account is held by one human user.</li>
    <li><strong>"Agent"</strong> — an automated software actor (typically an AI agent like Claude Code, Cursor, or Codex) that you have authorized to act on your behalf via a Markland-issued bearer token.</li>
    <li><strong>"Content"</strong> — markdown documents, titles, comments, agent labels, and any other material you publish, upload, or otherwise make available through the Service.</li>
    <li><strong>"Public Document"</strong> — Content you have explicitly marked as public; reachable by URL without an Account or grant.</li>
    <li><strong>"Private Document"</strong> — Content readable only by the owner and accounts or agents with a grant.</li>
  </ul>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Definitions"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Definitions section"
```

---

## Task 4: Section — Your account

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Definitions section.

- [ ] **Step 1: Append the account section**

Append after the closing `</ul>` of the Definitions section:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Your account</h2>

  <p style="margin-bottom: 1rem;">
    You must be at least 16 years old to create an Account. By creating one, you confirm you meet this minimum age and that you are entering into these Terms on your own behalf, or with authority to bind any organization on whose behalf you are acting.
  </p>

  <p style="margin-bottom: 1rem;">
    You are responsible for keeping your sign-in email secure and for any activity that occurs under your Account, including activity by Agents you have authorized. Bearer tokens issued to your Agents grant the same authority as your Account, scoped to whatever permission level you assigned. Treat them like passwords; if a token is leaked or an Agent is no longer trusted, revoke the token from <a href="/settings/agents" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/settings/agents</a> immediately.
  </p>

  <p style="margin-bottom: 1rem;">
    You agree to provide accurate sign-in information and to update it as needed. Each Account is for use by one human; sharing sign-in credentials with another human is not permitted (Agents are the supported way to delegate).
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Your account"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Your account section"
```

---

## Task 5: Section — Acceptable use

**Files:**
- Modify: `src/markland/web/templates/terms.html` — replace the existing "What is not allowed" `<h2>` block.

- [ ] **Step 1: Replace the not-allowed section**

Find the block beginning with `<h2 ...>What is not allowed</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Acceptable use</h2>

  <p style="margin-bottom: 1rem;">
    Markland is a publishing surface, not a hosting platform for everything. You agree not to use the Service to:
  </p>

  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li>Publish, store, or transmit illegal content under the laws of the United States or any jurisdiction in which you operate.</li>
    <li>Publish content that infringes the intellectual property rights, privacy rights, or other rights of any third party.</li>
    <li>Distribute malware, phishing payloads, or any code or content designed to harm a recipient's system, account, or data.</li>
    <li>Harass, threaten, defame, or doxx any specific person or group, or coordinate harm against them.</li>
    <li>Engage in spam, mass unsolicited messaging, fraud, market manipulation, or any deceptive scheme.</li>
    <li>Attempt to gain unauthorized access to the Service, other users' Accounts, or the underlying infrastructure (penetration testing requires prior written authorization).</li>
    <li>Interfere with or disrupt the Service — including by submitting requests at a rate, volume, or pattern designed to degrade performance for other users.</li>
    <li>Reverse-engineer, decompile, or attempt to extract the source code of the Service, except to the extent permitted by law.</li>
    <li>Use the Service to train AI or machine-learning models without prior written authorization. This restriction applies whether the model is yours, your employer's, or a third party's.</li>
    <li>Misrepresent your identity, your authority, or the source or accuracy of any Content you publish.</li>
  </ul>

  <p style="margin-bottom: 1rem;">
    We reserve the right to remove Content, suspend tokens, or close Accounts that violate these guidelines. Enforcement is logged in the append-only audit trail described on <a href="/security" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/security</a>. Where law allows, we will notify you of an enforcement action and the reason.
  </p>

  <p style="margin-bottom: 1rem;">
    If you believe Content on Markland infringes your rights or violates these terms, contact us using the address in the "Contact" section below. Provide enough information for us to locate and assess the Content (URL, the right being asserted, your contact information, and a good-faith statement that the Content is unauthorized).
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Acceptable use"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Acceptable use section + reporting path"
```

---

## Task 6: Section — Your content

**Files:**
- Modify: `src/markland/web/templates/terms.html` — replace the existing "What you can publish" `<h2>` block.

- [ ] **Step 1: Replace the publishable-content section**

Find the block beginning with `<h2 ...>What you can publish</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Your content</h2>

  <p style="margin-bottom: 1rem;">
    <strong>You own your Content.</strong> Markland claims no ownership of any document, title, comment, or other material you publish through the Service.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>License to operate.</strong> By publishing Content through Markland, you grant Markland a worldwide, non-exclusive, royalty-free license to host, store, reproduce, transmit, render, and display that Content solely as necessary to operate the Service for you and the people or Agents you have granted access to. This license is limited in scope: it does not give Markland the right to use your Content for advertising, training AI models, or any other purpose not strictly required to deliver the Service. The license terminates when you delete the Content or your Account, except for residual copies in encrypted backups, which are deleted within 30 days per the retention schedule on <a href="/privacy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/privacy</a>.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Public Documents.</strong> Content you mark public may be indexed by search engines, retrieved by AI crawlers (subject to <code>robots.txt</code>), forked by other users via the Save-to-Markland flow, and quoted under fair-use principles. Setting visibility back to private removes the URL from the public index but does not retract copies third parties may have already retrieved.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Representations.</strong> By publishing Content you confirm that (a) you own it or have a license sufficient to grant the rights described in this section, (b) the Content does not violate the Acceptable Use restrictions, and (c) public-mode Content is intentionally public.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Your content"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Your content + license-to-operate + public-content disclosure"
```

---

## Task 7: Section — Our service

**Files:**
- Modify: `src/markland/web/templates/terms.html` — replace the existing "Beta-stage software" `<h2>` block.

- [ ] **Step 1: Replace the beta-stage section**

Find the block beginning with `<h2 ...>Beta-stage software</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Our service</h2>

  <p style="margin-bottom: 1rem;">
    <strong>Beta status.</strong> Markland is in active beta, operated by a single individual developer. The Service is provided on an "as-is, as-available" basis. Please don't put anything on Markland that you cannot afford to lose access to or that you wouldn't be willing to re-host elsewhere on a few hours' notice.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Service availability.</strong> We aim for high availability but do not guarantee any specific uptime or performance level. The Service may be unavailable due to maintenance, failures, third-party outages, or events outside our control. We make no commitment about response times for support requests during beta.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Changes to the Service.</strong> Features may be added, modified, or removed during beta with or without notice. We will give reasonable advance notice (at least 14 days, where feasible) before discontinuing core publishing or sign-in functionality, and will provide an export path for your documents before any wholesale data removal.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Pricing.</strong> The Service is currently offered without charge during beta. We may introduce paid tiers in the future; if we do, existing accounts will receive at least 30 days' notice before any feature you currently use becomes paid-only, and grandfathering decisions will be communicated in writing.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Our service"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Our service — beta status, availability, changes, pricing"
```

---

## Task 8: Section — Termination

**Files:**
- Modify: `src/markland/web/templates/terms.html` — replace the existing "Termination & data" `<h2>` block.

- [ ] **Step 1: Replace the termination section**

Find the block beginning with `<h2 ...>Termination &amp; data</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Termination</h2>

  <p style="margin-bottom: 1rem;">
    <strong>Termination by you.</strong> You can stop using Markland at any time. To delete your Account and associated Content, follow the process described on <a href="/privacy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/privacy</a>.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Termination by us.</strong> We may suspend or terminate your Account, revoke tokens, or remove Content if you violate these Terms (especially the Acceptable Use section), if your use of the Service creates an unreasonable burden or risk for other users or for Markland, or if continued service would be illegal. Where lawful and operationally feasible, we will notify you and give you an opportunity to cure the issue before terminating.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Effect of termination.</strong> On termination, your right to use the Service ends immediately. Sections of these Terms that by their nature should survive termination — including "Your content" (as to the license retention period and IP rights), "Disclaimers," "Limitation of liability," "Indemnification," and "Governing law and disputes" — survive.
  </p>

  <p style="margin-bottom: 1rem;">
    <strong>Service discontinuation.</strong> If Markland decides to wind down the Service entirely, we will give at least 30 days' notice via email to active accounts and provide a way to export your documents before data is removed. The 30-day notice does not apply to legally compelled shutdowns or events outside our control.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Termination"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Termination — by you, by us, survival, discontinuation"
```

---

## Task 9: Section — Disclaimers

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Termination section.

- [ ] **Step 1: Append the disclaimers section**

Append after the closing `</p>` of the Termination section's "Service discontinuation" paragraph:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Disclaimers</h2>

  <p style="margin-bottom: 1rem;">
    THE SERVICE AND ALL CONTENT, INFORMATION, AND MATERIALS AVAILABLE THROUGH IT ARE PROVIDED "AS IS" AND "AS AVAILABLE," WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, MARKLAND DISCLAIMS ALL WARRANTIES, INCLUDING IMPLIED WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, NON-INFRINGEMENT, AND ANY WARRANTY ARISING OUT OF COURSE OF DEALING OR USAGE OF TRADE.
  </p>

  <p style="margin-bottom: 1rem;">
    Markland does not warrant that the Service will be uninterrupted, secure, error-free, or free from viruses or other harmful components, or that defects will be corrected. Markland makes no warranty about the accuracy, reliability, completeness, or timeliness of any Content available through the Service.
  </p>

  <p style="margin-bottom: 1rem;">
    Some jurisdictions do not allow the exclusion of certain warranties, so some of the above may not apply to you. In those jurisdictions the disclaimers apply to the maximum extent permitted by local law.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Disclaimers"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Disclaimers section"
```

---

## Task 10: Section — Limitation of liability

**Files:**
- Modify: `src/markland/web/templates/terms.html` — replace the existing "Liability" `<h2>` block.

- [ ] **Step 1: Replace the liability section**

Find the block beginning with `<h2 ...>Liability</h2>` and ending after its `</p>`. Replace with:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Limitation of liability</h2>

  <p style="margin-bottom: 1rem;">
    TO THE MAXIMUM EXTENT PERMITTED BY APPLICABLE LAW, IN NO EVENT WILL MARKLAND BE LIABLE TO YOU FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES, INCLUDING DAMAGES FOR LOST PROFITS, LOST REVENUE, LOST DATA, BUSINESS INTERRUPTION, OR ANY OTHER COMMERCIAL DAMAGES OR LOSSES, ARISING OUT OF OR RELATED TO YOUR USE OF THE SERVICE, EVEN IF MARKLAND HAS BEEN ADVISED OF THE POSSIBILITY OF SUCH DAMAGES.
  </p>

  <p style="margin-bottom: 1rem;">
    MARKLAND'S TOTAL CUMULATIVE LIABILITY FOR ALL CLAIMS ARISING OUT OF OR RELATED TO THESE TERMS OR THE SERVICE IS LIMITED TO THE GREATER OF (A) THE AMOUNT YOU HAVE PAID MARKLAND FOR THE SERVICE IN THE TWELVE MONTHS BEFORE THE CLAIM AROSE OR (B) ONE HUNDRED U.S. DOLLARS. SINCE THE BETA IS FREE, (A) IS CURRENTLY ZERO AND (B) APPLIES.
  </p>

  <p style="margin-bottom: 1rem;">
    Some jurisdictions do not allow the limitation of liability for incidental or consequential damages, so the above limitations may not apply to you. The limitations apply to the fullest extent permitted by local law, and nothing in these Terms limits liability that cannot lawfully be limited (such as for gross negligence or willful misconduct in jurisdictions where that is the case).
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Limitation of liability"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Limitation of liability with $100 floor"
```

---

## Task 11: Section — Indemnification

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Limitation of liability section.

- [ ] **Step 1: Append the indemnification section**

Append after the closing `</p>` of the Limitation of liability section's last paragraph:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Indemnification</h2>

  <p style="margin-bottom: 1rem;">
    You agree to indemnify and hold harmless Markland and its operator from any claim, demand, loss, or damage (including reasonable attorneys' fees) brought by a third party arising out of (a) Content you publish through the Service, (b) your violation of these Terms, (c) your violation of any law or any rights of a third party, or (d) actions taken by an Agent acting under a token issued from your Account. Markland will give you notice of any such claim and reasonable cooperation in the defense at your expense; you may not settle a claim that imposes obligations on Markland without our prior written consent.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Indemnification"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Indemnification section incl. agent-action coverage"
```

---

## Task 12: Section — Governing law and disputes

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Indemnification section.

- [ ] **Step 1: Append the disputes section**

Append after the closing `</p>` of the Indemnification section:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Governing law and disputes</h2>

  <p style="margin-bottom: 1rem;">
    These Terms are governed by the laws of the State of Delaware, United States, without regard to conflict-of-laws principles, except that the United Nations Convention on Contracts for the International Sale of Goods does not apply.
  </p>

  <p style="margin-bottom: 1rem;">
    Any dispute arising out of or related to these Terms or the Service that cannot be resolved through good-faith discussion will be brought exclusively in the state or federal courts located in Delaware, and you consent to personal jurisdiction in those courts. Either party may seek injunctive or equitable relief in any court of competent jurisdiction to protect intellectual property rights.
  </p>

  <p style="margin-bottom: 1rem;">
    Nothing in this section prevents either party from raising a dispute in a small-claims court of competent jurisdiction, where available, for claims that fit within that court's monetary limits. Class actions and class arbitrations are not permitted; each party may bring claims only in their individual capacity.
  </p>

  <p style="margin-bottom: 1rem;">
    If you are an EU/UK consumer, this section does not deprive you of mandatory consumer protections in your country of residence; in that case the courts of your country of residence may have concurrent jurisdiction.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Governing law and disputes"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Governing law and disputes — Delaware, no class actions"
```

---

## Task 13: Section — General

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Governing law section.

- [ ] **Step 1: Append the general section**

Append after the closing `</p>` of the Governing law section:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">General</h2>

  <ul style="margin-bottom: 1rem; padding-left: 1.4rem; line-height: 1.65;">
    <li><strong>Entire agreement.</strong> These Terms, together with the <a href="/privacy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">Privacy Policy</a>, are the entire agreement between you and Markland regarding the Service and supersede any prior agreements on the same subject.</li>
    <li><strong>Severability.</strong> If any provision of these Terms is held unenforceable, the remaining provisions remain in full force, and the unenforceable provision will be reformed to the minimum extent necessary to make it enforceable while preserving its intent.</li>
    <li><strong>No waiver.</strong> A failure or delay by Markland in enforcing any right under these Terms is not a waiver of that right.</li>
    <li><strong>Assignment.</strong> You may not assign or transfer your rights or obligations under these Terms without Markland's prior written consent. Markland may assign these Terms in connection with a merger, acquisition, or sale of substantially all of its assets, on notice to you.</li>
    <li><strong>No agency.</strong> Nothing in these Terms creates a partnership, joint venture, employment, or agency relationship between you and Markland.</li>
    <li><strong>Force majeure.</strong> Markland is not liable for failure or delay in performance caused by events outside its reasonable control, including natural disasters, war, civil unrest, government actions, internet outages, or third-party-service failures.</li>
    <li><strong>Notices.</strong> We may give you notice through the email address on your Account, through a notice posted on the Service, or by any other reasonable means. You may give us notice using the address in the "Contact" section below.</li>
  </ul>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"General"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): General provisions section"
```

---

## Task 14: Section — Changes to these terms

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the General section.

- [ ] **Step 1: Append the changes section**

Append after the closing `</ul>` of the General section:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Changes to these terms</h2>

  <p style="margin-bottom: 1rem;">
    We may update these Terms from time to time. The "Last updated" date at the top of the page reflects the most recent revision. For material changes — anything that meaningfully expands what you owe Markland, narrows what Markland owes you, or changes how disputes are resolved — we will notify active account holders by email at least 14 days before the change takes effect. Continuing to use the Service after the effective date constitutes acceptance of the updated Terms; if you do not accept, you may delete your Account before the effective date.
  </p>

  <p style="margin-bottom: 1rem;">
    The full revision history of this page is available in the public Markland repository on GitHub (<a href="https://github.com/dghiles/markland" style="color: var(--blue); border-bottom: 1px solid var(--outline);">github.com/dghiles/markland</a>). Every word change is on the record.
  </p>
```

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: failure list shrinks by `"Changes to these terms"`.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Changes to these terms + 14-day material-change notice"
```

---

## Task 15: Section — Contact

**Files:**
- Modify: `src/markland/web/templates/terms.html` — append after the Changes section.

- [ ] **Step 1: Append the contact section**

Append after the closing `</p>` of the Changes section's "Every word change is on the record" paragraph:

```html
  <h2 style="margin-top: 2rem; margin-bottom: 0.6rem;">Contact</h2>

  <p style="margin-bottom: 1rem;">
    For any question about these Terms, or to send a notice required under them, contact <a href="mailto:legal@markland.dev" style="color: var(--blue); border-bottom: 1px solid var(--outline);">legal@markland.dev</a>. For privacy-related requests (data access, deletion, export), see <a href="/privacy" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/privacy</a>. For security-specific reports, see <a href="/security" style="color: var(--blue); border-bottom: 1px solid var(--outline);">/security</a>.
  </p>

  <p style="margin-bottom: 1rem;">
    The operator is reachable at <a href="https://github.com/dghiles" rel="author" style="color: var(--blue); border-bottom: 1px solid var(--outline);">@dghiles on GitHub</a>.
  </p>
```

(`legal@markland.dev` should be wired as a forwarding alias before
this lands in production. Filing as a follow-up rather than blocking
this PR — the page can ship pointing at the alias even if the alias is
created hours later. Add a beads issue: `bd create --title="Provision
legal@markland.dev forwarding alias" --type=task --priority=2`.)

- [ ] **Step 2: Run the structure test**

```bash
uv run pytest tests/test_trust_pages.py::test_terms_has_standard_sections -v
```

Expected: PASS — all 14 sections now present.

- [ ] **Step 3: Commit**

```bash
git add src/markland/web/templates/terms.html
git commit -m "feat(terms): Contact section + legal@markland.dev alias"
```

---

## Task 16: Bump word-count floor + final verification

**Files:**
- Modify: `tests/test_trust_pages.py:68` — bump the `/terms` word-count floor from 250 to 900.

- [ ] **Step 1: Edit the parametrize tuple**

In `tests/test_trust_pages.py`, find the parametrize block at lines 59-71. Replace the `("/terms", 250)` entry with `("/terms", 900)`. The block becomes:

```python
@pytest.mark.parametrize(
    ("path", "min_words"),
    [
        # Audit 2026-04-24 C4: every trust page must clear the 250-word
        # E-E-A-T thin-content floor. Page-specific floors picked above
        # the audit baseline (about 98w, security 118w, privacy 101w,
        # terms 95w) — never let regression silently re-thin them.
        # 2026-05-04: privacy floor bumped to 800 (formal privacy policy);
        # terms floor bumped to 900 (formal Terms of Service).
        ("/about", 250),
        ("/security", 300),
        ("/privacy", 800),
        ("/terms", 900),
    ],
)
```

- [ ] **Step 2: Run the word-count test**

```bash
uv run pytest tests/test_trust_pages.py::test_trust_page_word_count -v -k terms
```

Expected: PASS. (The new sections combined produce ~1000-1200 words; if this fails with a count below 900, the executor missed a section — re-read the page output and confirm all of Task 3-15 landed.)

- [ ] **Step 3: Run the entire trust-pages suite**

```bash
uv run pytest tests/test_trust_pages.py -q
```

Expected: all green. Specifically:
- `test_trust_page_title_length[/terms-30-60]` PASS
- `test_privacy_terms_meta_description_length[/terms]` PASS (current description is 137 chars, in 130-160 range)
- `test_trust_page_word_count[/terms-900]` PASS
- `test_trust_page_has_last_updated[/terms]` PASS
- `test_terms_has_standard_sections` PASS

If the meta-description test fails: the description in line 2 of `terms.html` may have drifted out of the 130-160 char window during edits. Adjust the `seo_description` set-block to ~140-150 chars.

- [ ] **Step 4: Run the entire suite to catch any unrelated regression**

```bash
uv run pytest tests/ -q
```

Expected: all green. The ToS work doesn't touch service or route code; if anything else turned red, investigate before merging.

- [ ] **Step 5: Commit**

```bash
git add tests/test_trust_pages.py
git commit -m "test(terms): bump word-count floor to 900 for full ToS"
```

---

## Task 17: Update ROADMAP

**Files:**
- Modify: `docs/ROADMAP.md` — strike "Formal Terms of Service" from the Next lane and add a Shipped entry.

- [ ] **Step 1: Remove from Next lane**

In `docs/ROADMAP.md`, find the line:

```markdown
- **Formal Terms of Service** — `/terms` says "plain-English beta terms now, legalese later." Promote to a real ToS in parallel with the formal privacy policy work; same deadline (before GA).
```

Delete it.

- [ ] **Step 2: Add to Shipped — under "Marketing + UX surface"**

Add at the top of the "Marketing + UX surface" Shipped section (after the formal privacy policy entry if that has shipped, otherwise at the top):

```markdown
- **2026-05-04** — **Formal Terms of Service live.** `/terms` promoted from a "working terms summary for the public beta" to a full standard-shaped ToS: introduction & acceptance, definitions (Markland, You, Service, Account, Agent, Content, Public/Private Document), your account (16+ eligibility, agent-token responsibility), acceptable use (10 explicit prohibitions + reporting path), your content (ownership retained, license to operate, public-content disclosure), our service (beta status, availability, changes, pricing), termination (by you, by us, survival, discontinuation with 30-day notice), disclaimers (as-is/as-available), limitation of liability ($100 floor or 12 months paid), indemnification (incl. agent-action coverage), governing law (Delaware, no class actions), general (entire agreement, severability, no waiver, assignment, force majeure, notices), changes (14-day material-change notice), `legal@markland.dev` contact alias. Plan: `docs/plans/2026-05-04-formal-terms-of-service.md`.
```

- [ ] **Step 3: Commit**

```bash
git add docs/ROADMAP.md
git commit -m "docs(roadmap): formal Terms of Service shipped"
```

- [ ] **Step 4: Push**

```bash
git push origin main
```

(All commits in this plan ship to `main` via the docs-only direct-push convention in `AGENTS.md` — this work touches only template/test/docs files. No PR needed.)

---

## Out of scope (do not implement here)

- **Counsel review.** This is a standard-shaped ToS suitable for a single-developer beta with no paid customers. Before the first paid customer or material liability exposure, a licensed attorney should review and adjust for jurisdiction, industry-specific obligations (e.g., DMCA agent registration if hosting volumes grow), and any contractual obligations with sub-processors.
- **DMCA designated agent registration.** Not required for current scale (no third-party-content hosting at scale, no formal takedown queue). Revisit if Markland grows into a platform pattern.
- **Arbitration clause.** Considered and rejected for the beta — small-claims court is more accessible to consumers, and a single-developer operator has no realistic enforcement upside from arbitration. Counsel may revisit at GA + paid customers.
- **Region-specific addenda** (CCPA, EU Digital Services Act, UK consumer rights). The "Governing law and disputes" section preserves mandatory consumer protections; jurisdiction-specific addenda can be added when warranted.
- **Translating the terms.** English-only at launch; if we add translations the master is the English version on `markland.dev`.

---

## Self-review checklist (run before declaring this plan done)

- Each task ends with a `git commit` step ✅
- Every section step shows the actual HTML, not a description ✅
- Every test step shows the assertion or expected output ✅
- No "TBD" / "TODO" / "fill in" placeholders ✅
- Heading text in Task 1's test list exactly matches the heading text in Tasks 2-15 — case, wording ✅
- Word-count budget (~1000-1200w) covers the new floor (900w) with margin ✅
- All 14 sections in Task 1's required list have a corresponding write task (Tasks 2-15) ✅
- Roadmap update task included so the topic moves from Next to Shipped ✅
- `Last updated:` text added in Task 2 (required by `test_trust_page_has_last_updated`) ✅
- Pricing section (Task 7) hooks into the eventual monetization rollout ("at least 30 days' notice before any feature you currently use becomes paid-only") ✅
