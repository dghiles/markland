# Fix Fly Deploy Launch-Group Drift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `flyctl deploy` against the markland app update machine `185191df264378` in place instead of creating a sibling orphan. End state: a routine no-op deploy rolls the existing machine, the release counter advances by exactly one, and zero stray machines/volumes remain.

**Context:** Every `flyctl deploy --remote-only` against this app produces *"Your app doesn't have any Fly Launch machines, so we'll create one now"* even though `flyctl machine list` correctly returns 1 machine with all the right metadata fields (`fly_process_group: app`, `fly_platform_version: v2`, `fly_release_id` set). On 2026-04-28 this caused two consecutive sibling-machine incidents during the dispatcher-observability and Resend-domain rollouts; both required manual clean-up of an orphan machine + orphan 1GB volume. CI auto-deploy is currently disabled (`.github/workflows/deploy.yml` only runs on `workflow_dispatch`) precisely because of this. The shipped workaround is build-then-`machine-update`-in-place, which works but is clumsy. Diagnostic data already gathered: machine metadata reports `fly_release_version: 31` while `flyctl releases` reports `v33` (failed) is latest — the machine's release pointer drifted 2 versions behind. The most likely root cause is that the machine's `fly_release_id` no longer points at the head release in Fly's app-state, so `flyctl deploy`'s "find machines tagged with current release" lookup returns empty and it falls back to "create new."

**Architecture:** Step-by-step diagnostic, no code changes in markland source. Each task is either a read-only probe (no risk) or a single targeted Fly API mutation that I'll surface for explicit user confirm before running. We progress from cheapest/safest fix (re-pointing release metadata via `flyctl machine update --metadata`) to escalations (Fly support ticket) only if cheaper fixes fail. Once `flyctl deploy` updates in place, re-enable the CI workflow's `push` trigger.

**Tech Stack:** flyctl 0.4.41, Fly Machines v2 API. No Python changes.

---

## File Structure

**No code files modified for diagnosis (Tasks 1–4).**

**Files modified once verified (Tasks 5 + 6):**
- `.github/workflows/deploy.yml` — restore the `push: branches: [main]` trigger and update the disabled-comment to a re-enabled one.
- `docs/FOLLOW-UPS.md` — strike the "Fly launch-group registration is broken" entry once verified.

**No new files. No tests in the markland test suite (this is infra state, not code behavior).**

---

## Task 1: Snapshot current state (read-only baseline)

**Goal:** capture the exact pre-fix state so any change is observable. Zero mutation.

- [ ] **Step 1.1: Snapshot machines, volumes, releases**

