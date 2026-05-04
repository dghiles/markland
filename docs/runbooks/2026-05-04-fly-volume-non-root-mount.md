# Runbook — Fly volume mount + non-root app user

**Bead:** [`markland-lvv`](https://github.com/dghiles/markland) (P3, follow-up to P1-D / `markland-l2p`)
**Status:** Patch ready — needs operator smoke test on Fly.

## Problem

Dockerfile (PR #64) drops privileges to `app` (UID 1000) before
`ENTRYPOINT`. At image-build time we `chown -R app:app /data`, but
when Fly attaches a persistent volume to `/data` on first boot, the
volume root is owned by `root:root` and our build-time chown is
shadowed. As `app`, `start.sh` cannot:

1. Write `/data/markland.db` (litestream restore fails).
2. Open `/data/markland.db` for write (uvicorn boot fails).

The current image has not been deployed since the non-root change, so
this is currently latent.

## Fix

`start.sh` runs as root just long enough to chown the volume to `app`,
then `exec`s the rest of the boot as `app`. This is idempotent (chown
is a no-op when already correct) and safe (root window is a single
syscall).

### Patch (apply at deploy time)

Both edits below are required. Land them in a small PR _just before_
running the smoke test — keep the deploy and the patch as one atomic
unit so the deploy log is the test result.

```diff
 #!/usr/bin/env sh
 set -e

+# Volume-mount fixup: when Fly attaches /data on first boot the directory
+# is owned by root, shadowing the build-time chown. Re-chown here while
+# we still have root, then exec the rest of the boot as `app`.
+#
+# Idempotent: chown of an already-app-owned tree is a no-op.
+if [ "$(id -u)" = "0" ]; then
+  DATA_DIR="${MARKLAND_DATA_DIR:-/data}"
+  chown -R app:app "${DATA_DIR}"
+  exec su app -s /bin/sh -c "/app/start.sh"
+fi
+
 DB_PATH="${MARKLAND_DATA_DIR:-/data}/markland.db"
 ...
```

And the corresponding Dockerfile change:

```diff
-USER app
-
 ENTRYPOINT ["/app/start.sh"]
```

`start.sh` enters as root → chowns the volume → re-execs itself as
`app` → falls through to the existing litestream/uvicorn block. The
existing block is unchanged.

## Smoke test (operator runs this)

This MUST pass before declaring `markland-lvv` closed.

### 1. Build + deploy

```bash
git pull
fly deploy --remote-only
```

Watch the deploy output. Expected:
- Build succeeds.
- Health check passes.
- No error logs about `/data/markland.db: Permission denied` or
  `cannot open database file`.

### 2. Verify process UID

```bash
fly ssh console -C "ps -ef | grep uvicorn | grep -v grep"
```

Expected: the uvicorn process is owned by `app`, not `root`.

### 3. Verify volume ownership

```bash
fly ssh console -C "ls -la /data"
```

Expected: `/data/markland.db` (and `*-wal`, `*-shm`) owned by
`app:app`.

### 4. Verify litestream replication still works

```bash
fly ssh console -C "tail -n 20 /tmp/litestream.log 2>/dev/null || true"
```

(Or whatever the litestream log path is.) Expected: recent
"replicated wal" / "snapshot uploaded" lines, no permission errors.

### 5. Smoke a request

```bash
curl -fsS https://markland.dev/healthz
curl -fsS https://markland.dev/ | head
```

Expected: 200 OK on both.

### 6. Force a fresh-volume case (optional, only if you want full coverage)

```bash
# Detach + recreate the data volume — DESTRUCTIVE; only run if you have a Litestream replica
# in place that will restore the DB on next boot.
fly volumes destroy data ...
fly volumes create data --region <region> --size 1
fly deploy
```

Then repeat steps 2-5. Expected: litestream restore runs, `/data/markland.db`
is repopulated, app boots as `app`, no permission errors.

## Close-out

Once steps 1-5 all pass on a real Fly deployment:

```bash
bd close markland-lvv --reason="Fly deploy smoke verified $(date +%Y-%m-%d): app process runs as UID 1000, /data owned by app:app, litestream replicates, requests serve 200."
bd sync
```

If step 6 hasn't been run, leave a note in the close reason
acknowledging that the fresh-volume path is theoretically covered but
not exercised.

## Why not a different approach?

- **`gosu` / `su-exec`** — adds a binary dependency for one syscall
  worth of work. `su` is already in `python:3.12-slim`.
- **Fly volume UID config** — Fly's `[mounts]` block doesn't expose a
  UID setting today.
- **`securityContext.fsGroup`** — Kubernetes-only.
- **chown in Dockerfile only** — already tried; volume mount shadows
  it on first boot.

The runtime chown + re-exec is the smallest possible change that
works portably (Fly today, K8s tomorrow, plain Docker in dev).
