"""Unified HTTP entrypoint: web viewer + MCP on /mcp, Sentry init, email dispatcher."""

import json as _json
import logging
import sys

import uvicorn

from markland.config import get_config
from markland.db import init_db
from markland.log_scrubbing import build_uvicorn_log_config, scrub_sentry_event
from markland.service.email import EmailClient
from markland.service.email_dispatcher import EmailDispatcher
from markland.web.app import create_app


class JsonFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object, stdout-friendly.

    Pulls structured fields (principal_id, doc_id, action) from record.__dict__
    when callers log with `logger.info("msg", extra={"principal_id": ..., ...})`.
    """

    _STRUCTURED = ("principal_id", "doc_id", "action")

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in self._STRUCTURED:
            if key in record.__dict__:
                payload[key] = record.__dict__[key]
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return _json.dumps(payload, separators=(",", ":"), sort_keys=True)


_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("markland.app")

config = get_config()

if config.sentry_dsn:
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=config.sentry_dsn,
            traces_sample_rate=0.1,
            send_default_pii=False,
            # Strip magic-link tokens, share tokens, CSRF tokens and
            # Authorization headers before events leave the process.
            before_send=scrub_sentry_event,
        )
        logger.info("Sentry initialized")
    except ImportError:
        logger.warning("SENTRY_DSN set but sentry-sdk not installed; skipping")

db_conn = init_db(config.db_path)
email_client = EmailClient(
    api_key=config.resend_api_key,
    from_email=config.resend_from_email,
)
email_dispatcher = EmailDispatcher(email_client)
app = create_app(
    db_conn,
    mount_mcp=True,
    base_url=config.base_url,
    session_secret=config.session_secret,
    email_client=email_client,
    email_dispatcher=email_dispatcher,
    enable_presence_gc=True,
    gc_interval_seconds=60.0,
)


if __name__ == "__main__":
    host = "0.0.0.0" if config.session_secret else "127.0.0.1"
    logger.info(
        "Starting Markland hosted app on %s:%d (db: %s, mcp_enabled=%s, resend=%s)",
        host,
        config.web_port,
        config.db_path,
        bool(config.session_secret),
        bool(config.resend_api_key),
    )
    # Fly's proxy terminates TLS and forwards over HTTP. Without
    # proxy_headers=True / forwarded_allow_ips, Starlette builds redirect
    # URLs from the inner http scheme -- bearer tokens on those redirects
    # would travel cleartext. Trust the X-Forwarded-* headers so redirects
    # preserve https. forwarded_allow_ips="*" is safe here because Fly's
    # edge is the only proxy in front of the app: any traffic that reaches
    # us has already passed Fly's edge, so we can trust the forwarded
    # headers from any source IP we see.
    uvicorn.run(
        app,
        host=host,
        port=config.web_port,
        log_level="info",
        proxy_headers=True,
        forwarded_allow_ips="*",
        # Custom log config attaches a redaction filter to uvicorn.access so
        # secrets in the request URL (token=, share_token=, csrf=,
        # magic_link=) don't end up in stdout-captured access logs.
        log_config=build_uvicorn_log_config(),
    )
