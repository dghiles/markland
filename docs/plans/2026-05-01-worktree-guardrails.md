# Worktree Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the recurring "primary worktree got switched to a feature branch by another agent" friction by adding two complementary guardrails: a `post-checkout` git hook that warns at the moment of violation, and a Claude Code `SessionStart` hook that auto-recovers (or loudly warns) at the start of every session.

**Architecture:** The existing `pre-commit` hook (`scripts/git-hooks/pre-commit`, landed in `ba51d66`) refuses commits on non-main branches in the primary worktree but only fires AT commit time — wasted work can land on the wrong branch beforehand. Two additional layers:

1. **`scripts/git-hooks/post-checkout`** — fires immediately after every `git checkout`. If invoked in the primary worktree and the new branch isn't `main`, print a red banner pointing at the right way to do feature work. Doesn't prevent (post-checkout can't reject — the checkout already happened), but the next agent reads the banner.
2. **`scripts/claude-hooks/worktree-check.sh`** — wired into `~/.claude/settings.json` `hooks.SessionStart`. Detects primary-worktree branch state at session start. If on a non-main branch AND working tree is clean → `git checkout main` (auto-recover). If dirty → loud warning with recovery hints, no auto-fix.

Both scripts skip linked worktrees (`<repo>/.git/worktrees/<name>` git-dir pattern) so legitimate feature work in `.worktrees/*` and `.claude/worktrees/*` is unaffected.

**Tech Stack:** Bash, git hooks, Claude Code SessionStart hook protocol (JSON output to stdout).

---

## File Structure

- Create: `scripts/git-hooks/post-checkout` — git hook, executable
- Create: `scripts/claude-hooks/worktree-check.sh` — Claude SessionStart helper, executable
- Modify: `AGENTS.md` — install instructions for both
- Test: `tests/test_git_hooks.py` — already may not exist; if not, smoke-test the hooks manually (Step 1.6 + Step 2.6) since shell scripts don't fit pytest cleanly

No code under `src/`. No new dependencies.

---

## Task 1: post-checkout git hook

**Files:**
- Create: `scripts/git-hooks/post-checkout`
- Modify: (later) `AGENTS.md`

- [ ] **Step 1.1: Re-read the existing pre-commit hook for style parity**

  ```bash
  cat scripts/git-hooks/pre-commit
  ```

  Match its style: shebang, comment header explaining why + how to install + how to bypass, `git rev-parse --git-dir` worktree detection via `case */worktrees/* )`.

- [ ] **Step 1.2: Create the script**

  Create `scripts/git-hooks/post-checkout` with mode 0755:

  ```bash
  #!/usr/bin/env bash
  # Warn when the PRIMARY worktree gets checked out to a non-main branch.
  #
  # Why: parallel agent sessions share /Users/daveyhiles/Developer/markland.
  # When one agent runs `git checkout feat/foo` here (instead of `git worktree
  # add .worktrees/foo -b feat/foo`), the next session inherits the wrong HEAD
  # and lands work on the wrong branch. The pre-commit hook catches commits
  # but not the wasted work beforehand. This hook fires immediately so the
  # offending agent (and the next one) sees the banner.
  #
  # Linked worktrees (.worktrees/*, .claude/worktrees/*) skip this check.
  #
  # Activate (one-time, per clone):
  #     ln -s ../../scripts/git-hooks/post-checkout .git/hooks/post-checkout
  #
  # post-checkout receives 3 args from git:
  #   $1 = ref of previous HEAD
  #   $2 = ref of new HEAD
  #   $3 = flag: 1 if branch checkout, 0 if file checkout
  # We only care about branch checkouts.

  set -e

  prev_head="${1:-}"
  new_head="${2:-}"
  is_branch="${3:-0}"

  # File checkout (e.g. `git checkout -- path/to/file`) — ignore.
  if [ "$is_branch" != "1" ]; then
    exit 0
  fi

  # Same SHA before and after — not a real branch switch (e.g. `git checkout main`
  # when already on main). Skip to avoid noise on no-op checkouts.
  if [ "$prev_head" = "$new_head" ]; then
    exit 0
  fi

  # Detect linked worktree.
  git_dir=$(git rev-parse --git-dir)
  case "$git_dir" in
    */worktrees/*)
      exit 0
      ;;
  esac

  branch=$(git symbolic-ref --short HEAD 2>/dev/null || true)

  # Detached HEAD (rebase, cherry-pick, bisect): let it through silently.
  if [ -z "$branch" ]; then
    exit 0
  fi

  if [ "$branch" = "main" ]; then
    exit 0
  fi

  # Loud red banner. No exit-1 — post-checkout can't reject; the checkout
  # already happened. The point is visibility.
  red=$(printf '\033[31m')
  bold=$(printf '\033[1m')
  reset=$(printf '\033[0m')
  cat >&2 <<EOF
  ${red}${bold}⚠  Primary worktree is now on '${branch}', not main.${reset}

  The primary worktree (/Users/daveyhiles/Developer/markland) should stay on
  main. Feature work belongs in an isolated worktree:

      git worktree add .worktrees/<name> -b ${branch}
      cd .worktrees/<name>

  To recover here:

      git checkout main

  See AGENTS.md for the full convention. The pre-commit hook will refuse
  commits on '${branch}' in this worktree.
  EOF

  exit 0
  ```

- [ ] **Step 1.3: Make it executable**

  ```bash
  chmod +x scripts/git-hooks/post-checkout
  ls -l scripts/git-hooks/post-checkout
  ```

  Expected: shows `-rwxr-xr-x ...`.

- [ ] **Step 1.4: Install the symlink in this clone**

  ```bash
  ln -sf ../../scripts/git-hooks/post-checkout .git/hooks/post-checkout
  ls -l .git/hooks/post-checkout
  ```

  Expected: shows the symlink pointing at `../../scripts/git-hooks/post-checkout`.

- [ ] **Step 1.5: Smoke-test the warning fires on a non-main checkout**

  ```bash
  # In primary worktree, currently on main:
  git checkout -b __test_post_checkout
  ```

  Expected: red banner appears in stderr saying primary worktree is now on `__test_post_checkout`.

  Clean up:

  ```bash
  git checkout main
  git branch -D __test_post_checkout
  ```

  Expected on the second checkout: NO banner (back on main). Branch deletion succeeds.

- [ ] **Step 1.6: Smoke-test the warning does NOT fire in a linked worktree**

  ```bash
  git worktree add /tmp/markland-wt-test -b __test_wt_checkout
  cd /tmp/markland-wt-test
  git checkout -b __test_wt_checkout_2
  ```

  Expected: NO banner in either checkout (linked worktree skips the check).

  Clean up:

  ```bash
  cd /Users/daveyhiles/Developer/markland
  git worktree remove /tmp/markland-wt-test --force
  git branch -D __test_wt_checkout __test_wt_checkout_2 2>/dev/null || true
  ```

- [ ] **Step 1.7: Commit**

  ```bash
  git add scripts/git-hooks/post-checkout
  git commit -m "chore(hooks): post-checkout warns on non-main checkout in primary worktree"
  ```

---

## Task 2: SessionStart auto-recovery script

**Files:**
- Create: `scripts/claude-hooks/worktree-check.sh`
- Modify: (later) `AGENTS.md`

- [ ] **Step 2.1: Create the script directory**

  ```bash
  mkdir -p scripts/claude-hooks
  ```

- [ ] **Step 2.2: Create the script**

  Create `scripts/claude-hooks/worktree-check.sh` with mode 0755:

  ```bash
  #!/usr/bin/env bash
  # Claude Code SessionStart hook for the markland repo.
  #
  # Detects whether the primary worktree at /Users/daveyhiles/Developer/markland
  # is on main. If not:
  #   - Working tree CLEAN  → run `git checkout main` automatically (auto-recover)
  #   - Working tree DIRTY  → emit a loud warning into the session context, no fix
  #
  # Wires into ~/.claude/settings.json:
  #
  #     "hooks": {
  #       "SessionStart": [
  #         { "matcher": "", "hooks": [
  #           { "type": "command", "command": "/Users/daveyhiles/Developer/markland/scripts/claude-hooks/worktree-check.sh" }
  #         ]}
  #       ]
  #     }
  #
  # The hook contract: print JSON to stdout with shape
  #   {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "<text>"}}
  # The text is injected into the session as additional context.

  set -e

  REPO=/Users/daveyhiles/Developer/markland

  # Only fire for sessions whose CWD is inside the markland repo. SessionStart
  # runs for every Claude session, so guard early.
  case "$PWD" in
    "$REPO"|"$REPO"/*) ;;
    *) exit 0 ;;
  esac

  # Skip if we're inside a linked worktree — the parent worktree's branch
  # state is irrelevant to this session.
  git_dir=$(cd "$REPO" && git rev-parse --git-dir 2>/dev/null || true)
  if [ -z "$git_dir" ]; then
    exit 0
  fi
  case "$PWD" in
    "$REPO"/.worktrees/*|"$REPO"/.claude/worktrees/*) exit 0 ;;
  esac

  branch=$(cd "$REPO" && git symbolic-ref --short HEAD 2>/dev/null || true)

  if [ -z "$branch" ] || [ "$branch" = "main" ]; then
    exit 0
  fi

  # Working tree clean? Both staged and unstaged must be empty.
  dirty=$(cd "$REPO" && git status --porcelain 2>/dev/null | head -1)

  if [ -z "$dirty" ]; then
    # Auto-recover.
    (cd "$REPO" && git checkout main >/dev/null 2>&1) || true
    msg="Primary worktree was on '$branch'; auto-recovered to main (working tree was clean). See AGENTS.md."
  else
    # Dirty — leave it alone, warn loudly.
    msg=$(cat <<EOF
  ⚠ Primary worktree is on '$branch' with uncommitted changes. AGENTS.md says the primary worktree should stay on main; feature work belongs in .worktrees/<name>.

  To recover safely:
    1. Inspect: cd $REPO && git status
    2. If the WIP belongs on '$branch', stash or commit it there: git stash push -u -m "wip"
    3. Switch back: git checkout main
    4. Re-pop if needed in a fresh worktree: git worktree add .worktrees/$branch -b $branch && cd .worktrees/$branch && git stash pop

  The pre-commit hook will refuse commits on '$branch' from the primary worktree.
  EOF
  )
  fi

  # Emit JSON to stdout per Claude Code SessionStart hook protocol.
  jq -n --arg c "$msg" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $c
    }
  }'
  ```

- [ ] **Step 2.3: Make it executable**

  ```bash
  chmod +x scripts/claude-hooks/worktree-check.sh
  ```

- [ ] **Step 2.4: Smoke-test the auto-recover path**

  ```bash
  # Verify clean main first:
  cd /Users/daveyhiles/Developer/markland
  git status --porcelain  # should be empty
  git checkout -b __test_session_check
  bash scripts/claude-hooks/worktree-check.sh | jq -r '.hookSpecificOutput.additionalContext'
  git branch --show-current
  ```

  Expected:
  - script output contains `auto-recovered to main`
  - `git branch --show-current` reports `main` (the script switched it back)

  Clean up:

  ```bash
  git branch -D __test_session_check 2>/dev/null || true
  ```

- [ ] **Step 2.5: Smoke-test the dirty-warn path**

  ```bash
  cd /Users/daveyhiles/Developer/markland
  git checkout -b __test_session_dirty
  echo "scratch" > /tmp/scratch_marker
  cp /tmp/scratch_marker scratch_marker.txt
  git add scratch_marker.txt
  bash scripts/claude-hooks/worktree-check.sh | jq -r '.hookSpecificOutput.additionalContext' | head -3
  git branch --show-current
  ```

  Expected:
  - script output contains `uncommitted changes`
  - `git branch --show-current` is still `__test_session_dirty` (NOT auto-fixed)

  Clean up:

  ```bash
  git rm -f scratch_marker.txt
  git checkout main
  git branch -D __test_session_dirty
  rm /tmp/scratch_marker
  ```

- [ ] **Step 2.6: Smoke-test the linked-worktree skip**

  ```bash
  cd /Users/daveyhiles/Developer/markland
  git worktree add .worktrees/__test_session_skip -b __test_session_skip
  cd .worktrees/__test_session_skip
  bash /Users/daveyhiles/Developer/markland/scripts/claude-hooks/worktree-check.sh
  echo "exit=$?"
  ```

  Expected: zero output, `exit=0` (linked worktree, hook short-circuits before any work).

  Clean up:

  ```bash
  cd /Users/daveyhiles/Developer/markland
  git worktree remove .worktrees/__test_session_skip --force
  git branch -D __test_session_skip 2>/dev/null || true
  ```

- [ ] **Step 2.7: Commit**

  ```bash
  git add scripts/claude-hooks/worktree-check.sh
  git commit -m "chore(hooks): SessionStart hook auto-recovers primary worktree to main"
  ```

---

## Task 3: Update AGENTS.md with install instructions

**Files:**
- Modify: `AGENTS.md`

- [ ] **Step 3.1: Read current AGENTS.md**

  ```bash
  cat AGENTS.md
  ```

  Confirm: existing "One-time setup" section already documents the pre-commit symlink. The new sections add post-checkout symlink + SessionStart hook wiring.

- [ ] **Step 3.2: Edit AGENTS.md**

  Replace the existing "One-time setup" section in `AGENTS.md`:

  ```markdown
  ## One-time setup

  Activate the git hooks (refuse commits on non-main in primary worktree;
  warn on non-main checkouts in primary worktree):

  ```bash
  ln -sf ../../scripts/git-hooks/pre-commit .git/hooks/pre-commit
  ln -sf ../../scripts/git-hooks/post-checkout .git/hooks/post-checkout
  ```

  Activate the Claude Code SessionStart hook (auto-recovers primary
  worktree to main if it got switched between sessions). Add this to
  `~/.claude/settings.json` under `hooks.SessionStart`:

  ```json
  {
    "matcher": "",
    "hooks": [
      {
        "type": "command",
        "command": "/Users/daveyhiles/Developer/markland/scripts/claude-hooks/worktree-check.sh"
      }
    ]
  }
  ```

  See `scripts/git-hooks/{pre-commit,post-checkout}` and
  `scripts/claude-hooks/worktree-check.sh` for the full logic and bypass
  switches.
  ```

- [ ] **Step 3.3: Commit**

  ```bash
  git add AGENTS.md
  git commit -m "docs(agents): document post-checkout + SessionStart worktree hooks"
  ```

---

## Task 4: Operator wires up the SessionStart hook (OPERATOR ACTION)

**Files:** `~/.claude/settings.json` (per-user, not in repo).

- [ ] **Step 4.1: Read current ~/.claude/settings.json**

  ```bash
  jq '.hooks.SessionStart' ~/.claude/settings.json
  ```

  Expected: existing array with `bd prime` and the date-context hook.

- [ ] **Step 4.2: Add the worktree-check command**

  Edit `~/.claude/settings.json`. Find `hooks.SessionStart`, append a third entry to the inner `hooks` array:

  ```json
  {
    "type": "command",
    "command": "/Users/daveyhiles/Developer/markland/scripts/claude-hooks/worktree-check.sh"
  }
  ```

  Final `SessionStart[0].hooks` array should be three entries: `bd prime`, the existing `jq -n ... TODAY` line, and the new worktree-check.

- [ ] **Step 4.3: Validate JSON**

  ```bash
  jq '.' ~/.claude/settings.json > /dev/null
  echo "valid: $?"
  ```

  Expected: `valid: 0`. If non-zero, you have a syntax error — re-read the file.

- [ ] **Step 4.4: Verify in a fresh session**

  Start a new Claude Code session in `/Users/daveyhiles/Developer/markland`. The session-start banner should include any worktree-check output if main was deflected; on a clean session it should be silent (no error, no extra banner).

  To force a positive test:

  ```bash
  cd /Users/daveyhiles/Developer/markland
  git checkout -b __test_real_session
  ```

  Then start a fresh Claude session — it should auto-recover to main and surface the message in the session-start context. Verify by asking Claude "what branch is the primary worktree on" — it should say `main`.

  Clean up: `git branch -D __test_real_session` if it survived.

---

## Verification matrix

| Check | Command / Action | Expected |
|---|---|---|
| post-checkout fires on non-main | `git checkout -b _foo` in primary | red banner |
| post-checkout silent on main | `git checkout main` (already on main) | no output |
| post-checkout silent in linked worktree | `git checkout` in `.worktrees/x` | no output |
| pre-commit still works | `git commit` on non-main in primary | refused |
| SessionStart auto-recovers clean | clean primary on `_foo`, fresh session | switched to main, message |
| SessionStart warns dirty | dirty primary on `_foo`, fresh session | warning, no fix |
| SessionStart silent in linked worktree | session in `.worktrees/x` | no output |

---

## Rollback

If any hook causes friction:

```bash
rm .git/hooks/post-checkout
# and remove the worktree-check entry from ~/.claude/settings.json hooks.SessionStart
```

The scripts in the repo can stay; they're inert without the symlink and the settings entry. To fully revert, also `git revert` the three commits from Tasks 1–3.

---

## Self-review

**Spec coverage check:**
- post-checkout warning hook → Task 1 ✓
- SessionStart auto-recovery (clean) → Task 2.4 ✓
- SessionStart warn (dirty) → Task 2.5 ✓
- Linked-worktree skip in both → Task 1.6 + Task 2.6 ✓
- AGENTS.md install instructions → Task 3 ✓
- Per-user settings wiring → Task 4 ✓
- Rollback path → end-of-doc ✓

**Placeholder scan:** No `TBD`/`TODO`/`fill in`. Test branch names use `__test_*` prefix to make accidental survival easy to spot and clean up.

**Type/name consistency:**
- `scripts/git-hooks/post-checkout` referenced in Task 1.2 (creation), 1.4 (symlink target), and Task 3.2 (AGENTS.md install snippet) — same path everywhere
- `scripts/claude-hooks/worktree-check.sh` referenced in Task 2.2 (creation), 2.4–2.6 (smoke tests), Task 3.2 (AGENTS.md), Task 4.2 (settings command) — same path everywhere
- The "linked worktree skip" predicate (`case "$git_dir" in */worktrees/* )` for git hooks; `case "$PWD" in .worktrees/*|.claude/worktrees/*` for the SessionStart script) uses different mechanisms because the SessionStart script may not be invoked from inside the repo at all — both are correct for their context.

**Known limitation:** The SessionStart hook runs from the user's home `~/.claude/settings.json`, which is not in the markland repo. Its absence on a fresh laptop is silent (no breakage, just no auto-recovery). AGENTS.md Task 3 captures the wiring in repo docs so any operator (including future-you) can re-establish it from the README trail.
