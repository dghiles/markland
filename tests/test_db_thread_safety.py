"""The shared connection from init_db() is used from the event-loop thread
(middleware, async routes, presence GC) and from threadpool threads (sync MCP
tools, sync routes) at the same time. These tests pin down that such use is
serialised: statements never interleave on the connection, and a thread's
open transaction is never joined, committed or rolled back by another thread.
"""

from __future__ import annotations

import asyncio
import collections
import sqlite3
import threading

import anyio.to_thread
import pytest

from markland import db
from markland.service import docs as docs_svc
from markland.service.auth import Principal

OWNER = Principal(
    principal_id="usr_owner",
    principal_type="user",
    display_name="Owner",
    is_admin=False,
    user_id=None,
)


@pytest.fixture
def conn(tmp_path):
    c = db.init_db(tmp_path / "t.db")
    yield c
    c.close()


def _waitlist(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT email FROM waitlist").fetchall()}


def test_another_thread_cannot_write_into_an_open_transaction(conn):
    """Thread A opens a transaction; thread B's INSERT+commit must wait for it
    rather than land inside it and commit A's work out from under A."""
    b_started = threading.Event()
    b_done = threading.Event()
    b_errors: list[BaseException] = []

    def thread_b():
        b_started.set()
        try:
            db.add_waitlist_email(conn, "b@example.com")
        except BaseException as exc:  # pragma: no cover - reported below
            b_errors.append(exc)
        finally:
            b_done.set()

    conn.execute("BEGIN IMMEDIATE")
    conn.execute(
        "INSERT INTO waitlist (email, created_at) VALUES ('a@example.com', 'now')"
    )
    t = threading.Thread(target=thread_b)
    t.start()
    assert b_started.wait(5)
    finished_during_a = b_done.wait(0.5)
    conn.execute("ROLLBACK")  # raises on unserialised code: B committed A's txn
    t.join(5)

    assert not t.is_alive()
    assert b_errors == []
    assert not finished_during_a, "thread B ran inside thread A's transaction"
    assert _waitlist(conn) == {"b@example.com"}


def _seed_doc(conn) -> None:
    conn.execute(
        "INSERT INTO users (id, email, display_name, is_admin, created_at) "
        "VALUES (?, 'owner@example.com', 'Owner', 0, 'now')",
        (OWNER.principal_id,),
    )
    conn.commit()
    db.insert_document(conn, "doc1", "T", "v0", "share1", owner_id=OWNER.principal_id)


def test_concurrent_use_from_event_loop_and_threadpool(conn):
    """Mixed service-level work from the loop thread and anyio worker threads
    (how Starlette/FastMCP run sync handlers) must neither raise nor corrupt
    results. Unserialised, this produces InterfaceError, 'cannot start a
    transaction within a transaction', rows of the wrong shape and lost writes."""
    _seed_doc(conn)
    iterations = 150
    errors: collections.Counter[str] = collections.Counter()
    updates_applied = 0
    lock = threading.Lock()

    def note(exc: BaseException) -> None:
        with lock:
            errors[f"{type(exc).__name__}: {exc}"[:120]] += 1

    def writer(i: int) -> None:
        for j in range(iterations):
            try:
                assert db.add_waitlist_email(conn, f"w{i}-{j}@example.com") is True
            except BaseException as exc:
                note(exc)

    def updater() -> None:
        nonlocal updates_applied
        for j in range(iterations):
            try:
                current = db.get_document(conn, "doc1")
                docs_svc.update(
                    conn, "doc1", OWNER, content=f"u{j}", if_version=current.version
                )
                with lock:
                    updates_applied += 1
            except docs_svc.ConflictError:
                pass
            except BaseException as exc:
                note(exc)

    def reader() -> None:
        for _ in range(iterations):
            try:
                doc = db.get_document(conn, "doc1")
                assert doc is not None and doc.id == "doc1", doc
                (count,) = conn.execute("SELECT COUNT(*) FROM waitlist").fetchone()
                assert isinstance(count, int), count
            except BaseException as exc:
                note(exc)

    async def loop_worker(i: int) -> None:
        # Middleware-shaped work on the event-loop thread: read, write, commit.
        for j in range(iterations):
            try:
                assert db.get_document(conn, "doc1").id == "doc1"
                assert db.add_waitlist_email(conn, f"l{i}-{j}@example.com") is True
            except BaseException as exc:
                note(exc)
            await asyncio.sleep(0)

    async def main() -> None:
        jobs = [anyio.to_thread.run_sync(writer, i) for i in range(2)]
        jobs += [anyio.to_thread.run_sync(updater) for _ in range(2)]
        jobs += [anyio.to_thread.run_sync(reader) for _ in range(2)]
        jobs += [loop_worker(i) for i in range(2)]
        await asyncio.gather(*jobs)

    asyncio.run(main())

    assert dict(errors) == {}
    assert len(_waitlist(conn)) == 4 * iterations
    doc = db.get_document(conn, "doc1")
    assert doc.version == 1 + updates_applied
    (revisions,) = conn.execute(
        "SELECT COUNT(*) FROM revisions WHERE doc_id = 'doc1'"
    ).fetchone()
    assert revisions == min(updates_applied, docs_svc.MAX_REVISIONS_PER_DOC)


def test_failed_statement_does_not_leave_its_transaction_open(conn):
    """A write that fails (and is swallowed, as _build_principal_and_touch
    does) must not leave an open transaction that blocks other threads."""
    db.add_waitlist_email(conn, "dup@example.com")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO waitlist (email, created_at) VALUES ('dup@example.com', 'x')"
        )
    assert not conn.in_transaction

    t = threading.Thread(target=db.add_waitlist_email, args=(conn, "other@example.com"))
    t.start()
    t.join(5)
    assert not t.is_alive()
    assert _waitlist(conn) == {"dup@example.com", "other@example.com"}


