"""End-to-end: two MCP 'agents' racing on the same document."""

import pytest

from markland.db import init_db, upsert_grant
from markland.service import docs as svc
from markland.service.auth import Principal
from markland.service.docs import ConflictError, get, update
from markland.tools.documents import publish_doc


def _P(pid: str) -> Principal:
    return Principal(
        principal_id=pid,
        principal_type="user",
        display_name=None,
        is_admin=True,
        user_id=pid,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "e2e.db")
    yield c
    c.close()


def test_two_agents_race_then_reconcile(conn):
    a = _P("agent_a")
    b = _P("agent_b")

    # Seed the doc as agent_a (so a is owner) then grant b edit access.
    pub = svc.publish(conn, "http://x", a, "v1", title="T", public=False)
    doc_id = pub["id"]
    # Grant b edit (direct grant via db helper).
    upsert_grant(conn, doc_id, b.principal_id, "user", "edit", a.principal_id)

    # Warm-up: bump to version 3.
    update(conn, doc_id, a, content="v2", if_version=1)
    update(conn, doc_id, a, content="v3", if_version=2)

    # A reads at version 3.
    a_snapshot = get(conn, doc_id, a)
    assert a_snapshot.version == 3
    a_saw_content = a_snapshot.content  # "v3"

    # B reads, writes, bumps to version 4.
    b_snapshot = get(conn, doc_id, b)
    assert b_snapshot.version == 3
    update(conn, doc_id, b, content="v4-from-b", if_version=3)

    # A tries to write with its stale if_version=3 → conflict.
    with pytest.raises(ConflictError) as ei:
        update(conn, doc_id, a, content="v4-from-a", if_version=3)
    err = ei.value
    assert err.current_version == 4
    assert err.current_content == "v4-from-b"

    # A merges and retries.
    a_merged = err.current_content + "\n\n[from A on top of " + a_saw_content + "]"
    final = update(conn, doc_id, a, content=a_merged, if_version=err.current_version)
    assert final.version == 5
    assert "v4-from-b" in final.content
    assert "[from A on top of v3]" in final.content


def test_fifty_five_writes_prune_revisions_to_fifty(conn):
    from markland.db import count_revisions

    a = _P("agent_a")
    pub = svc.publish(conn, "http://x", a, "v1", title="T", public=False)
    doc_id = pub["id"]
    for i in range(55):
        update(conn, doc_id, a, content=f"body-{i}", if_version=i + 1)
    assert count_revisions(conn, doc_id) == 50
    final = get(conn, doc_id, a)
    assert final.version == 56
    assert final.content == "body-54"
