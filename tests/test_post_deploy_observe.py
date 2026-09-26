"""Tests for .github/scripts/post-deploy-observe.sh (deploy.yml observe step).

The script decides whether a production deploy job goes red, so the
contract is pinned here against a local stub server (never markland.dev):
fail only on a sustained health failure, never on a CPU-balance dip or
throttling alone, and never let the metrics API fail the job.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "post-deploy-observe.sh"
RUNBOOK = "docs/runbooks/post-deploy-cpu-throttle.md"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("bash", "curl", "jq")),
    reason="needs bash, curl and jq (all present on ubuntu-latest)",
)


class Stub:
    """Scripted /health statuses plus a canned Prometheus query endpoint."""

    def __init__(self, health, balance_ticks="5000", throttle_ticks="0", prom_status=200):
        self.health = list(health)
        self.balance_ticks = balance_ticks
        self.throttle_ticks = throttle_ticks
        self.prom_status = prom_status
        self.health_hits = 0
        self.auth_headers: list[str] = []

    def __enter__(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, status, body=b""):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                stub.health_hits += 1
                status = stub.health.pop(0) if len(stub.health) > 1 else stub.health[0]
                self._send(status, b"ok")

            def do_POST(self):
                stub.auth_headers.append(self.headers.get("Authorization", ""))
                length = int(self.headers.get("Content-Length", "0"))
                query = parse_qs(self.rfile.read(length).decode())["query"][0]
                if stub.prom_status != 200:
                    self._send(stub.prom_status, b"unauthorized")
                    return
                value = stub.balance_ticks if "cpu_balance" in query else stub.throttle_ticks
                body = {
                    "status": "success",
                    "data": {"resultType": "vector", "result": [{"metric": {}, "value": [0, value]}]},
                }
                self._send(200, json.dumps(body).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.health_url = f"{base}/health"
        self.prom_url = f"{base}/prom"
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


def run(health_url, prom_url=None, token="fm2_test", **overrides):
    env = {
        "PATH": os.environ["PATH"],
        "HEALTH_URL": health_url,
        "PROM_URL": prom_url or "http://127.0.0.1:9/prom",
        "CHECKS": "5",
        "INTERVAL_SECONDS": "0",
        "FAIL_AFTER": "3",
        "BOOT_GRACE_SECONDS": "0",
        "HEALTH_TIMEOUT": "2",
    }
    if token is not None:
        env["FLY_API_TOKEN"] = token
    env.update({k: str(v) for k, v in overrides.items()})
    proc = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_healthy_run_passes_and_reports_metrics_in_cpu_seconds(tmp_path):
    summary = tmp_path / "summary.md"
    with Stub([200], balance_ticks="5000", throttle_ticks="0") as s:
        rc, out = run(s.health_url, s.prom_url, GITHUB_STEP_SUMMARY=summary)
    assert rc == 0, out
    assert s.health_hits == 5
    assert "50.0" in out  # 5000 centiseconds -> 50.0 CPU-s
    assert "::error" not in out
    assert "50.0" in summary.read_text()


def test_sustained_health_failure_fails_fast_and_points_at_runbook():
    with Stub([503]) as s:
        rc, out = run(s.health_url, s.prom_url, CHECKS=10)
    assert rc == 1, out
    assert s.health_hits == 3  # stops at FAIL_AFTER, does not wait out the window
    assert "::error" in out
    assert RUNBOOK in out
    assert "roll back" in out.lower()  # tells the operator it did NOT roll back


def test_unreachable_health_url_fails():
    rc, out = run("http://127.0.0.1:9/health", token=None)
    assert rc == 1, out
    assert RUNBOOK in out


def test_intermittent_failures_warn_but_pass():
    with Stub([503, 200, 503, 200, 503, 200]) as s:
        rc, out = run(s.health_url, s.prom_url, CHECKS=6)
    assert rc == 0, out
    assert "::warning" in out


def test_balance_dip_and_throttling_alone_warn_but_pass():
    with Stub([200], balance_ticks="0", throttle_ticks="50") as s:
        rc, out = run(s.health_url, s.prom_url)
    assert rc == 0, out
    assert "::warning" in out
    assert "throttl" in out.lower()


def test_failures_during_boot_grace_are_not_counted():
    with Stub([503, 503, 503, 503, 200]) as s:
        rc, out = run(s.health_url, s.prom_url, BOOT_GRACE_SECONDS=3600)
    assert rc == 0, out


def test_boot_grace_ends_at_first_success():
    with Stub([503, 200, 503, 503, 503, 200]) as s:
        rc, out = run(s.health_url, s.prom_url, CHECKS=6, BOOT_GRACE_SECONDS=3600)
    assert rc == 1, out


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("fm2_abc", "FlyV1 fm2_abc"),  # macaroon: Fly returns 401 for "Bearer fm2_..."
        ("FlyV1 fm2_abc,fm2_def", "FlyV1 fm2_abc,fm2_def"),  # `fly tokens create` output
        ("legacy123", "Bearer legacy123"),
    ],
)
def test_auth_scheme_matches_token_shape(token, expected):
    with Stub([200]) as s:
        rc, out = run(s.health_url, s.prom_url, token=token, CHECKS=1)
    assert rc == 0, out
    assert s.auth_headers and set(s.auth_headers) == {expected}


def test_metrics_api_error_warns_but_never_fails():
    with Stub([200], prom_status=401) as s:
        rc, out = run(s.health_url, s.prom_url)
    assert rc == 0, out
    assert "HTTP 401" in out


def test_missing_token_skips_metrics():
    with Stub([200]) as s:
        rc, out = run(s.health_url, s.prom_url, token=None)
    assert rc == 0, out
    assert s.auth_headers == []
