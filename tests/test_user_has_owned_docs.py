"""service/docs.py::user_has_owned_docs — used by the dashboard
welcome panel visibility logic. Plan: docs/plans/2026-05-29-pre-launch-cleanup.md
Track D Task D1 (bead markland-2l0)."""

from __future__ import annotations

from markland.db import init_db, upsert_grant
from markland.service import docs as svc
from markland.service.auth import Principal


BASE = "https://markland.test"


def _user(uid: str) -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


def test_user_has_owned_docs_false_for_new_user(tmp_path):
    conn = init_db(tmp_path / "t.db")
    assert svc.user_has_owned_docs(conn, "usr_alice") is False


def test_user_has_owned_docs_true_after_publish(tmp_path):
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    svc.publish(conn, BASE, alice, "body", title="T", public=False)
    assert svc.user_has_owned_docs(conn, "usr_alice") is True


def test_user_has_owned_docs_false_for_user_with_only_grants(tmp_path):
    """A grant on someone else's doc doesn't count as 'owned'."""
    conn = init_db(tmp_path / "t.db")
    alice = _user("usr_alice")
    bob_id = "usr_bob"
    doc_id = svc.publish(conn, BASE, alice, "body", title="T", public=False)["id"]
    upsert_grant(conn, doc_id, bob_id, "user", "view", "usr_alice")
    assert svc.user_has_owned_docs(conn, bob_id) is False
