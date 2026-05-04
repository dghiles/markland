# Claude Code Plugin Marketplace Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Beads:** `markland-97r` (P3; trigger-gated).

**Goal:** Publish Markland as a Claude Code plugin so users can install via `claude plugin marketplace add markland-dev/claude-plugin` (browseable on the `/plugins` Discover surface) instead of typing the full `claude mcp add ... --header` command. Bundle the MCP server config, any future slash commands or subagents, and a README that says what Markland is in two sentences.

**Architecture:** A separate public GitHub repo (`markland-dev/claude-plugin`) carrying a Claude Code plugin manifest. The plugin's `.mcp.json` points at `https://markland.dev/mcp/` so install reduces to one marketplace command followed by Claude Code's standard plugin auth handshake. No changes to the Markland server itself; this is purely a distribution-channel addition.

**Tech Stack:** GitHub repo + JSON manifests + Claude Code's plugin loader. No Python.

**Trigger gate (do not start before this is true):** **50+ active MCP installs against `markland.dev`** (measured via `markland_admin_metrics` once `users_total` clears 50) **OR** an inbound request from a community Claude Code marketplace asking to list us. Track via the soak-window analytics check (beads `markland-fjd`). Until the trigger fires, this plan stays archived.

---

## File Structure (in the new `markland-dev/claude-plugin` repo)

**Create (in the new repo):**

```
markland-dev/claude-plugin/
├── .claude-plugin/
│   ├── plugin.json          # plugin manifest (name, version, description, MCP refs)
│   └── marketplace.json     # marketplace listing (icon, screenshots, tags)
├── .mcp.json                # MCP server config — points at https://markland.dev/mcp/
├── README.md                # 2-sentence "what is Markland" + install instructions
├── LICENSE                  # MIT, matching the main markland repo
└── .github/
    └── workflows/
        └── verify.yml       # CI that lints the JSON files + checks /mcp resolves
```

**Modify (in the markland repo):**

- `src/markland/web/templates/quickstart.html` — add a "Or install as a Claude Code plugin" section with the marketplace command.
- `docs/ROADMAP.md` — strike from Later, add to Shipped.

---

## Task 1: Confirm trigger has fired

**Files:** none (gate check).

- [ ] **Step 1: Verify the trigger condition**

```bash
curl -s -H "Authorization: Bearer $(cat .env.local | grep ADMIN_TOKEN | cut -d= -f2)" \
     https://markland.dev/admin/metrics | jq '.users_total'
```

Expected: integer ≥ 50. If less than 50 AND there's no community-marketplace request, **stop here** and re-archive this plan. Do not proceed.

If a community marketplace asked us to list (signal arrives via email or GitHub issue), proceed regardless of the user count — that's the alternate trigger.

- [ ] **Step 2: Sanity-check that the user count is real adoption, not bots**

Cross-reference with Umami sessions and `markland_admin_metrics::publishes` count. If publishes is much lower than `users_total / 2` it suggests the count is inflated by signups that never activated; in that case, defer the plugin work until activation rate looks healthier.

- [ ] **Step 3: Document the trigger event**

```bash
bd update markland-97r --status=in_progress --notes="Trigger fired: <users_total or community-marketplace-request>. Proceeding with plugin publication."
```

---

## Task 2: Create the new GitHub repo

**Files:** none in this repo (work happens on github.com).

- [ ] **Step 1: Create the public repo**

```bash
gh repo create markland-dev/claude-plugin --public \
  --description "Markland MCP server as a Claude Code plugin — install via 'claude plugin marketplace add markland-dev/claude-plugin'" \
  --license=mit
```

- [ ] **Step 2: Clone the new repo locally**

```bash
gh repo clone markland-dev/claude-plugin /tmp/markland-claude-plugin
cd /tmp/markland-claude-plugin
```

- [ ] **Step 3: Add an initial empty commit so subsequent task commits have a parent**

```bash
git commit --allow-empty -m "chore: initial commit"
git push origin main
```

(The remaining tasks add files to this `/tmp/markland-claude-plugin` worktree and push from there. The Markland repo itself only changes in Task 7.)

