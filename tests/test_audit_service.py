"""Tests for the audit-log table and service."""

import json
import sqlite3

import pytest

from markland.db import init_db


@pytest.fixture
def conn(tmp_path) -> sqlite3.Connection:
    return init_db(tmp_path / "test.db")


def test_audit_log_table_exists(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
    ).fetchone()
    assert row is not None


def test_audit_log_columns(conn: sqlite3.Connection) -> None:
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert cols["id"].upper() == "INTEGER"
    assert cols["doc_id"].upper() == "TEXT"
    assert cols["action"].upper() == "TEXT"
    assert cols["principal_id"].upper() == "TEXT"
    assert cols["principal_type"].upper() == "TEXT"
    assert cols["metadata"].upper() == "TEXT"
    assert cols["created_at"].upper() == "TEXT"


def test_record_audit_inserts_row(conn: sqlite3.Connection) -> None:
    from markland.db import record_audit

    record_audit(
        conn,
        doc_id="doc_1",
        action="publish",
        principal_id="usr_abc",
        principal_type="user",
        metadata={"title": "hello"},
    )
    row = conn.execute(
        "SELECT doc_id, action, principal_id, principal_type, metadata FROM audit_log"
    ).fetchone()
    assert row[0] == "doc_1"
    assert row[1] == "publish"
    assert row[2] == "usr_abc"
    assert row[3] == "user"
    assert json.loads(row[4]) == {"title": "hello"}


def test_record_audit_allows_null_doc_id(conn: sqlite3.Connection) -> None:
    from markland.db import record_audit

    record_audit(
        conn,
        doc_id=None,
        action="invite_accept",
        principal_id="usr_xyz",
        principal_type="user",
        metadata=None,
    )
    row = conn.execute("SELECT doc_id, metadata FROM audit_log").fetchone()
    assert row[0] is None
    assert row[1] == "{}"


from markland.service.auth import Principal


def _principal(kind: str = "user") -> Principal:
    return Principal(
        principal_id="usr_a" if kind == "user" else "agt_a",
        principal_type=kind,  # type: ignore[arg-type]
        display_name="Alice",
        is_admin=False,
        user_id="usr_a" if kind == "user" else None,
    )


def test_service_record_writes_row(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    audit.record(
        conn,
        action="publish",
        principal=_principal(),
        doc_id="doc_1",
        metadata={"title": "hi"},
    )
    row = conn.execute(
        "SELECT action, principal_id, principal_type FROM audit_log"
    ).fetchone()
    assert row == ("publish", "usr_a", "user")


def test_service_record_swallows_exceptions(conn: sqlite3.Connection, caplog) -> None:
    from markland.service import audit

    conn.close()  # force any write to raise
    # Must not raise; must log.
    audit.record(
        conn,
        action="publish",
        principal=_principal(),
        doc_id="doc_1",
    )
    assert any("audit" in r.message.lower() for r in caplog.records)


def test_service_list_recent_orders_by_created_at_desc(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    for i in range(3):
        audit.record(
            conn,
            action="publish",
            principal=_principal(),
            doc_id=f"doc_{i}",
            metadata={"i": i},
        )
    rows = audit.list_recent(conn, limit=10)
    assert [r["doc_id"] for r in rows] == ["doc_2", "doc_1", "doc_0"]
    assert rows[0]["metadata"] == {"i": 2}


def test_service_list_recent_filters_by_doc_id(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    audit.record(conn, action="publish", principal=_principal(), doc_id="doc_1")
    audit.record(conn, action="publish", principal=_principal(), doc_id="doc_2")
    rows = audit.list_recent(conn, doc_id="doc_1", limit=10)
    assert len(rows) == 1
    assert rows[0]["doc_id"] == "doc_1"


def test_service_list_recent_honors_limit(conn: sqlite3.Connection) -> None:
    from markland.service import audit

    for i in range(5):
        audit.record(conn, action="publish", principal=_principal(), doc_id=f"doc_{i}")
    rows = audit.list_recent(conn, limit=2)
    assert len(rows) == 2