def test_failed_statement_inside_a_transaction_keeps_it_open(conn):
    """Only a transaction the failing statement itself opened is rolled back;
    earlier work in a caller's transaction stays for the caller to settle."""
    db.add_waitlist_email(conn, "dup@example.com")
    conn.execute(
        "INSERT INTO waitlist (email, created_at) VALUES ('keep@example.com', 'x')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO waitlist (email, created_at) VALUES ('dup@example.com', 'x')"
        )
    assert conn.in_transaction
    conn.commit()
    assert _waitlist(conn) == {"dup@example.com", "keep@example.com"}


def test_transaction_left_open_by_a_dead_thread_is_rolled_back(conn):
    def abandon() -> None:
        conn.execute(
            "INSERT INTO waitlist (email, created_at) VALUES ('ghost@example.com', 'x')"
        )  # no commit, and the thread exits

    t = threading.Thread(target=abandon)
    t.start()
    t.join(5)

    db.add_waitlist_email(conn, "live@example.com")
    assert _waitlist(conn) == {"live@example.com"}


def test_waiting_on_a_live_open_transaction_times_out_as_database_locked(conn):
    conn.lock_timeout = 0.2
    opened = threading.Event()
    release = threading.Event()

    def hold() -> None:
        conn.execute(
            "INSERT INTO waitlist (email, created_at) VALUES ('held@example.com', 'x')"
        )
        opened.set()
        release.wait(5)
        conn.commit()

    t = threading.Thread(target=hold)
    t.start()
    assert opened.wait(5)
    try:
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            conn.execute("SELECT 1")
    finally:
        release.set()
        t.join(5)
    assert _waitlist(conn) == {"held@example.com"}


def test_execute_returns_a_fully_fetched_cursor(conn):
    insert = conn.execute(
        "INSERT INTO waitlist (email, created_at) VALUES ('a@example.com', 'x')"
    )
    assert insert.rowcount == 1
    assert isinstance(insert.lastrowid, int)
    assert insert.description is None
    assert insert.fetchone() is None
    conn.execute(
        "INSERT INTO waitlist (email, created_at) VALUES ('b@example.com', 'y')"
    )
    conn.commit()

    cur = conn.execute("SELECT email, created_at FROM waitlist ORDER BY email")
    assert [d[0] for d in cur.description] == ["email", "created_at"]
    assert cur.rowcount == -1
    assert cur.fetchone() == ("a@example.com", "x")
    assert cur.fetchall() == [("b@example.com", "y")]
    assert cur.fetchone() is None
    assert list(conn.execute("SELECT email FROM waitlist ORDER BY email")) == [
        ("a@example.com",),
        ("b@example.com",),
    ]
    assert conn.execute("SELECT email FROM waitlist ORDER BY email").fetchmany(1) == [
        ("a@example.com",)
    ]
    deleted = conn.execute("DELETE FROM waitlist")
    assert deleted.rowcount == 2
    conn.commit()