---

## Task 3: Write `.claude-plugin/plugin.json`

**Files (in `/tmp/markland-claude-plugin`):**
- Create: `.claude-plugin/plugin.json`.

- [ ] **Step 1: Create the directory**

```bash
mkdir -p .claude-plugin
```

- [ ] **Step 2: Write the manifest**

Create `.claude-plugin/plugin.json`:

```json
{
  "name": "markland",
  "version": "0.1.0",
  "displayName": "Markland",
  "description": "Publish markdown docs from your AI agent. One MCP tool call gets you a shareable URL — no copy-paste into Notion or Google Docs.",
  "author": {
    "name": "@dghiles",
    "url": "https://github.com/dghiles"
  },
  "homepage": "https://markland.dev",
  "repository": "https://github.com/markland-dev/claude-plugin",
  "license": "MIT",
  "mcpServers": {
    "markland": {
      "type": "http",
      "url": "https://markland.dev/mcp/",
      "transport": "http"
    }
  },
  "tags": ["mcp", "publishing", "markdown", "agents", "collaboration"]
}
```

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "feat: add plugin.json manifest"
```

---

## Task 4: Write `.claude-plugin/marketplace.json`

**Files (in `/tmp/markland-claude-plugin`):**
- Create: `.claude-plugin/marketplace.json`.

- [ ] **Step 1: Write the listing**

Create `.claude-plugin/marketplace.json`:

```json
{
  "$schema": "https://claude.ai/schemas/plugin-marketplace-v1.json",
  "name": "markland",
  "displayName": "Markland — Agent-Native Publishing",
  "shortDescription": "Your agent publishes markdown to a shareable URL via one MCP tool call.",
  "longDescription": "Markland gives Claude Code (and any MCP-compatible agent) one tool — markland_publish — that turns a markdown document into a public URL. No copy-paste into Notion or Google Docs. Default-private with per-doc grants; agent-to-agent sharing is a first-class primitive. Free during beta.",
  "category": "publishing",
  "tags": ["mcp", "publishing", "markdown", "agents", "collaboration", "knowledge-management"],
  "icon": "icon.png",
  "screenshots": [
    {
      "url": "screenshots/explore.png",
      "caption": "Public docs surface on /explore"
    },
    {
      "url": "screenshots/viewer.png",
      "caption": "Clean markdown rendering with revision history"
    }
  ],
  "links": {
    "homepage": "https://markland.dev",
    "documentation": "https://markland.dev/quickstart",
    "support": "https://github.com/dghiles/markland/issues"
  },
  "pricing": "free",
  "license": "MIT"
}
```

- [ ] **Step 2: Add a placeholder icon and screenshots**

```bash
mkdir -p screenshots
# Take screenshots of /explore and a sample /d/{share_token} viewer
# from a real markland.dev session and copy them into screenshots/.
# Icon: 256x256 PNG with the Markland mark; export from the existing
# brand asset (favicon.svg or similar in the main repo).
```

(If brand assets aren't immediately available, ship without screenshots and the icon as a follow-up — `marketplace.json` references are advisory; some marketplaces accept missing optional images.)

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/marketplace.json screenshots/ icon.png 2>/dev/null
git commit -m "feat: marketplace listing + screenshots"
```

---

## Task 5: Write `.mcp.json` and `README.md`

**Files (in `/tmp/markland-claude-plugin`):**
- Create: `.mcp.json`.
- Create: `README.md`.

- [ ] **Step 1: Write `.mcp.json`**

```json
{
  "mcpServers": {
    "markland": {
      "type": "http",
      "url": "https://markland.dev/mcp/"
    }
  }
}
```

