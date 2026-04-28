# Make Markland Repo Public Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Switch `dghiles/markland` from private to public on GitHub, with a secrets-clean history under the privacy-preserving `magic_davey <9299277+dghiles@users.noreply.github.com>` identity, then apply the free branch-protection ruleset to `main` that the visibility-gated GitHub Pro APIs were blocking.

**Architecture:** Three phases. **Audit** (find secrets + identity leaks + stray artifacts; nothing destructive). **Cleanup** (rewrite history, scrub working tree, reconcile contradictions; everything reversible up to the force-push). **Publish** (flip visibility, lock down `main`, verify). The ordering matters — every cleanup must complete *before* the visibility flip, because once public, history rewrites still work but the old SHAs may already be cached by mirrors, search engines, and forks.

**Tech Stack:** `git`, `gh` CLI, `git-filter-repo`, `gitleaks` (or `trufflehog`), `ripgrep`, `bash`. No code changes — this is ops + history surgery.

---

### Task 1: Audit secrets and identity leaks

**Files:**
- Create: `docs/runbooks/repo-public-audit.md`

- [ ] **Step 1: Identify unique committer identities across all history**

Run:
```bash
git log --all --format="%an <%ae>%n%cn <%ce>" | sort -u
```

Expected (current state):
```
Davey Hiles <daveyhiles@DGH-M3-Max.local>
magic_davey <9299277+dghiles@users.noreply.github.com>
magic_davey <daveyhiles@gmail.com>
```

Two of these expose private info: the hostname-derived email (`@DGH-M3-Max.local`) and the personal Gmail. Both will be remapped in Task 4.

- [ ] **Step 2: Scan working tree for secret-shaped strings**

Install `gitleaks` if not present:
```bash
brew install gitleaks
```

Run on the working tree:
```bash
gitleaks detect --no-git --redact -v 2>&1 | tail -30
```

Expected: the only hits should be `.env.example` placeholders (e.g. `RESEND_API_KEY=` with no value) and known-safe constants. **STOP if any hit shows a real key.**

- [ ] **Step 3: Scan full git history for secrets**

```bash
gitleaks detect --redact -v 2>&1 | tail -30
```

Expected: same shape as Step 2. **STOP if any commit hash shows a real key** — the rewrite in Task 4 needs that finding folded in.

- [ ] **Step 4: List untracked + suspicious working-tree files**

```bash
git status --short
ls -la '<sqlite3.Connection object at'* 2>/dev/null
ls -la mobile-*.png 2>/dev/null
ls -la .playwright-mcp/ 2>/dev/null
```

Each of these needs an explicit decision in Task 3:
- `<sqlite3.Connection object ...>` — accidental SQLite blob from a buggy `str(conn)` path coercion. Delete.
- `mobile-full.png`, `mobile-top.png` — design screenshots. Decide: commit to `docs/screenshots/` or delete.
- `.playwright-mcp/` — Playwright MCP cache. Add to `.gitignore` and delete locally.

- [ ] **Step 5: Write the audit summary**

Write `docs/runbooks/repo-public-audit.md` with:
- Identities found and target identity
- Gitleaks results (count, severity)
- Untracked-file decisions
- Tags + branches inventory: `git tag -l`, `git branch -a`
- The exact `git-filter-repo` mailmap planned for Task 4

- [ ] **Step 6: Commit the audit**

```bash
git add docs/runbooks/repo-public-audit.md
git commit -m "docs(audit): pre-public-flip identity and secrets audit"
```

---

### Task 2: Reconcile README license claim with LICENSE file

**Files:**
- Modify: `README.md`

The repo currently has `LICENSE` (MIT) but `README.md` says "Source-available pending a decision post-launch." A public reader sees a contradiction. Pick MIT (it's what's actually in `LICENSE`) and update the README.

- [ ] **Step 1: Read current state**

```bash
grep -n -A 2 "## License" README.md
```

Expected: shows the "Source-available pending..." line.

- [ ] **Step 2: Replace the License section**

Edit `README.md` so the `## License` section reads:

```markdown
## License

[MIT](LICENSE) © magic_davey
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): align license section with MIT LICENSE file"
```

---

### Task 3: Clean working tree before history rewrite

**Files:**
- Modify: `.gitignore`
- Delete: `<sqlite3.Connection object at 0x10b2ef970>`, `.playwright-mcp/`, `mobile-full.png`, `mobile-top.png` (or move screenshots to `docs/screenshots/`)

