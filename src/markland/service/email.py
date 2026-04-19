"""Thin wrapper around Resend. No-ops safely when no API key is configured."""

from __future__ import annotations

import logging
from typing import Any

import resend

logger = logging.getLogger("markland.email")


class EmailSendError(RuntimeError):
    """Raised when Resend returns an error."""


class EmailClient:
    """Stateless-ish wrapper — holds api_key and from_email, calls resend.Emails.send."""

    def __init__(self, *, api_key: str, from_email: str) -> None:
        self._api_key = api_key
        self._from = from_email
        if api_key:
            resend.api_key = api_key

    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str | None:
        """Send an email with HTML + optional plaintext.

        `metadata` is forwarded to Resend as `tags` — useful for filtering the
        Resend dashboard by template name or document id. No PII should go here.
        Returns Resend's message id, or None if disabled (no API key).
        """
        if not self._api_key:
            logger.info(
                "Email disabled (no RESEND_API_KEY); would have sent to %s: %s",
                to, subject,
            )
            return None

        payload: dict[str, Any] = {
            "from": self._from,
            "to": to,
            "subject": subject,
            "html": html,
        }
        if text:
            payload["text"] = text
        if metadata:
            payload["tags"] = [
                {"name": k, "value": str(v)} for k, v in metadata.items()
            ]

        try:
            resp = resend.Emails.send(payload)
            return resp.get("id") if isinstance(resp, dict) else None
        except Exception as exc:
            raise EmailSendError(str(exc)) from exc
