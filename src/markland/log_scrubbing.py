"""Redaction helpers for access logs and Sentry events.

Magic-link tokens, share tokens, CSRF tokens, and ``Authorization`` headers
must never reach long-lived log storage in plaintext. The ``GET /verify``
endpoint takes a single-use token in the query string, which means without
redaction the secret would land in:

* uvicorn's ``uvicorn.access`` log (printed to stdout, captured by Fly's log
  aggregator and any downstream log-shipper).
* Sentry breadcrumbs and request payloads attached to error events.

This module exposes a ``logging.Filter`` that rewrites the request line in
``uvicorn.access`` records and a ``before_send`` callback for the Sentry SDK
that scrubs the same parameter names from request/breadcrumb payloads.
"""

from __future__ import annotations

import logging
import re
from typing import Any

# Parameter names whose values should always be redacted in URLs/log lines.
_SENSITIVE_PARAMS: tuple[str, ...] = (
    "token",
    "share_token",
    "csrf",
    "magic_link",
)

_REDACTED = "[REDACTED]"

# Match `name=value` where name is one of the sensitive params and value
# extends until the next `&` or whitespace. Case-insensitive match on the
# parameter name; values are replaced wholesale.
_PARAM_RE = re.compile(
    r"(?i)\b(" + "|".join(re.escape(p) for p in _SENSITIVE_PARAMS) + r")=[^&\s#]*"
)


def redact_url(value: str) -> str:
    """Return ``value`` with sensitive query-parameter values masked.

    Operates on either a full URL, a path+query, or a bare query string.
    Non-string inputs are returned unchanged.
    """
    if not isinstance(value, str) or not value:
        return value
    return _PARAM_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", value)


class RedactSensitiveQueryParamsFilter(logging.Filter):
    """Redact sensitive query params from ``uvicorn.access`` log records.

    The uvicorn AccessFormatter reads the request URL out of
    ``record.args[2]`` (``full_path``). We mutate that tuple in place so the
    formatter — and any downstream handler — only ever sees the redacted
    version. Returning ``True`` always; this filter never drops records.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            redacted = redact_url(args[2])
            if redacted != args[2]:
                record.args = args[:2] + (redacted,) + args[3:]
        return True


def build_uvicorn_log_config() -> dict[str, Any]:
    """Return a uvicorn-compatible LOGGING_CONFIG that scrubs access logs.

    Mirrors the structure of :data:`uvicorn.config.LOGGING_CONFIG` and
    attaches :class:`RedactSensitiveQueryParamsFilter` to the
    ``uvicorn.access`` logger so any value in a sensitive query parameter is
    masked before reaching stdout.
    """
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
            },
        },
        "filters": {
            "redact_sensitive": {
                "()": "markland.log_scrubbing.RedactSensitiveQueryParamsFilter",
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "filters": ["redact_sensitive"],
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {
                "handlers": ["access"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }


# ---------------------------------------------------------------------------
# MCP client-disconnect noise
# ---------------------------------------------------------------------------
#
# The MCP SDK's streamable-HTTP transport wraps its whole POST handler in a
# blanket `except Exception` (mcp/server/streamable_http.py). A client that
# hangs up mid-body therefore surfaces as a server fault: `request.body()`
# raises `starlette.requests.ClientDisconnect`, which is logged at ERROR and
# then pushed back into the read stream, where the low-level server logs it a
# second time. One disconnect produces two Sentry events plus a 500 written to
# a socket nobody is listening on.
#
# Disconnects are entirely client-controlled and not actionable, and at volume
# they bury genuine 5xx in the alert. Drop exactly these two signatures --
# nothing broader, so a real transport error still reports.
_MCP_TRANSPORT_LOGGER = "mcp.server.streamable_http"
_MCP_DISCONNECT_EXC = ("starlette.requests", "ClientDisconnect")
_MCP_LOWLEVEL_LOGGER = "mcp.server.lowlevel.server"
_MCP_STREAM_ECHO = "Received exception from stream:"


def _is_mcp_disconnect_noise(event: dict[str, Any]) -> bool:
    """True for the two ERROR records a single MCP client disconnect emits."""
    logger_name = event.get("logger")

    if logger_name == _MCP_TRANSPORT_LOGGER:
        exception = event.get("exception")
        values = exception.get("values") if isinstance(exception, dict) else None
        if not isinstance(values, list):
            return False
        return any(
            isinstance(v, dict)
            and (v.get("module"), v.get("type")) == _MCP_DISCONNECT_EXC
            for v in values
        )

    if logger_name == _MCP_LOWLEVEL_LOGGER:
        logentry = event.get("logentry")
        if not isinstance(logentry, dict):
            return False
        text = logentry.get("formatted") or logentry.get("message")
        # `str(ClientDisconnect())` is empty, so the echo renders with nothing
        # after the colon. Any real exception carries a message and is kept.
        return isinstance(text, str) and text.strip() == _MCP_STREAM_ECHO

    return False


def scrub_sentry_event(
    event: dict[str, Any] | None, hint: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Sentry ``before_send`` callback — strip secrets from outgoing events.

    Defensively handles missing keys; Sentry does not guarantee a fixed event
    shape across SDK versions or integrations. The function never raises:
    redaction is best-effort, but a crash here would silently lose the event
    in the Sentry SDK and we'd rather ship a partially-redacted event than
    no event at all (we still strip the worst offenders below).

    Returning ``None`` drops the event. We do that for one case only -- the
    MCP client-disconnect records described above, which are misclassified
    client behaviour rather than server errors. Everything else returns the
    (mutated) event so error reporting still works.
    """
    if not isinstance(event, dict):
        return event

    if _is_mcp_disconnect_noise(event):
        return None

    # ---- Request payload ----
    request = event.get("request")
    if isinstance(request, dict):
        # Strip Authorization header; Sentry already masks it by default
        # since send_default_pii=False, but be explicit for defence-in-depth
        # in case someone flips that flag later.
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key in list(headers.keys()):
                if key.lower() == "authorization":
                    headers.pop(key, None)
        elif isinstance(headers, list):
            request["headers"] = [
                pair
                for pair in headers
                if not (
                    isinstance(pair, (list, tuple))
                    and len(pair) >= 1
                    and isinstance(pair[0], str)
                    and pair[0].lower() == "authorization"
                )
            ]
        # Redact sensitive params from URL / query string fields.
        if isinstance(request.get("url"), str):
            request["url"] = redact_url(request["url"])
        if isinstance(request.get("query_string"), str):
            request["query_string"] = redact_url(request["query_string"])

    # ---- Breadcrumbs ----
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        values = breadcrumbs.get("values")
    else:
        values = breadcrumbs if isinstance(breadcrumbs, list) else None
    if isinstance(values, list):
        for crumb in values:
            if not isinstance(crumb, dict):
                continue
            data = crumb.get("data")
            if isinstance(data, dict):
                for key in ("url", "query_string"):
                    if isinstance(data.get(key), str):
                        data[key] = redact_url(data[key])
            # Some integrations stash the URL on the crumb message itself.
            if isinstance(crumb.get("message"), str):
                crumb["message"] = redact_url(crumb["message"])

    return event