(Note: no `Authorization` header is set here. Claude Code's plugin loader handles auth via the standard MCP discovery handshake — once `markland-vtb` lands upstream, the loader will prompt for a bearer token inline; until then, users follow the device-flow path documented in the install/onboarding plan.)

- [ ] **Step 2: Write `README.md`**

```markdown
# Markland — Claude Code Plugin

Publish markdown docs from your AI agent. One MCP tool call gets you a
shareable URL — no copy-paste into Notion or Google Docs.

## Install

```bash
claude plugin marketplace add markland-dev/claude-plugin
```

Then enable Markland from Claude Code's `/plugins` panel.

## What you get

A single MCP server entry pointing at `https://markland.dev/mcp/` plus
27 tools your agent can call:

- `markland_publish` — turn markdown into a public or share-token URL
- `markland_grant` — give another human or agent read/edit access
- `markland_search` — find your past docs by title or content
- `markland_update` — edit an existing doc with version control
- `markland_revoke` — remove access
- ... and 22 more

Full reference: <https://markland.dev/quickstart>

## Auth

Markland uses bearer-token auth (RFC 9728). Mint a token at
<https://markland.dev/settings/tokens> and Claude Code will prompt for
it on first use.

## Beta

Markland is in active public beta operated by @dghiles. Privacy:
<https://markland.dev/privacy>. Terms: <https://markland.dev/terms>.

## License

MIT.
```

- [ ] **Step 3: Commit**

```bash
git add .mcp.json README.md
git commit -m "feat: .mcp.json + README"
```

---

## Task 6: Add CI verification

**Files (in `/tmp/markland-claude-plugin`):**
- Create: `.github/workflows/verify.yml`.

- [ ] **Step 1: Write the workflow**

```yaml
name: verify

on:
  push:
    branches: [main]
  pull_request:

jobs:
  verify:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Validate JSON manifests
        run: |
          for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json .mcp.json; do
            echo "Validating $f..."
            python -c "import json; json.load(open('$f'))"
          done

      - name: Verify MCP server is reachable
        run: |
          curl -fsS -o /dev/null \
            -H "Accept: application/json" \
            https://markland.dev/.well-known/oauth-protected-resource
          echo "MCP server discovery endpoint OK"
```

- [ ] **Step 2: Push to trigger first run**

```bash
git add .github/workflows/verify.yml
git commit -m "ci: validate manifests + verify MCP server reachable"
git push origin main
```

- [ ] **Step 3: Confirm green**

```bash
gh run watch --exit-status
```

Expected: workflow completes successfully.

---

## Task 7: Update Quickstart on markland.dev

**Files (back in `/Users/daveyhiles/Developer/markland`):**
- Modify: `src/markland/web/templates/quickstart.html`.
- Test: `tests/test_quickstart_page.py` (extend).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_quickstart_page.py`:

```python
def test_quickstart_mentions_plugin_install_path(client):
    """Quickstart page advertises the plugin marketplace install path."""
    r = client.get("/quickstart")
    assert r.status_code == 200
    assert "claude plugin marketplace add markland-dev/claude-plugin" in r.text
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
uv run pytest tests/test_quickstart_page.py::test_quickstart_mentions_plugin_install_path -v
```

Expected: FAIL.

- [ ] **Step 3: Add the plugin install path to quickstart.html**

In `src/markland/web/templates/quickstart.html`, find the existing install command block (the `claude mcp add ...` line) and add a new section above or below it:

```html
<h2>Or install as a Claude Code plugin</h2>
<p>If you'd rather install Markland from the Claude Code <code>/plugins</code> Discover surface:</p>
<pre><code>claude plugin marketplace add markland-dev/claude-plugin</code></pre>
<p>Then enable Markland from <code>/plugins</code> and follow the auth prompt.</p>
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
uv run pytest tests/test_quickstart_page.py::test_quickstart_mentions_plugin_install_path -v
```

Expected: PASS.

- [ ] **Step 5: Run the full quickstart suite**

```bash
uv run pytest tests/test_quickstart_page.py -q
```

Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/markland/web/templates/quickstart.html tests/test_quickstart_page.py
git commit -m "feat(quickstart): advertise Claude Code plugin install path"
```

---

## Task 8: Smoke-test the install flow end-to-end

**Files:** none (manual verification).

- [ ] **Step 1: Install via marketplace from a clean Claude Code config**

```bash
# In a separate user account or after clearing ~/.claude.json
claude plugin marketplace add markland-dev/claude-plugin
```

Expected: command succeeds; `claude plugin list` shows `markland`.

- [ ] **Step 2: Enable + auth**

In Claude Code, open `/plugins`, find Markland, click Enable. Walk through the auth handshake (mint token at `/settings/tokens` and paste).

- [ ] **Step 3: Verify tools surface**

```bash
# In a Claude Code session
markland_whoami()
```

Expected: returns principal info (`{"principal_id": "usr_...", "principal_type": "user", ...}`).

- [ ] **Step 4: Document the smoke result on the plugin repo**

Add a `SMOKE.md` to the `markland-dev/claude-plugin` repo with the date, the user count at trigger time, and a screenshot of the `/plugins` panel showing Markland enabled. This becomes the "this works" evidence for community marketplace listings.

```bash
cd /tmp/markland-claude-plugin
# write SMOKE.md
git add SMOKE.md
git commit -m "docs: smoke verification on <date> at <user_count> users"
git push origin main
```

---

## Task 9: Announce + close the loop

- [ ] **Step 1: Post a short Show HN or r/ClaudeAI announcement**

Title: "Markland is now a Claude Code plugin: `claude plugin marketplace add markland-dev/claude-plugin`"

Body: 2-sentence what-it-is + the install command + a link to a sample `/d/{share_token}` doc. Per the SEO strategy doc (`docs/audits/2026-05-03-seo-strategy/SEO-STRATEGY.md`), this is the kind of brand-mention we want — earned, on-topic, with a real product to point at.

- [ ] **Step 2: Update beads**

```bash
bd close markland-97r --reason="Plugin published at github.com/markland-dev/claude-plugin; marketplace listing live; quickstart updated; smoke-verified."
bd sync
```

- [ ] **Step 3: Update ROADMAP**

In `docs/ROADMAP.md`:

1. Remove the Claude Code plugin marketplace entry from the Later lane (or wherever it's tagged).
2. Add at the top of the "Marketing + UX surface" Shipped section:

```markdown
- **<DATE>** — **Claude Code plugin published.** `claude plugin marketplace add markland-dev/claude-plugin` now installs Markland as a first-party plugin on the `/plugins` Discover surface, with `.mcp.json` pointing at `https://markland.dev/mcp/`. Reduces install friction from "copy this `claude mcp add` command and paste a bearer token" to "click Enable in /plugins." Trigger fired at <user_count> active installs. Closes `markland-97r`. Plan: `docs/plans/2026-05-04-claude-code-plugin-marketplace.md`. Plugin repo: <https://github.com/markland-dev/claude-plugin>.
```

```bash
git add docs/ROADMAP.md .beads/issues.jsonl
git commit -m "docs(roadmap): Claude Code plugin published"
git push origin main
```

---

## Out of scope

- **Bundling slash commands or subagents** in the plugin. v1 ships the MCP config alone. If/when Markland accumulates command/subagent shapes worth bundling, a v2 of the plugin adds them.
- **Auto-publishing the plugin from CI on every Markland release.** Plugin manifest changes are rare; manual pushes are fine.
- **Listing on multiple community marketplaces.** Start with the canonical Claude Code path (`claude plugin marketplace add`); evaluate community marketplaces if and when they reach out.
- **A signed plugin / verified publisher badge.** Wait for Anthropic's plugin-verification process to stabilize.
- **Pre-trigger work.** Do not start any of Tasks 2-9 until Task 1 confirms the trigger fired.

---

## Self-review checklist

- Each task ends with a concrete artifact (file, commit, push, or bd state change) ✅
- The trigger gate is the first task and explicitly tells the executor to stop if not met ✅
- Plugin manifests follow the published Claude Code plugin schema (verify the schema URL in `marketplace.json` against current docs at execute time) ✅
- Smoke test exercises the full install path end-to-end, not just JSON validation ✅
- ROADMAP move included so the topic transitions from Later → Shipped ✅
- No "TBD" / "TODO" placeholders ✅
- Cross-link to the SEO strategy doc for the announcement step (one of the brand-mention moves it specifically calls out) ✅
