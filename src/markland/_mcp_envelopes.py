"""Canonical MCP return envelopes. See spec §8.2."""

from __future__ import annotations

import base64
import json
from typing import Any


_DOC_ENVELOPE_FIELDS = (
    "id", "title", "content", "version", "owner_id", "share_url",
    "is_public", "is_featured", "created_at", "updated_at",
)

_DOC_SUMMARY_FIELDS = (
    "id", "title", "owner_id", "is_public", "is_featured",
    "created_at", "updated_at", "version",
)


def doc_envelope(
    raw: dict, *, active_principals: list[dict] | None = None
) -> dict:
    """Project a service-layer doc dict into the canonical doc_envelope."""
    env = {k: raw.get(k) for k in _DOC_ENVELOPE_FIELDS}
    if active_principals is not None:
        env["active_principals"] = active_principals
    return env


def doc_summary(raw: dict) -> dict:
    """Project a service-layer doc dict into the canonical doc_summary
    (no content)."""
    return {k: raw.get(k) for k in _DOC_SUMMARY_FIELDS}


def list_envelope(*, items: list[Any], next_cursor: str | None) -> dict:
    """Wrap a paginated result in the canonical list_envelope."""
    return {"items": list(items), "next_cursor": next_cursor}


def encode_cursor(*, last_id: str, last_updated_at: str) -> str:
    """Encode pagination state as opaque base64-JSON.

    Consumers must use ORDER BY (updated_at DESC, id DESC) and WHERE
    (updated_at, id) < (?, ?) for stable pagination across rows with equal
    updated_at."""
    payload = json.dumps(
        {"last_id": last_id, "last_updated_at": last_updated_at},
        sort_keys=True,
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    """Decode an opaque cursor. Returns (last_id, last_updated_at).
    Raises ValueError on malformed input."""
    pad = "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + pad).decode())
        return payload["last_id"], payload["last_updated_at"]
    except (ValueError, KeyError, UnicodeDecodeError) as exc:
        raise ValueError(f"malformed cursor: {exc}") from exc
