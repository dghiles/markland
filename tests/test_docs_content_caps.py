"""P2-D / markland-o1u: storage-DoS caps on doc content + title.

Caps are enforced at the service layer (`docs_svc.publish` and
`docs_svc.update`) so MCP, HTTP, and any future caller share the same
limits. Crossing either limit raises `ContentTooLarge`.
"""

from __future__ import annotations

import pytest

from markland.db import init_db
from markland.service import docs as docs_svc
from markland.service.auth import Principal


def _user(uid: str = "usr_alice") -> Principal:
    return Principal(
        principal_id=uid,
        principal_type="user",
        display_name=None,
        is_admin=False,
        user_id=uid,
    )


@pytest.fixture
def conn(tmp_path):
    c = init_db(tmp_path / "t.db")
    yield c
    c.close()


def test_publish_under_cap_succeeds(conn):
    """Regression: a 999KB content publishes successfully."""
    big = "a" * 999_000  # 999_000 bytes
    raw = docs_svc.publish(
        conn, "http://t", _user(), content=big, title="ok",
    )
    assert raw["id"]


def test_publish_over_cap_raises(conn):
    """1.5MB content must fail with ContentTooLarge."""
    huge = "a" * 1_500_000
    with pytest.raises(docs_svc.ContentTooLarge):
        docs_svc.publish(conn, "http://t", _user(), content=huge, title="bad")


def test_publish_long_title_raises(conn):
    long_title = "x" * 600
    with pytest.raises(docs_svc.ContentTooLarge):
        docs_svc.publish(
            conn, "http://t", _user(), content="hi", title=long_title,
        )


def test_publish_multibyte_content_counted_in_bytes(conn):
    """A char-length cap would let 1MB of 4-byte chars (4MB on disk) past.
    The cap is in bytes — emoji-heavy payloads are bounded the same way."""
    # "🦀" is 4 bytes in UTF-8 → 250_001 of them = 1_000_004 bytes.
    payload = "🦀" * 250_001
    with pytest.raises(docs_svc.ContentTooLarge):
        docs_svc.publish(
            conn, "http://t", _user(), content=payload, title="emoji",
        )


def test_update_over_cap_raises(conn):
    raw = docs_svc.publish(
        conn, "http://t", _user(), content="hi", title="ok",
    )
    huge = "a" * 1_500_000
    with pytest.raises(docs_svc.ContentTooLarge):
        docs_svc.update(
            conn, raw["id"], _user(), content=huge, if_version=1,
        )


def test_update_long_title_raises(conn):
    raw = docs_svc.publish(
        conn, "http://t", _user(), content="hi", title="ok",
    )
    long_title = "x" * 600
    with pytest.raises(docs_svc.ContentTooLarge):
        docs_svc.update(
            conn, raw["id"], _user(), title=long_title, if_version=1,
        )


def test_update_at_boundary_succeeds(conn):
    """Exactly MAX_CONTENT_BYTES UTF-8 bytes is permitted (boundary)."""
    raw = docs_svc.publish(
        conn, "http://t", _user(), content="hi", title="ok",
    )
    boundary = "a" * docs_svc.MAX_CONTENT_BYTES
    doc = docs_svc.update(
        conn, raw["id"], _user(), content=boundary, if_version=1,
    )
    assert len(doc.content) == docs_svc.MAX_CONTENT_BYTES