History rewrite operates on committed history. Untracked junk in the working tree won't end up in commits, but flipping public is also when first-time visitors clone the repo — a clean tree avoids embarrassment if anything gets accidentally `git add .`-ed.

- [ ] **Step 1: Add ignores for the build/cache artifacts**

Append to `.gitignore`:
```
# Playwright MCP
.playwright-mcp/

# Stray screenshots from local dev
mobile-*.png
desktop-*.png
```

- [ ] **Step 2: Delete the accidental files**

```bash
rm -- '<sqlite3.Connection object at 0x10b2ef970>'
rm -rf .playwright-mcp/
rm -f mobile-full.png mobile-top.png
```

If you want to keep the screenshots:
```bash
mkdir -p docs/screenshots
mv mobile-full.png mobile-top.png docs/screenshots/
git add docs/screenshots/
```

- [ ] **Step 3: Verify clean tree**

```bash
git status --short
```

Expected: only the `.gitignore` modification (and `docs/screenshots/` adds, if kept).

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore playwright-mcp + stray dev screenshots"
```

---

### Task 4: Rewrite git history to remove private identities

**Files:** every commit. Destructive on remote — requires force-push.

This is the irreversible step. Make a backup branch first.

- [ ] **Step 1: Install git-filter-repo**

```bash
brew install git-filter-repo
```

Verify:
```bash
git filter-repo --version
```

- [ ] **Step 2: Make a safety mirror clone**

```bash
cd /tmp
git clone --mirror https://github.com/dghiles/markland.git markland-backup-$(date +%Y%m%d).git
cd /Users/daveyhiles/Developer/markland
```

This is a recoverable backup if the rewrite goes wrong.

- [ ] **Step 3: Write the mailmap**

Create `/tmp/markland-mailmap.txt` with:
```
magic_davey <9299277+dghiles@users.noreply.github.com> Davey Hiles <daveyhiles@DGH-M3-Max.local>
magic_davey <9299277+dghiles@users.noreply.github.com> magic_davey <daveyhiles@gmail.com>
```

Format: `<canonical name> <canonical email> <bad name> <bad email>` — replaces every commit authored or committed by the right side with the left side.

- [ ] **Step 4: Run the rewrite**

```bash
git filter-repo --mailmap /tmp/markland-mailmap.txt
```

Expected: filter-repo prints "New history written" with a commit count.

- [ ] **Step 5: Verify the rewrite**

```bash
git log --all --format="%an <%ae>%n%cn <%ce>" | sort -u
```

Expected (exactly two lines, in some order):
```
GitHub <noreply@github.com>
magic_davey <9299277+dghiles@users.noreply.github.com>
```

The `GitHub <noreply@github.com>` line is preserved on purpose — those commits were authored by GitHub's merge bot when PRs were squash-merged, and rewriting them would misattribute work GitHub did itself.

If any **other** identity appears, **STOP** and inspect with `git log --all --format="%H %an <%ae>" | grep -vE "9299277\+dghiles|noreply@github\.com"` to find the missed commits.

- [ ] **Step 6: Re-add the remote (filter-repo strips it as a safety measure)**

```bash
git remote add origin https://github.com/dghiles/markland.git
```

- [ ] **Step 7: Force-push to remote**

```bash
git push --force-with-lease origin main
git push --force --tags
```

`--force-with-lease` refuses to overwrite remote work you haven't seen. If it fails, `git fetch` first and review what landed.

- [ ] **Step 8: Verify on GitHub**

```bash
gh api /repos/dghiles/markland/commits/main --jq '.commit.author.name + " <" + .commit.author.email + ">"'
```

Expected:
```
magic_davey <9299277+dghiles@users.noreply.github.com>
```

---

### Task 5: Final secret scan against rewritten history

**Files:** read-only.

- [ ] **Step 1: Re-run gitleaks**

```bash
gitleaks detect --redact -v 2>&1 | tail -30
```

Expected: no findings. The rewrite kept the same content, only changed authors — but verifying after is cheap and necessary.

- [ ] **Step 2: Spot-check `.env.example` and `fly.toml`**

```bash
grep -nE "(api[_-]?key|secret|token|password)\s*[:=]" .env.example fly.toml | head
```

Expected: only placeholder names, no real values. If anything looks suspicious, **STOP** and either redact via another filter-repo pass or rotate the credential.

---

### Task 6: Add a minimal SECURITY.md

**Files:**
- Create: `SECURITY.md`

GitHub surfaces this on public repos as a "Report a vulnerability" link. Spending two minutes on this avoids a future "you ignored the bug I emailed you" thread.

- [ ] **Step 1: Create the file**

```markdown
# Security Policy

