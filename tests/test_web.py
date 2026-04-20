"""Tests for the web viewer."""

import pytest
from fastapi.testclient import TestClient

from markland.db import init_db, insert_document
from markland.web.app import create_app


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    insert_document(
        conn,
        "doc1",
        "Test Document",
        "# Hello\n\nThis is a test document.",
        "abc123token",
    )
    app = create_app(conn)
    return TestClient(app)


def test_view_by_token(client):
    response = client.get("/d/abc123token")
    assert response.status_code == 200
    assert "Test Document" in response.text
    assert "Hello" in response.text
    assert "Markland" in response.text


def test_view_nonexistent_token_returns_404(client):
    response = client.get("/d/nonexistent")
    assert response.status_code == 404


def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_returns_something(client):
    # Root should at least not 500
    response = client.get("/")
    assert response.status_code in (200, 404)


@pytest.fixture
def client_with_public_docs(tmp_path):
    from markland.db import init_db, insert_document, set_featured
    from markland.web.app import create_app
    db_path = tmp_path / "test.db"
    conn = init_db(db_path)
    # 1 private doc, 2 public docs (one featured)
    insert_document(conn, "priv", "Private Doc", "Secret.", "priv-token", is_public=False)
    insert_document(conn, "pub1", "Public First", "Body for first public doc.", "pub1-token", is_public=True)
    insert_document(conn, "pub2", "Python Guide", "A guide to Python for agents.", "pub2-token", is_public=True)
    set_featured(conn, "pub1", is_featured=True)
    app = create_app(conn)
    return TestClient(app)


