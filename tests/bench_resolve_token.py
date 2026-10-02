"""Before/after CPU cost of resolve_token (markland-tex). Not collected by pytest.

Run on the branch, then against main's code, and paste both outputs into
the PR:

    uv run python -m tests.bench_resolve_token             # branch (worktree)
    (cd /Users/daveyhiles/Developer/markland && \
     uv run --no-sync python .worktrees/token-digest/tests/bench_resolve_token.py)   # main

Measures time.process_time(): CPU seconds, which is what Fly's shared-cpu
quota throttles. Argon2 runs on 4 threads, so wall time under-reports it.
The table is prod-shaped: 9 user + 5 agent tokens minted by the app, 1
legacy-shape token (written as the pre-digest release wrote it,
pre-cutoff), and 1 revoked token.

Exits 1 if a path marked "digest-only" makes an Argon2 verify or takes
more than CPU_BOUND_S of CPU. On main that is expected: every path pays
Argon2 there.
"""

from __future__ import annotations

import contextlib
import io
import secrets
import statistics
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from argon2 import PasswordHasher

from markland.db import init_db
from markland.service import auth
from markland.service.agents import create_agent
from markland.service.users import create_user

ITERATIONS = 10  # on main each legacy-path resolve costs ~1.5 CPU-s
CPU_BOUND_S = 0.005  # ~20x under one Argon2 verify
LEGACY_ID = "tok_benchlegacy0000"
BURST_BALANCE_S = 50.0  # CPU-s Fly grants after a deploy
BASELINE_SHARE = 0.0625  # shared-cpu-1x baseline once the balance is spent


def _has_digest_column(conn) -> bool:
    return any(r[1] == "token_digest" for r in conn.execute("PRAGMA table_info(tokens)"))


def _setup(db_path: Path):
    conn = init_db(db_path)
    with contextlib.redirect_stdout(io.StringIO()):  # metrics.emit prints JSON lines
        user = create_user(conn, email="bench@x", display_name="Bench")
        minted = [
            auth.create_user_token(conn, user_id=user.id, label=f"u{i}")
            for i in range(9)
        ]
        agent = create_agent(conn, user.id, "bench-agent")
        for i in range(5):
            auth.create_agent_token(
                conn, agent_id=agent.id, owner_user_id=user.id, label=f"a{i}"
            )
        revoked_id, revoked = auth.create_user_token(conn, user_id=user.id, label="rev")
        auth.revoke_token(conn, token_id=revoked_id, user_id=user.id)
    legacy = "mk_usr_" + secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO tokens(id, token_hash, label, principal_type, principal_id, "
        "created_at, last_used_at, revoked_at) "
        "VALUES (?, ?, 'legacy', 'user', ?, '2026-01-01T00:00:00+00:00', NULL, NULL)",
        (LEGACY_ID, auth.hash_token(legacy), user.id),
    )
    conn.commit()
    return conn, minted, legacy, revoked


def _measure(conn, plaintext: str, before=None) -> tuple[float, int]:
    cpu: list[float] = []
    verifies: list[int] = []
    for _ in range(ITERATIONS):
        if before is not None:
            before()
        auth.invalidate_token_cache()
        with patch.object(
            PasswordHasher, "verify", autospec=True, side_effect=PasswordHasher.verify
        ) as spy:
            t0 = time.process_time()
            auth.resolve_token(conn, plaintext)
            cpu.append(time.process_time() - t0)
        verifies.append(spy.call_count)
    return statistics.median(cpu), max(verifies)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        conn, minted, legacy, revoked = _setup(Path(tmp) / "bench.db")
        has_digest = _has_digest_column(conn)
        (existing_id, _) = minted[0]
        short_id = existing_id.removeprefix("tok_")

        def reset_legacy_digest():
            if has_digest:
                conn.execute("UPDATE tokens SET token_digest = NULL WHERE id = ?", (LEGACY_ID,))
                conn.commit()

        def reset_all_digests():
            if has_digest:
                conn.execute("UPDATE tokens SET token_digest = NULL")
                conn.commit()

        # (label, plaintext, before-hook, digest-only?) — order matters: the
        # steady-state rows run after the legacy row has been backfilled.
        scenarios = [
            ("new-shape valid", minted[3][1], None, True),
            ("legacy, first resolve (pays the scan)", legacy, reset_legacy_digest, False),
            ("legacy, repeat resolve", legacy, None, True),
            ("unknown legacy-shape bearer", "mk_usr_" + secrets.token_urlsafe(32), None, True),
            ("forged: existing id, wrong secret", f"mk_usr_{short_id}_{secrets.token_urlsafe(32)}", None, True),
            ("forged: unknown id", "mk_usr_deadbeefdeadbeef_" + secrets.token_urlsafe(32), None, True),
            ("revoked token", revoked, None, True),
            ("unknown bearer, deploy moment (no digests yet)", "mk_usr_" + secrets.token_urlsafe(32), reset_all_digests, False),
        ]

        print(f"digest column present: {has_digest}; {ITERATIONS} cache-cold resolves each")
        print(f"{'scenario':<50} {'median CPU-s':>12} {'argon2':>6} {'per 50 s bank':>13} {'wall @6.25%':>11}")
        failures = []
        for label, plaintext, before, digest_only in scenarios:
            cpu, verifies = _measure(conn, plaintext, before)
            per_bank = BURST_BALANCE_S / cpu if cpu > 0 else float("inf")
            print(
                f"{label:<50} {cpu:>12.5f} {verifies:>6} {per_bank:>13.0f} "
                f"{cpu / BASELINE_SHARE:>10.3f}s"
            )
            if digest_only and (verifies > 0 or cpu > CPU_BOUND_S):
                failures.append(label)
        conn.close()

    if failures:
        print("\nFAIL (expected on main): not digest-only: " + "; ".join(failures))
        return 1
    print("\nOK: every digest-only path made 0 Argon2 verifies under the CPU bound")
    return 0


if __name__ == "__main__":
    sys.exit(main())
