"""Tests for the Resend email wrapper."""

from unittest.mock import patch

import pytest

from markland.service.email import EmailClient, EmailSendError


def test_sends_via_resend_with_html_and_text():
    client = EmailClient(api_key="re_test", from_email="notifications@markland.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "email_abc"}
        msg_id = client.send(
            to="alice@example.com",
            subject="Hi",
            html="<p>hi</p>",
            text="hi",
        )
    assert msg_id == "email_abc"
    sent = send_mock.call_args.args[0] if send_mock.call_args.args else send_mock.call_args.kwargs
    assert sent["to"] == "alice@example.com"
    assert sent["from"] == "notifications@markland.dev"
    assert sent["subject"] == "Hi"
    assert sent["html"] == "<p>hi</p>"
    assert sent["text"] == "hi"


def test_send_forwards_metadata_as_tags_when_provided():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "x"}
        client.send(
            to="a@b",
            subject="s",
            html="<p>x</p>",
            text="x",
            metadata={"template": "user_grant", "doc_id": "d_1"},
        )
    sent = send_mock.call_args.args[0] if send_mock.call_args.args else send_mock.call_args.kwargs
    tags = sent.get("tags") or []
    names = {t["name"] for t in tags}
    assert "template" in names
    assert "doc_id" in names


def test_send_without_text_still_works_backward_compat():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        send_mock.return_value = {"id": "x"}
        client.send(to="a@b", subject="s", html="<p>x</p>")
    sent = send_mock.call_args.args[0] if send_mock.call_args.args else send_mock.call_args.kwargs
    assert sent["html"] == "<p>x</p>"
    assert "text" not in sent or sent["text"] in (None, "")


def test_noop_when_api_key_empty():
    client = EmailClient(api_key="", from_email="n@m.dev")
    with patch("resend.Emails.send") as send_mock:
        msg_id = client.send(to="a@b", subject="x", html="<p>x</p>", text="x")
    send_mock.assert_not_called()
    assert msg_id is None


def test_raises_on_resend_failure():
    client = EmailClient(api_key="re_test", from_email="n@m.dev")
    with patch("resend.Emails.send", side_effect=RuntimeError("resend down")):
        with pytest.raises(EmailSendError):
            client.send(to="a@b", subject="x", html="<p>x</p>", text="x")