Run each command and save the output to a scratch file (don't commit). The plan calls for capturing-on-paper because some Fly state — specifically release-counter values — won't be reversible if the diagnostic tasks fail.

```bash
mkdir -p /tmp/fly-deploy-fix && cd /tmp/fly-deploy-fix
flyctl machine list -a markland > machines-before.txt
flyctl volumes list -a markland > volumes-before.txt
flyctl releases -a markland > releases-before.txt
flyctl scale show -a markland > scale-before.txt
flyctl machine status 185191df264378 -a markland --display-config > machine-config-before.json
flyctl secrets list -a markland > secrets-before.txt
ls -la /tmp/fly-deploy-fix
```

**Expected output:** six files, all non-empty. The machine config JSON should be ~2-4 KB and contain the `metadata` block.

- [ ] **Step 1.2: Verify the suspected drift**

```bash
grep "fly_release_version" /tmp/fly-deploy-fix/machine-config-before.json
head -2 /tmp/fly-deploy-fix/releases-before.txt
```

**Expected output:**
- The machine's `fly_release_version` in the JSON is **lower** than the latest release shown in `releases-before.txt` (e.g., `"fly_release_version": "31"` while latest release is `v33`). This confirms the diagnosis: the machine's release pointer is stale.

If the versions actually match, the diagnosis is wrong and the plan needs adjustment — STOP and report.

- [ ] **Step 1.3: Note the current image and volume IDs**

```bash
grep -E "Image|185191df264378" /tmp/fly-deploy-fix/machines-before.txt
grep "vol_" /tmp/fly-deploy-fix/volumes-before.txt
```

**Expected output:** machine `185191df264378` running an image tagged `markland:deployment-...` and attached to volume `vol_rnzwen30xp2kejkr`. Record these — they're the things we MUST NOT touch.

No commit needed; this is local scratch.

---

## Task 2: Try the cheapest fix — `flyctl machine update --metadata` to re-point the release

**Goal:** force the machine's `fly_release_id` and `fly_release_version` metadata to match the latest *successful* release. If `flyctl deploy`'s machine-targeting logic is keying off these tags, this should make it find the machine again.

- [ ] **Step 2.1: Identify the latest *successful* release (v33 is "failed", so use v32)**

```bash
flyctl releases -a markland --json 2>&1 | head -50 || flyctl releases -a markland 2>&1 | grep "complete" | head -3
```

**Expected output:** at least one row with `STATUS: complete`. The first such row's `VERSION` is the target. Per the snapshot in Task 1, that should be `v32`.

If no `complete` row is found, STOP — there's a bigger problem to diagnose first.

- [ ] **Step 2.2: Find that release's `rel_*` ID**

The metadata field on the machine is `fly_release_id` (a `rel_*` opaque string), not a version number. `flyctl releases` doesn't print the `rel_*` ID by default; you'll need:

```bash
flyctl releases -a markland --image 2>&1 | head -10
```

If that doesn't show the `rel_*` ID either, fall back to:

```bash
flyctl machine status 185191df264378 -a markland --display-config | grep "fly_release_id"
```

**Expected output:** `"fly_release_id": "rel_ljg928m79w77z43o"` (or similar). This is *the current value* on the machine — which is also the v31 release ID per the snapshot. We need a *newer* successful release ID.

If `flyctl` cannot surface `rel_*` IDs for past releases, ESCALATE to a Fly support ticket — this is a known opacity in flyctl's release model and there's no public API to enumerate `rel_*` IDs from version numbers. The escalation path is Task 4.

- [ ] **Step 2.3: ⚠ DESTRUCTIVE / SHARED-INFRA — Surface the metadata-update plan for user confirm**

Before running the next command, surface this to the user verbatim:

> *"I'm about to update the machine metadata on prod machine `185191df264378`. The change re-points `fly_release_id` from the current stale value to a newer successful release ID. This **does not** restart the machine, change the image, or touch the volume — it only edits an opaque API-side tag that `flyctl deploy` uses to find deploy targets. Worst case if it doesn't help: the machine reads the same release-version-mismatch state we have now, but with a different stale tag. Want to proceed?"*

Wait for explicit confirm. Do NOT run the next step otherwise.

- [ ] **Step 2.4: Run the metadata update**

```bash
flyctl machine update 185191df264378 \
  -a markland \
  --metadata fly_release_id=<NEWER_REL_ID> \
  --metadata fly_release_version=32 \
  --skip-start
```

`--skip-start` is critical — if the flag is missing, `flyctl machine update` will issue a stop+start cycle, causing brief downtime for a metadata-only change. (Confirmed via `flyctl machine update --help`; this flag exists and is the right one.)

**Expected output:** `Machine 185191df264378 updated successfully!` with no health-check waits (no restart). If the command stops/starts the machine despite `--skip-start`, the machine should recover within ~30 seconds; do not panic.

- [ ] **Step 2.5: Re-snapshot machine config**

```bash
flyctl machine status 185191df264378 -a markland --display-config | grep "fly_release"
```

**Expected output:** the `fly_release_id` and `fly_release_version` now show the new values. If they didn't update, STOP — the metadata flag may not behave the way the plan assumed; investigate before proceeding.

---

## Task 3: Verify the fix with a no-op deploy

**Goal:** prove that `flyctl deploy` now updates the existing machine in place.

- [ ] **Step 3.1: Verify pytest still green locally before touching prod**

```bash
cd /Users/daveyhiles/Developer/markland && uv run pytest tests/ 2>&1 | tail -3
```

**Expected output:** `XXX passed`. (As of 2026-04-29 main, 794+ pass.) If failing, fix tests before doing a deploy — nothing in this plan is supposed to break the suite.

- [ ] **Step 3.2: ⚠ DESTRUCTIVE / SHARED-INFRA — Surface the deploy plan for user confirm**

Surface to the user verbatim:

> *"I'm about to run `flyctl deploy --remote-only -a markland` against prod. Expected outcome: the existing machine `185191df264378` rolls in place with the latest code from main (~30s downtime during health-check), the release counter advances by exactly one, and **no orphan machine is created**. If an orphan IS created, that's the diagnostic outcome — Task 2's fix didn't work and we escalate to Task 4. Either way, machine `185191df264378` and volume `vol_rnzwen30xp2kejkr` stay attached and intact. Want to proceed?"*

Wait for explicit confirm.

- [ ] **Step 3.3: Run the deploy**

```bash
flyctl deploy --remote-only -a markland 2>&1 | tee /tmp/fly-deploy-fix/deploy-output.log
```

This builds the image, pushes it to the Fly registry, and asks the Fly API to roll the app's machines.

**Watch for the smoking-gun line:**
- ✅ Success: `Updating existing machines in 'app' with rolling strategy` followed by `Machine 185191df264378 update finished: success`.
- ❌ Failure: `Your app doesn't have any Fly Launch machines, so we'll create one now`.

- [ ] **Step 3.4: Inspect the post-deploy state**

```bash
flyctl machine list -a markland > /tmp/fly-deploy-fix/machines-after.txt
flyctl volumes list -a markland > /tmp/fly-deploy-fix/volumes-after.txt
diff /tmp/fly-deploy-fix/machines-before.txt /tmp/fly-deploy-fix/machines-after.txt | head -20
diff /tmp/fly-deploy-fix/volumes-before.txt /tmp/fly-deploy-fix/volumes-after.txt | head -20
```

**Expected output (success):**
- `machines-after.txt` lists exactly **one** machine with ID `185191df264378`.
- `volumes-after.txt` lists exactly **one** volume `vol_rnzwen30xp2kejkr`.
- The machine's image tag has changed (new `markland:deployment-...` value).
- No new `vol_*` IDs appear.

If a second machine or volume appears, Task 2 didn't fix it — go to Task 4 escalation. The orphan must be cleaned up before the next deploy: surface to user, get confirm, then `flyctl machine destroy <orphan-id> --force` and `flyctl volume destroy <orphan-vol-id> --yes`.

- [ ] **Step 3.5: Smoke-test the live app**

```bash
curl -sS -i https://markland.fly.dev/health | head -3
```

**Expected output:** `HTTP/2 200` and `{"status":"ok"}`. Also call any MCP tool (e.g., `markland_whoami`) from your client to confirm the rolled image still serves the same user identity (volume is intact).

If the health check passes and MCP returns the right principal, the deploy is good.

---

## Task 4: Escalation paths if Task 2's metadata fix didn't work

**Use only if Task 3 step 3.3 produced *"Your app doesn't have any Fly Launch machines"* despite the metadata change.**

- [ ] **Step 4.1: Try `flyctl scale count` to re-register the machine to the group**

`flyctl scale count` is documented as the canonical way to set machine count for a process group. Setting it to the count we already have (1) may force re-registration:

```bash
flyctl scale count 1 -a markland --process-group app --yes
```

**Expected output:** if this fixes the registration, output mentions reusing machine `185191df264378`. Otherwise it might create another orphan; inspect carefully.

After running, retry Task 3 step 3.3 (the deploy). If still fails, continue.

- [ ] **Step 4.2: Try `flyctl deploy --strategy immediate`**

`--strategy immediate` skips health-check waits and uses a different deploy path internally. Sometimes it bypasses launch-group lookup quirks:

```bash
flyctl deploy --remote-only --strategy immediate -a markland 2>&1 | tee /tmp/fly-deploy-fix/deploy-immediate.log
```

Same success/failure indicators as Task 3 step 3.3.

- [ ] **Step 4.3: Open a Fly support ticket**

If 4.1 and 4.2 both fail, this is a Fly platform bug we can't fix from the outside. File a ticket at https://fly.io/dashboard/personal/support with:

- App name: `markland`
- Machine ID: `185191df264378`
- Description: copy the relevant chunks of `/tmp/fly-deploy-fix/deploy-output.log` showing the *"doesn't have any Fly Launch machines"* line alongside `flyctl machine list -a markland` output that clearly shows the machine exists with `process_group: app`.
- Ask: "Why doesn't `flyctl deploy` recognize this machine as a launch-group target despite correct metadata? How do I re-register it?"

In the interim, the existing operator workflow (build, `machine update`, manual orphan cleanup) keeps working. STOP this plan and re-enter when Fly support has guidance.

---

## Task 5: Re-enable CI auto-deploy

**Only run this if Task 3 succeeded — the existing machine was updated in place with no orphans.**

- [ ] **Step 5.1: Restore the `push` trigger in the workflow**

Read `.github/workflows/deploy.yml` first to confirm current state, then edit:

```bash
cd /Users/daveyhiles/Developer/markland && cat .github/workflows/deploy.yml
```

The current shape is:

```yaml
name: Deploy to Fly

# DISABLED: `flyctl deploy` currently creates an orphan machine + volume on
# every run instead of updating the existing machine in place — see
# docs/FOLLOW-UPS.md ("Fly launch-group registration"). Until that's
# resolved, deploys are operator-driven via `flyctl machine update`.
#
# The workflow is left here (a) as a build-the-image side effect — pushing
# a deployment-tagged image to registry.fly.io that an operator can then
# point a machine at — and (b) so the bug stays visible.
#
# Re-enable by restoring the `push:` trigger below once the launch-group
# bug is fixed and a single fresh deploy is verified to update in place.

on:
  workflow_dispatch:
```

Replace the disabled-comment block + `on:` with this:

```yaml
name: Deploy to Fly

# Auto-deploys main to Fly via `flyctl deploy --remote-only`. Verified
# 2026-04-29 to update the existing machine 185191df264378 in place
# (the launch-group registration drift was fixed by re-pointing the
# fly_release_id metadata — see docs/plans/2026-04-29-fix-fly-deploy-
# launch-group.md). If a future deploy creates an orphan machine again,
# disable the push: trigger and reopen that plan.

on:
  push:
    branches: [main]
  workflow_dispatch:
```

Leave the `jobs:` block untouched.

- [ ] **Step 5.2: Verify the workflow YAML parses**

```bash
cd /Users/daveyhiles/Developer/markland && python3 -c "import yaml; print(yaml.safe_load(open('.github/workflows/deploy.yml')))" 2>&1 | head -5
```

**Expected output:** a Python dict printed (workflow contents). If yaml.YAMLError, the syntax is broken — fix indentation before continuing.

- [ ] **Step 5.3: Commit the re-enable**

```bash
cd /Users/daveyhiles/Developer/markland && git checkout -b chore/re-enable-ci-deploy && git add .github/workflows/deploy.yml && git commit -m "$(cat <<'EOF'
chore: re-enable CI auto-deploy after fly launch-group fix

The launch-group registration drift was fixed 2026-04-29 by re-pointing
the machine's fly_release_id metadata to the latest successful release.
Verified by running a no-op `flyctl deploy --remote-only` and observing
the existing machine 185191df264378 update in place with no orphan
sibling. See docs/plans/2026-04-29-fix-fly-deploy-launch-group.md.

If this regresses (orphan machine appears in flyctl machine list after
a CI deploy), revert this commit to restore the workflow_dispatch-only
gate and reopen the plan.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5.4: Push and open a PR**

```bash
cd /Users/daveyhiles/Developer/markland && git push -u origin chore/re-enable-ci-deploy
gh pr create --title "chore: re-enable CI auto-deploy after fly launch-group fix" --body "$(cat <<'EOF'
## Summary
- Restore the \`push: branches: [main]\` trigger on \`.github/workflows/deploy.yml\`.
- The launch-group drift was fixed 2026-04-29 (metadata re-point); verified by running a no-op deploy that updated the existing machine in place.

## Test plan
- [x] No code paths exercised; this only affects when the workflow runs.
- [ ] Post-merge: \`gh run list -w deploy.yml\` should show an automatic run on the merge commit, and \`flyctl machine list -a markland\` should still show exactly 1 machine afterward.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 5.5: Merge the PR**

```bash
cd /Users/daveyhiles/Developer/markland && gh pr merge --squash --delete-branch
```

After merge, GitHub Actions will trigger a real CI deploy — this is the actual end-to-end verification. Watch:

```bash
gh run list -w deploy.yml --limit 3
gh run watch
```

**Expected:** workflow run goes green, then `flyctl machine list -a markland` still shows exactly 1 machine. If a sibling appears, the fix didn't fully stick — disable CI again, surface to user, reopen plan.

---

## Task 6: Update docs and close the loop

**Goal:** strike the launch-group entry from `docs/FOLLOW-UPS.md` so the next reader doesn't think the bug is still open.

- [ ] **Step 6.1: Read the FOLLOW-UPS entry to confirm it still exists in current main**

```bash
cd /Users/daveyhiles/Developer/markland && grep -n "Fly launch-group" docs/FOLLOW-UPS.md
```

**Expected output:** at least one line matching, in the "Deploy / operations" section.

- [ ] **Step 6.2: Replace the bug entry with a "fixed" historical note**

Read the file, locate the entry that begins `**Fly launch-group registration is broken.**`, and replace its bullet body with a strike-through and resolution date. Keep the entry visible for future archaeology rather than deleting outright. Concretely:

Replace this paragraph:

```markdown
- **Fly launch-group registration is broken.** `flyctl deploy` (and the CI
  workflow that calls it) creates a fresh sibling machine + volume on every
  run instead of updating the existing machine `185191df264378` in place.
  ...truncated...
  an orphan that has to be manually destroyed.
```

with:

```markdown
- **~~Fly launch-group registration is broken.~~** Fixed 2026-04-29 by
  re-pointing the machine's `fly_release_id` metadata to the latest
  successful release via `flyctl machine update --metadata`. Verified
  by running `flyctl deploy --remote-only` and observing the existing
  machine `185191df264378` update in place with no orphan sibling. CI
  auto-deploy re-enabled in PR (see Task 5). Plan with full diagnostic
  steps: `docs/plans/2026-04-29-fix-fly-deploy-launch-group.md`.
```

- [ ] **Step 6.3: Per the docs-direct-push convention, commit on main**

(This is a docs-only change; per the user's saved feedback `feedback_docs_direct_push.md`, docs-only diffs go direct to main.)

```bash
cd /Users/daveyhiles/Developer/markland && git checkout main && git pull --ff-only && git add docs/FOLLOW-UPS.md && git commit -m "$(cat <<'EOF'
docs(follow-ups): strike fly launch-group bug — fixed 2026-04-29

Re-pointed the machine's fly_release_id metadata to the latest
successful release; flyctl deploy now updates the existing machine in
place. Full diagnostic in docs/plans/2026-04-29-fix-fly-deploy-launch-
group.md.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
EOF
)" && git push
```

---

## Verification

End-to-end, the plan succeeds when:

1. `flyctl machine list -a markland` shows exactly 1 machine before and after a CI-triggered deploy on a no-op commit to main.
2. `flyctl volumes list -a markland` shows exactly 1 volume.
3. The deploy-output log contains *"Updating existing machines"* and does NOT contain *"doesn't have any Fly Launch machines"*.
4. `markland_whoami` from any signed-in client still returns `usr_67c667bfc6062731` (the volume's data is intact).
5. `docs/FOLLOW-UPS.md` no longer shows the launch-group bug as open.

---

## Critical Files for Implementation

- `/Users/daveyhiles/Developer/markland/.github/workflows/deploy.yml` (Task 5)
- `/Users/daveyhiles/Developer/markland/docs/FOLLOW-UPS.md` (Task 6)
- `/tmp/fly-deploy-fix/` — scratch directory for state snapshots (Tasks 1–4); not in repo.

**Reference (no edits expected):**
- `/Users/daveyhiles/Developer/markland/fly.toml` — already correctly sets `[mounts]`, `[http_service]`, `[[vm]]`, `processes = ['app']`. Don't edit.
- `/Users/daveyhiles/Developer/markland/docs/runbooks/first-deploy.md` — historical setup; the launch-group bug post-dates this runbook.

---

## Decision Points Requiring User Confirm

Per the constraint, these moments must surface verbatim and wait for explicit "yes" before proceeding:

1. **Task 2 step 2.3** — before mutating machine metadata.
2. **Task 3 step 3.2** — before the verification deploy. This deploy is the moment we either confirm the fix or learn it didn't work and an orphan was created.
3. **Task 3 step 3.4** — IF an orphan appears, before destroying it.
4. **Task 5 step 5.5** — before merging the CI re-enable PR. (Implicitly destructive: the merge auto-triggers a real production deploy.)

No batched destructive command sequences. Any failure mode that produces an orphan machine + volume STOPS the plan and surfaces to user.