def test_landing_renders_empty(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Shared documents" in response.text
    assert "For you <em>and</em> your agents" in response.text
    assert "period-red" in response.text
    assert "period-blue" in response.text
    assert "Nothing yet." in response.text


def test_landing_has_geo_definitional_paragraph(client):
    r = client.get("/")
    text = r.text
    # LLM-friendly definitional sentence — single declarative statement
    # with the product category + primary use case.
    assert "Markland is an MCP-based document publishing platform" in text
    assert "Claude Code" in text


def test_landing_hero_has_waitlist_form(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'action="/api/waitlist"' in response.text
    assert ">Get started<" in response.text
    assert 'name="source"' in response.text
    assert 'value="hero"' in response.text


def test_landing_signup_ok_renders_success_chip(client):
    response = client.get("/?signup=ok")
    assert response.status_code == 200
    assert "You&#39;re on the list" in response.text or "You're on the list" in response.text


def test_landing_signup_invalid_renders_error_chip(client):
    response = client.get("/?signup=invalid")
    assert response.status_code == 200
    assert "That doesn&#39;t look like a valid email" in response.text or "That doesn't look like a valid email" in response.text


def test_landing_no_signup_param_no_chip(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "You're on the list" not in response.text
    assert "That doesn't look like a valid email" not in response.text


def test_landing_has_before_after_section(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "The old way vs. Markland" in response.text
    assert "Stop copy-pasting your agent" in response.text
    assert "~2 min of manual work" in response.text
    assert "~3 seconds" in response.text
    assert 'href="#how-it-works"' in response.text


def test_landing_has_how_it_works_section(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="how-it-works"' in response.text
    assert "How it works" in response.text
    assert "One MCP call. One link." in response.text
    assert ">Published<" in response.text
    assert "2,340 words" in response.text


def test_landing_has_get_early_access_section(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Get early access" in response.text
    assert "Be the first to publish" in response.text
    assert response.text.count('action="/api/waitlist"') >= 2
    assert 'value="cta-section"' in response.text
    assert response.text.count(">Get started<") >= 2


def test_landing_escapes_title_xss(tmp_path):
    """Jinja autoescape must prevent script injection via doc titles on the landing."""
    from markland.db import init_db, insert_document, set_featured
    from markland.web.app import create_app
    db_path = tmp_path / "xss.db"
    conn = init_db(db_path)
    insert_document(conn, "xss", "<script>alert(1)</script>", "body", "xss-tok", is_public=True)
    set_featured(conn, "xss", is_featured=True)
    client = TestClient(create_app(conn))
    response = client.get("/")
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


def test_explore_escapes_title_xss(tmp_path):
    """Jinja autoescape must prevent script injection via doc titles on explore."""
    from markland.db import init_db, insert_document
    from markland.web.app import create_app
    db_path = tmp_path / "xss.db"
    conn = init_db(db_path)
    insert_document(conn, "xss", "<script>alert(2)</script>", "body", "xss-tok", is_public=True)
    client = TestClient(create_app(conn))
    response = client.get("/explore")
    assert "<script>alert(2)</script>" not in response.text
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in response.text


def test_landing_shows_public_docs_with_featured_first(client_with_public_docs):
    response = client_with_public_docs.get("/")
    assert response.status_code == 200
    assert "Public First" in response.text
    assert "Python Guide" in response.text
    # Featured should render the Pinned badge
    assert "Pinned" in response.text
    # Private doc must NOT appear
    assert "Private Doc" not in response.text
    # Featured doc should appear before the non-featured one
    assert response.text.index("Public First") < response.text.index("Python Guide")


def test_explore_empty_shows_empty_state(client):
    response = client.get("/explore")
    assert response.status_code == 200
    assert "Nothing here yet" in response.text


def test_explore_lists_public_docs_only(client_with_public_docs):
    response = client_with_public_docs.get("/explore")
    assert response.status_code == 200
    assert "Public First" in response.text
    assert "Python Guide" in response.text
    assert "Private Doc" not in response.text


def test_explore_search_filters(client_with_public_docs):
    response = client_with_public_docs.get("/explore?q=Python")
    assert response.status_code == 200
    assert "Python Guide" in response.text
    assert "Public First" not in response.text


def test_explore_search_empty_shows_search_empty_state(client_with_public_docs):
    response = client_with_public_docs.get("/explore?q=zzznomatches")
    assert response.status_code == 200
    assert "No docs matched" in response.text


def test_waitlist_post_happy_path(client):
    response = client.post(
        "/api/waitlist",
        data={"email": "ada@example.com", "source": "hero"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?signup=ok"


def test_waitlist_post_invalid_email_redirects_to_invalid(client):
    response = client.post(
        "/api/waitlist",
        data={"email": "not-an-email", "source": "hero"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?signup=invalid"


def test_waitlist_post_duplicate_still_redirects_to_ok(client):
    client.post("/api/waitlist", data={"email": "ada@example.com"}, follow_redirects=False)
    response = client.post(
        "/api/waitlist",
        data={"email": "ada@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?signup=ok"


def test_waitlist_post_missing_email_returns_422(client):
    response = client.post("/api/waitlist", data={}, follow_redirects=False)
    assert response.status_code == 422


def test_waitlist_post_lowercases_and_strips_email(client):
    response = client.post(
        "/api/waitlist",
        data={"email": "  Ada@Example.COM  "},
        follow_redirects=False,
    )
    assert response.status_code == 303
    second = client.post(
        "/api/waitlist",
        data={"email": "ada@example.com"},
        follow_redirects=False,
    )
    assert second.status_code == 303
    assert second.headers["location"] == "/?signup=ok"


def test_landing_passes_signup_param_to_template(client):
    response = client.get("/?signup=ok")
    assert response.status_code == 200
    assert "signup=ok" not in response.text


def test_landing_signup_param_is_whitelisted(client):
    response = client.get("/?signup=xyz")
    assert response.status_code == 200
    assert "xyz" not in response.text


def test_landing_gallery_caps_at_four(tmp_path):
    db_path = tmp_path / "cap.db"
    conn = init_db(db_path)
    for i in range(6):
        insert_document(
            conn,
            doc_id=f"d{i}",
            title=f"Doc {i}",
            content=f"Body {i}",
            share_token=f"tok{i}",
            is_public=True,
        )
    app = create_app(conn)
    tc = TestClient(app)

    response = tc.get("/")
    assert response.status_code == 200
    visible = sum(1 for i in range(6) if f"Doc {i}" in response.text)
    assert visible == 4


def test_share_dialog_shown_for_owner_only(tmp_path):
    from unittest.mock import MagicMock
    from fastapi.testclient import TestClient
    from markland.db import init_db
    from markland.service import docs as docs_svc
    from markland.service.auth import Principal
    from markland.web.app import create_app

    conn = init_db(tmp_path / "t.db")
    conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES ('usr_alice', 'a@x', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO users (id, email, created_at) VALUES ('usr_eve', 'e@x', '2026-01-01')"
    )
    conn.commit()
    alice = Principal(
        principal_id="usr_alice", principal_type="user",
        display_name=None, is_admin=False, user_id="usr_alice",
    )
    stranger = Principal(
        principal_id="usr_eve", principal_type="user",
        display_name=None, is_admin=False, user_id="usr_eve",
    )

    app = create_app(
        conn, mount_mcp=False, base_url="https://markland.test",
        session_secret="t", email_client=MagicMock(),
        test_principal_by_token={"alice": alice, "eve": stranger},
    )
    c = TestClient(app)

    pub = docs_svc.publish(
        conn, "https://markland.test", alice, "body", title="T", public=True
    )
    share_token = pub["share_url"].rsplit("/", 1)[-1]

    # Owner sees the share dialog
    r_owner = c.get(f"/d/{share_token}", headers={"Authorization": "Bearer alice"})
    assert r_owner.status_code == 200
    assert 'id="share-dialog"' in r_owner.text

    # Stranger (public doc) can view but dialog is hidden
    r_eve = c.get(f"/d/{share_token}", headers={"Authorization": "Bearer eve"})
    assert r_eve.status_code == 200
    assert 'id="share-dialog"' not in r_eve.text

    # Anonymous (public doc) also no dialog
    r_anon = c.get(f"/d/{share_token}")
    assert r_anon.status_code == 200
    assert 'id="share-dialog"' not in r_anon.text


def test_alternatives_hub_lists_competitors(client):
    r = client.get("/alternatives")
    assert r.status_code == 200
    assert "Markland vs Markshare.to" in r.text
    assert "Markland vs GitHub" in r.text
    assert "Markland vs Google Docs" in r.text
    assert "Markland vs Notion" in r.text


def test_alternatives_hub_has_summary_and_cta(client):
    r = client.get("/alternatives")
    assert r.status_code == 200
    assert "hosted markdown publishing service" in r.text
    assert "Join the waitlist" in r.text


def test_alternative_page_renders_markshare(client):
    r = client.get("/alternatives/markshare")
    assert r.status_code == 200
    assert "Markland vs Markshare.to" in r.text
    assert "MCP-native vs CLI" in r.text
    assert "Pick Markshare.to when" in r.text
    assert "Pick Markland when" in r.text


def test_alternative_page_renders_github(client):
    r = client.get("/alternatives/github")
    assert r.status_code == 200
    assert "Sharing unit mismatch" in r.text
    assert "Code-review chrome bounces readers" in r.text


def test_alternative_page_unknown_slug_returns_404(client):
    r = client.get("/alternatives/bogus")
    assert r.status_code == 404
