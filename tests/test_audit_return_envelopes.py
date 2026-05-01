"""Layer C — axis 2: return envelopes."""

import pytest
from markland._mcp_envelopes import doc_envelope, doc_summary, list_envelope


def test_doc_envelope_required_fields():
    raw = {
        "id": "doc_a", "title": "T", "content": "x", "version": 1,
        "owner_id": "usr_b", "share_url": "http://x/d/abc",
        "is_public": False, "is_featured": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    env = doc_envelope(raw)
    assert set(env) >= {
        "id", "title", "content", "version", "owner_id", "share_url",
        "is_public", "is_featured", "created_at", "updated_at",
    }


def test_doc_envelope_with_active_principals():
    raw = {
        "id": "doc_a", "title": "T", "content": "x", "version": 1,
        "owner_id": "usr_b", "share_url": "http://x/d/abc",
        "is_public": False, "is_featured": False,
        "created_at": "x", "updated_at": "x",
    }
    actives = [{"principal_id": "usr_c", "status": "editing"}]
    env = doc_envelope(raw, active_principals=actives)
    assert env["active_principals"] == actives


def test_doc_summary_excludes_content():
    env = doc_summary({
        "id": "doc_a", "title": "T", "content": "should_not_appear",
        "owner_id": "usr_b", "is_public": False, "is_featured": False,
        "created_at": "x", "updated_at": "x",
    })
    assert "content" not in env
    assert env["title"] == "T"


def test_list_envelope_shape():
    env = list_envelope(items=[{"id": "doc_a"}, {"id": "doc_b"}], next_cursor="abc")
    assert env == {"items": [{"id": "doc_a"}, {"id": "doc_b"}], "next_cursor": "abc"}


def test_list_envelope_no_more_pages():
    env = list_envelope(items=[{"id": "doc_a"}], next_cursor=None)
    assert env["next_cursor"] is None


from markland._mcp_envelopes import encode_cursor, decode_cursor


def test_cursor_round_trip():
    enc = encode_cursor(last_id="doc_abc", last_updated_at="2026-04-27T03:00:00Z")
    assert decode_cursor(enc) == ("doc_abc", "2026-04-27T03:00:00Z")


def test_decode_malformed_cursor_raises():
    with pytest.raises(ValueError, match="malformed cursor"):
        decode_cursor("@@@@@@")
