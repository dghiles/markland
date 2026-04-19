"""Tests that the presence GC task runs during the FastAPI lifespan."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db
from markland.web import presence_gc
from markland.web.app import create_app


def _seed_doc(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        INSERT INTO documents (id, title, content, share_token, created_at, updated_at, is_public, is_featured, version)
        VALUES ('doc_1', 'T', 'C', 'tok_1', '2026-04-19T00:00:00', '2026-04-19T00:00:00', 0, 0, 1)
        """
    )
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES ('usr_alice', 'a@x', 'Alice', 0, '2026-04-19T00:00:00')"
    )
    conn.commit()


def test_gc_task_registered_and_cancelled(tmp_path):
    conn = init_db(tmp_path / "t.db")
    app = create_app(conn, enable_presence_gc=True, gc_interval_seconds=0.05)

    # Before the lifespan fires, the attr exists but task is None.
    assert getattr(app.state, "presence_gc_task", None) is None

    with TestClient(app) as client:
        task = app.state.presence_gc_task
        assert isinstance(task, asyncio.Task)
        assert not task.done()
        assert client.get("/health").status_code == 200

    # After the context exits, the task has been cancelled or completed.
    assert app.state.presence_gc_task.cancelled() or app.state.presence_gc_task.done()


def test_gc_task_actually_deletes_expired_rows(tmp_path):
    """End-to-end: seed an expired row, let the loop tick, confirm deletion."""
    conn = init_db(tmp_path / "t.db")
    _seed_doc(conn)

    # Manually insert a row that is ALREADY expired so we don't have to wait 10 min.
    past = "2020-01-01T00:00:00"
    conn.execute(
        """
        INSERT INTO presence (doc_id, principal_id, principal_type, status, note, updated_at, expires_at)
        VALUES ('doc_1', 'usr_alice', 'user', 'reading', NULL, ?, ?)
        """,
        (past, past),
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0] == 1

    app = create_app(conn, enable_presence_gc=True, gc_interval_seconds=0.05)
    with TestClient(app):
        import time
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0] == 0:
                break
            time.sleep(0.05)
    assert conn.execute("SELECT COUNT(*) FROM presence").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_gc_loop_swallows_exceptions_and_continues():
    """A failing gc_expired call must not kill the loop."""
    calls: list[int] = []

    def _bad():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("simulated DB hiccup")
        return 0

    stop = asyncio.Event()

    async def _run():
        await presence_gc._loop(_bad, interval_seconds=0.01, stop_event=stop)

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.1)
    stop.set()
    await task
    # Despite the first call raising, the loop kept ticking.
    assert len(calls) >= 2
