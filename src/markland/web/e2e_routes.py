"""E2E smoke-test endpoints. Mounted only when MARKLAND_E2E_SECRET is set.

These routes exist so an external smoke runner (e.g. gauntlet) can drive
the real browser auth flow against prod without round-tripping through
Resend. They are NOT part of the user-facing API and are absent unless
the env var is configured at boot.

Auth model: every endpoint requires the `X-Markland-E2E-Secret` header
to equal `MARKLAND_E2E_SECRET` exactly. Constant-time compare via hmac.

Allowlist: emails are restricted to the `@markland.test` suffix so the
endpoint can never be coerced into minting a verify URL for a real
user's email. The smoke runner picks a fresh local-part each run.
"""

from __future__ import annotations

import hmac
import os
import sqlite3

from fastapi import APIRouter, Header, HTTPException

from markland.service.magic_link import issue_magic_link_token


_E2E_EMAIL_SUFFIX = "@markland.test"


def build_e2e_router(
    *,
    db_conn: sqlite3.Connection,
    session_secret: str,
    base_url: str,
    e2e_secret: str,
) -> APIRouter:
    """Return a router carrying e2e smoke endpoints, or an empty router if
    the secret is falsy. Callers should still mount the empty router so a
    misconfigured prod surfaces 404 (not 500) on the test path."""
    router = APIRouter()

    if not e2e_secret:
        return router

    def _check_secret(provided: str | None) -> None:
        if not provided or not hmac.compare_digest(provided, e2e_secret):
            # 404 (not 403) so a wrong/missing secret looks indistinguishable
            # from "endpoint not deployed" — denies fingerprinting.
            raise HTTPException(404, "not found")

    @router.post("/api/test/mint-magic-link")
    def mint_magic_link(
        email: str,
        x_markland_e2e_secret: str | None = Header(default=None),
    ):
        """Mint a real verify URL for an @markland.test address.

        The token is identical to what /api/auth/magic-link would issue —
        signed with the prod session secret, single-use, 15-minute window.
        Skips Resend so the smoke runner doesn't need inbox access.
        """
        _check_secret(x_markland_e2e_secret)
        normalized = email.strip().lower()
        if not normalized.endswith(_E2E_EMAIL_SUFFIX):
            raise HTTPException(
                400, f"email must end with {_E2E_EMAIL_SUFFIX}"
            )
        token = issue_magic_link_token(normalized, secret=session_secret)
        return {
            "verify_url": f"{base_url.rstrip('/')}/verify?token={token}",
            "email": normalized,
        }

    return router


def e2e_secret_from_env() -> str:
    """Read MARKLAND_E2E_SECRET from env. Empty string = disabled."""
    return os.environ.get("MARKLAND_E2E_SECRET", "").strip()
