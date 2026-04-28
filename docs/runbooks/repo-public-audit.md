# Pre-Public-Flip Audit — Markland Repository

**Date:** 2026-04-27
**Worktree:** `/Users/daveyhiles/Developer/markland-public-flip`
**Branch at audit time:** `main` @ `19db7a6` (1 ahead of `origin/main`)
**Auditor:** automated (gitleaks 8.30.1 + grep heuristics)

This runbook captures the read-only audit phase of
`docs/plans/2026-04-27-make-repo-public.md`. It freezes a snapshot of what
the repo looks like *before* the destructive cleanup steps so the result is
verifiable after Task 4 lands.

## 1. Committer / author identities

```
Davey Hiles    <daveyhiles@DGH-M3-Max.local>             ← rewrite
GitHub         <noreply@github.com>                      ← preserve
magic_davey    <9299277+dghiles@users.noreply.github.com> ← target identity
magic_davey    <daveyhiles@gmail.com>                    ← rewrite
```

Two of these expose private info:

- `daveyhiles@DGH-M3-Max.local` — hostname-derived address from a default
  `git config` setting. Reveals real name + workstation hostname.
- `daveyhiles@gmail.com` — personal email. Reveals primary contact address.

`GitHub <noreply@github.com>` is the GitHub merge-commit author — kept as-is
because it's already a public, well-known address and rewriting it would
misattribute merges that GitHub itself made.

## 2. Mailmap to apply in Task 4

```
magic_davey <9299277+dghiles@users.noreply.github.com> Davey Hiles <daveyhiles@DGH-M3-Max.local>
magic_davey <9299277+dghiles@users.noreply.github.com> magic_davey <daveyhiles@gmail.com>
```

Format: `<canonical name> <canonical email> <bad name> <bad email>`. After
`git filter-repo --mailmap` runs, `git log --all --format="%an <%ae>%n%cn <%ce>" | sort -u`
must yield exactly these two lines:

```
GitHub <noreply@github.com>
magic_davey <9299277+dghiles@users.noreply.github.com>
```

## 3. Secret-scanning results

### 3a. Working-tree (gitleaks `--no-git`)

- 2 findings, both verified false positives.

| File:line | RuleID | Verdict |
|---|---|---|
| `docs/plans/2026-04-19-hosted-infra.md:659` | `curl-auth-header` | False positive — placeholder string `Bearer local_test` in tutorial curl example. |
| `docs/plans/2026-04-19-users-and-tokens.md:2743` | `curl-auth-header` | False positive — literal placeholder `Bearer mk_usr_PASTE_HERE`. |

### 3b. Full git history (gitleaks `detect`)

At audit time: 47 commits scanned on both `seo/batch-2-trust-and-conversion`
and `origin/main`, same 2 findings as the working-tree scan, no others.

Re-run before Task 4 to pick up any commits added since this snapshot was
written — the count will be higher; only the *findings* need to stay
unchanged. Real keys would show as new findings, not as a count delta.

### 3c. Provider-prefix grep (working tree + full history)

- **Working tree:** 0 hits across `sk_live_*`, `sk_test_*`, `pk_live_*`,
  `re_*`, `AKIA*`, `ASIA*`, `ghp_*`, `gho_*`, `github_pat_*`, `xoxb-*`,
  `xoxp-*`, `AIza*`, `ya29.*`, `-----BEGIN PRIVATE KEY-----`.
- **Full history:** 0 hits across the same set.

### 3d. `.env.example` and `fly.toml`

- `.env.example` placeholder values are all empty strings.
- `fly.toml` contains no `api_key|secret|token|password|bearer|credential`-shaped lines.
- No tracked `.env`, `.pem`, `.key`, `credentials*`, or `service_account*` files.

## 4. Stray files inventory

Re-checked at audit time:

| Path | Status |
|---|---|
| `<sqlite3.Connection object at 0x10b2ef970>` (root) | Already gone. |
| `.playwright-mcp/` (root) | Already gone. |
| `mobile-full.png`, `mobile-top.png` (root) | Already gone. |

`.gitignore` will be tightened in Task 3 anyway so these can't recur.

## 5. Branches and tags

```
main                                 19db7a6  (this worktree, +1 vs origin)
seo/batch-2-trust-and-conversion     fab1fe5  (other worktree; same as origin/main, already merged)
feat/read-only-viewer-save           — behind origin/main, no unmerged commits

remotes/origin/main                  fab1fe5
remotes/origin/feat/read-only-viewer-save
                                     — behind origin/main
```

`git tag -l` returns empty — no tags to worry about.

**Implication for Task 4:** there is no in-flight branch with unmerged
commits. The history rewrite + force-push can proceed without rebasing
collaborators' work — both side branches will need to be re-fetched / reset
or simply deleted afterward.

## 6. Open items before Task 4 (history rewrite)

1. User to confirm the two non-`main` local branches (`seo/batch-2-trust-and-conversion`,
   `feat/read-only-viewer-save`) are either already merged or can be discarded.
2. User to confirm okay to force-push `main` (destructive on remote).
3. Take safety mirror clone to `/tmp/markland-backup-YYYYMMDD.git` per Task 4 Step 2.

## 7. Open items before Task 7 (visibility flip)

1. All commits on `origin/main` show `magic_davey <…@users.noreply.github.com>`
   except the preserved `GitHub <noreply@github.com>` merge entries.
2. Re-run gitleaks against the rewritten history (Task 5) and confirm same
   2-or-fewer false-positive findings.
3. Final manual sweep of any new files added between this audit and the
   flip moment.
