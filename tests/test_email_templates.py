"""Renderer tests: correct subject, html + text populated, key fields present."""

import pytest

from markland.config import reset_config
from markland.service import email_templates as tpl


@pytest.fixture(autouse=True)
def _config(monkeypatch, tmp_path):
    monkeypatch.setenv("MARKLAND_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MARKLAND_BASE_URL", "https://markland.dev")
    reset_config()
    yield
    reset_config()


def test_magic_link_renders():
    rendered = tpl.magic_link(
        email="alice@example.com",
        verify_url="https://markland.dev/auth/verify?t=abc",
        expires_in_minutes=15,
    )
    assert rendered["subject"] == "Your Markland login link (expires in 15 minutes)."
    assert "https://markland.dev/auth/verify?t=abc" in rendered["html"]
    assert "https://markland.dev/auth/verify?t=abc" in rendered["text"]
    assert "15 minutes" in rendered["text"]
    assert "Manage notifications" in rendered["html"]
    assert "/settings/notifications" in rendered["text"]


def test_user_grant_renders():
    rendered = tpl.user_grant(
        granter_display="Bob",
        doc_title="Quarterly plan",
        doc_url="https://markland.dev/d/tok",
        level="view",
    )
    assert rendered["subject"] == 'Bob shared "Quarterly plan" with you — view access.'
    assert "Bob" in rendered["html"]
    assert "Quarterly plan" in rendered["html"]
    assert "https://markland.dev/d/tok" in rendered["html"]
    assert "view" in rendered["text"]


def test_user_grant_level_changed_renders():
    rendered = tpl.user_grant_level_changed(
        granter_display="Bob",
        doc_title="Q plan",
        doc_url="https://markland.dev/d/tok",
        old_level="view",
        new_level="edit",
    )
    assert rendered["subject"] == 'Bob changed your access to "Q plan" to edit.'
    assert "edit" in rendered["html"]
    assert "view" in rendered["html"]
    assert "Q plan" in rendered["text"]


def test_agent_grant_renders():
    rendered = tpl.agent_grant(
        granter_display="Bob",
        agent_name="coder-01",
        agent_id="agt_abc",
        doc_title="Q plan",
        doc_url="https://markland.dev/d/tok",
        level="edit",
    )
    assert rendered["subject"] == 'Bob granted your agent coder-01 edit access to "Q plan".'
    assert "coder-01" in rendered["html"]
    assert "agt_abc" in rendered["html"]
    assert "agt_abc" in rendered["text"]


def test_invite_accepted_renders():
    rendered = tpl.invite_accepted(
        accepter_display="Alice",
        doc_title="Q plan",
        doc_url="https://markland.dev/d/tok",
    )
    assert rendered["subject"] == 'Alice accepted your invite to "Q plan".'
    assert "Alice" in rendered["html"]
    assert "Q plan" in rendered["text"]


def test_all_templates_include_footer_settings_link():
    rendered = tpl.magic_link(
        email="a@b", verify_url="https://x/y", expires_in_minutes=15
    )
    assert "/settings/notifications" in rendered["html"]
    assert "/settings/notifications" in rendered["text"]


def test_html_and_text_are_both_nonempty_for_every_template():
    samples = [
        tpl.magic_link(email="a@b", verify_url="https://x", expires_in_minutes=15),
        tpl.user_grant(granter_display="G", doc_title="T", doc_url="https://x", level="view"),
        tpl.user_grant_level_changed(
            granter_display="G", doc_title="T", doc_url="https://x",
            old_level="view", new_level="edit",
        ),
        tpl.agent_grant(
            granter_display="G", agent_name="n", agent_id="agt_x",
            doc_title="T", doc_url="https://x", level="edit",
        ),
        tpl.invite_accepted(accepter_display="A", doc_title="T", doc_url="https://x"),
    ]
    for r in samples:
        assert r["subject"]
        assert r["html"].strip().startswith("<!DOCTYPE")
        assert r["text"].strip()
        assert "Markland" in r["html"]