## Reporting a Vulnerability

If you discover a security issue in Markland, please email
**security@markland.dev** (or the email listed on https://markland.dev)
rather than opening a public issue.

You can expect a response within 72 hours. Please include:

- A description of the issue
- Steps to reproduce
- The affected version (commit SHA or release tag)

## Scope

In scope: the hosted service at https://markland.dev, the MCP server,
the web viewer, and authentication flows.

Out of scope: third-party dependencies (report upstream),
denial-of-service via rate limits (we have them; tell us if you can
bypass them).
```

- [ ] **Step 2: Commit**

```bash
git add SECURITY.md
git commit -m "docs: add SECURITY.md for vulnerability reports"
git push origin main
```

---

### Task 7: Flip repo visibility to public

**Files:** none — GitHub setting only.

- [ ] **Step 1: Pre-flip checklist**

Confirm out loud:
- All work in Tasks 1-6 has landed on `origin/main`.
- `git status` is clean.
- `gitleaks detect --redact` returns no findings.
- `git log --all --format="%ae" | sort -u` returns only `9299277+dghiles@users.noreply.github.com`.

If any check fails, **STOP** and resolve before proceeding.

- [ ] **Step 2: Flip via gh CLI**

```bash
gh repo edit dghiles/markland --visibility public --accept-visibility-change-consequences
```

- [ ] **Step 3: Verify externally**

In a different browser session (or curl):
```bash
curl -s -o /dev/null -w "%{http_code}\n" https://github.com/dghiles/markland
```

Expected: `200` (was `404` for logged-out viewers while private).

---

### Task 8: Apply branch-protection ruleset to `main`

**Files:** none — GitHub setting only.

Now that the repo is public, the ruleset API works on the Free plan.

- [ ] **Step 1: Build the ruleset payload**

Write `/tmp/main-ruleset.json`:
```json
{
  "name": "Protect main",
  "target": "branch",
  "enforcement": "active",
  "conditions": {
    "ref_name": {
      "include": ["refs/heads/main"],
      "exclude": []
    }
  },
  "rules": [
    {"type": "deletion"},
    {"type": "non_fast_forward"}
  ]
}
```

- [ ] **Step 2: Apply via gh API**

```bash
gh api -X POST /repos/dghiles/markland/rulesets --input /tmp/main-ruleset.json
```

Expected: JSON response with the new ruleset's `id` and `enforcement: "active"`.

- [ ] **Step 3: Verify the banner is gone**

Reload `https://github.com/dghiles/markland` in your browser. The "Your main branch isn't protected" banner should be gone.

---

### Task 9: Smoke test the protection

**Files:** none — exercises remote behavior.

- [ ] **Step 1: Confirm normal pushes still work**

```bash
git commit --allow-empty -m "test: normal push after protection"
git push origin main
```

Expected: push succeeds.

- [ ] **Step 2: Confirm force pushes are rejected**

```bash
git commit --amend -m "test: amend (rewrites SHA)"
git push --force origin main
```

Expected: rejected with `protected branch hook declined` or similar.

Recover:
```bash
git push origin main  # the un-amended SHA still matches
git reset --hard origin/main  # local catches up
```

- [ ] **Step 3: Confirm deletion is rejected**

```bash
git push --delete origin main
```

Expected: rejected.

- [ ] **Step 4: Clean up the test commit**

```bash
git revert HEAD --no-edit
git push origin main
```

Or, if the test commit was the empty one and you want it gone, force-push from a sister branch via PR — at this point the protection is doing its job.

---

## Self-Review Notes

- **Reversibility:** Tasks 1-3 and 6-9 are reversible. Task 4 (history rewrite + force-push) is the point of no return on shared history; the safety mirror in Task 4 Step 2 covers the local recovery case. Task 7 (visibility flip) is reversible via `gh repo edit --visibility private` but **search engines will have already seen the public state** — assume any commit visible at any moment after Task 7 is permanent on the public web.
- **Identity check before flip:** Task 7 Step 1 explicitly re-verifies the identity rewrite before flipping. Don't skip.
- **Out of scope:** GitHub Issue templates, PR templates, Code of Conduct, CONTRIBUTING.md, GitHub Actions tightening. Add later if collaborators arrive.
- **What this plan does NOT change:** the Fly.io deployment, secrets in Fly's env, the production database, the `markland.dev` DNS. All of those continue working unchanged across the visibility flip.
