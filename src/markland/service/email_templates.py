"""Render transactional email bodies. Each function returns {subject, html, text}.

Subject lines match spec §17 / §7 verbatim. HTML templates extend _layout.html;
text templates stand alone. Every email includes the footer "manage notifications"
link and a one-line "why am I getting this?" explanation.
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from markland.config import get_config

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "email_templates"

_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)


def _render(name: str, **ctx) -> str:
    return _env.get_template(name).render(**ctx)


def _base_ctx(footer_reason: str) -> dict:
    return {
        "base_url": get_config().base_url,
        "footer_reason": footer_reason,
    }


def magic_link(*, email: str, verify_url: str, expires_in_minutes: int = 15) -> dict:
    subject = f"Your Markland login link (expires in {expires_in_minutes} minutes)."
    ctx = {
        **_base_ctx("you requested a sign-in link for this email address."),
        "subject": subject,
        "email": email,
        "verify_url": verify_url,
        "expires_in_minutes": expires_in_minutes,
    }
    return {
        "subject": subject,
        "html": _render("magic_link.html", **ctx),
        "text": _render("magic_link.txt", **ctx),
    }


def user_grant(
    *,
    granter_display: str,
    doc_title: str,
    doc_url: str,
    level: str,
) -> dict:
    subject = f'{granter_display} shared "{doc_title}" with you — {level} access.'
    level_phrase = (
        f"You have {level} access."
        if level == "edit"
        else "You have view access (read-only)."
    )
    ctx = {
        **_base_ctx("someone shared a Markland document with you."),
        "subject": subject,
        "granter_display": granter_display,
        "doc_title": doc_title,
        "doc_url": doc_url,
        "level": level,
        "level_phrase": level_phrase,
    }
    return {
        "subject": subject,
        "html": _render("user_grant.html", **ctx),
        "text": _render("user_grant.txt", **ctx),
    }


def user_grant_level_changed(
    *,
    granter_display: str,
    doc_title: str,
    doc_url: str,
    old_level: str,
    new_level: str,
) -> dict:
    subject = f'{granter_display} changed your access to "{doc_title}" to {new_level}.'
    ctx = {
        **_base_ctx("your access to a shared Markland document changed."),
        "subject": subject,
        "granter_display": granter_display,
        "doc_title": doc_title,
        "doc_url": doc_url,
        "old_level": old_level,
        "new_level": new_level,
    }
    return {
        "subject": subject,
        "html": _render("user_grant_level_changed.html", **ctx),
        "text": _render("user_grant_level_changed.txt", **ctx),
    }


def agent_grant(
    *,
    granter_display: str,
    agent_name: str,
    agent_id: str,
    doc_title: str,
    doc_url: str,
    level: str,
) -> dict:
    subject = (
        f'{granter_display} granted your agent {agent_name} {level} access to "{doc_title}".'
    )
    ctx = {
        **_base_ctx("an agent you own was granted access to a Markland document."),
        "subject": subject,
        "granter_display": granter_display,
        "agent_name": agent_name,
        "agent_id": agent_id,
        "doc_title": doc_title,
        "doc_url": doc_url,
        "level": level,
    }
    return {
        "subject": subject,
        "html": _render("agent_grant.html", **ctx),
        "text": _render("agent_grant.txt", **ctx),
    }


def invite_accepted(
    *,
    accepter_display: str,
    doc_title: str,
    doc_url: str,
) -> dict:
    subject = f'{accepter_display} accepted your invite to "{doc_title}".'
    ctx = {
        **_base_ctx("someone accepted an invite link you created."),
        "subject": subject,
        "accepter_display": accepter_display,
        "doc_title": doc_title,
        "doc_url": doc_url,
    }
    return {
        "subject": subject,
        "html": _render("invite_accepted.html", **ctx),
        "text": _render("invite_accepted.txt", **ctx),
    }
