"""In-process email dispatch queue with jittered exponential-backoff retry.

Design notes:
- Fire-and-forget: callers call the synchronous `enqueue(...)` which puts an item
  on the queue via `put_nowait` and returns immediately. Callers never `await enqueue`.
- A single background worker task pulls items and calls EmailClient.send.
- On EmailSendError, the item is re-enqueued with an incrementing attempt counter.
  After `len(retry_delays)` failures, the item is dropped with a WARNING log.
- Retry delays are jittered by ±25% to avoid thundering herds against Resend.
- No persistence: process restart drops any in-flight items. Documented as OK for
  v1 per spec §7 ("lightweight in-process"). Persistent queue lands post-launch
  when Redis/DB-backed retry is justified.
- Grants and writes never fail because of email problems — callers always enqueue
  inside a try/except-and-log-only path.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from dataclasses import dataclass
from typing import Protocol

from markland.service.email import EmailSendError

logger = logging.getLogger("markland.email_dispatcher")

# Attempts after initial: 1s, 3s, 10s, then drop. Total 4 attempts including initial.
DEFAULT_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0, 10.0)

# Permanent-failure signatures from Resend. Anything matching here drops
# on attempt 1 instead of burning the retry budget. Refine as we collect
# more rejection shapes — a single helper, message-based, intentionally simple.
_PERMANENT_SIGNATURES: tuple[str, ...] = (
    "you can only send testing emails",  # sandbox mode
    "validation_error",                  # 422 from Resend on bad payload
    "invalid `to` field",                # malformed address
)


def _classify(exc: EmailSendError) -> str:
    """Return 'permanent' or 'transient' for an EmailSendError.

    Permanent failures should not be retried (sandbox rejection, validation).
    Transient failures (5xx, network, rate-limit) get the full retry ladder.
    """
    msg = str(exc).lower()
    for sig in _PERMANENT_SIGNATURES:
        if sig in msg:
            return "permanent"
    return "transient"


def _recipient_hash(addr: str) -> str:
    """Stable, non-reversible 12-hex-char digest. Suitable for tag values.

    Lets ops correlate "same recipient seeing repeated drops" without leaking
    the raw address into Sentry. sha256 truncated; collisions on 12 hex chars
    are statistically irrelevant at our volume.
    """
    return hashlib.sha256(addr.encode("utf-8")).hexdigest()[:12]


def _safe_sentry_capture(
    exc: BaseException,
    *,
    tags: dict[str, str],
) -> None:
    """Best-effort Sentry capture. No-op if sentry_sdk missing or init failed.

    Mirrors run_app.py's optional-import style — we never want a Sentry
    transport problem to take down the dispatcher worker.
    """
    try:
        import sentry_sdk
    except ImportError:
        return
    try:
        with sentry_sdk.new_scope() as scope:
            for k, v in tags.items():
                scope.set_tag(k, v)
            sentry_sdk.capture_exception(exc)
    except Exception as err:
        # Sentry transport / init issues must not poison the queue. Log at
        # WARNING (not ERROR/exception) so Sentry's own LoggingIntegration
        # cannot re-fire on this failure path.
        logger.warning("sentry capture failed: %r", err)


class _ClientProto(Protocol):
    def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> str | None: ...


@dataclass
class _Item:
    to: str
    subject: str
    html: str
    text: str | None
    metadata: dict[str, str] | None
    attempt: int = 0


class EmailDispatcher:
    def __init__(
        self,
        client: _ClientProto,
        *,
        retry_delays: tuple[float, ...] = DEFAULT_RETRY_DELAYS,
        jitter_frac: float = 0.25,
    ) -> None:
        self._client = client
        self._retry_delays = retry_delays
        self._jitter_frac = jitter_frac
        self._queue: asyncio.Queue[_Item] = asyncio.Queue()
        self._worker: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._worker is not None:
            return
        self._stopped.clear()
        self._worker = asyncio.create_task(self._run(), name="email-dispatcher")
        logger.info("EmailDispatcher started")

    async def stop(self) -> None:
        if self._worker is None:
            return
        self._stopped.set()
        # Cancel the waiting worker; queue.get will raise CancelledError.
        self._worker.cancel()
        try:
            await self._worker
        except asyncio.CancelledError:
            pass
        self._worker = None
        logger.info("EmailDispatcher stopped")

    def enqueue(
        self,
        to: str,
        subject: str,
        html: str,
        text: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> None:
        """Synchronous, non-blocking. Puts the item on the queue and returns.

        Callers must NOT await this method. It is safe to call from sync or async
        contexts. The background worker (async) picks items off the queue and
        calls EmailClient.send.
        """
        item = _Item(
            to=to, subject=subject, html=html, text=text, metadata=metadata,
        )
        # asyncio.Queue.put_nowait is safe to call from a sync context; the
        # queue is unbounded so QueueFull will not be raised in practice.
        self._queue.put_nowait(item)

    async def drain(self, timeout: float = 5.0) -> None:
        """Wait until the queue is empty and the worker is idle. Test helper."""
        async def _wait() -> None:
            await self._queue.join()

        await asyncio.wait_for(_wait(), timeout=timeout)

    async def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                item = await self._queue.get()
                try:
                    await self._process(item)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            return

    async def _process(self, item: _Item) -> None:
        try:
            # Run blocking resend SDK in a thread so the worker stays responsive.
            await asyncio.to_thread(
                self._client.send,
                to=item.to,
                subject=item.subject,
                html=item.html,
                text=item.text,
                metadata=item.metadata,
            )
        except EmailSendError as exc:
            failure_kind = _classify(exc)
            if failure_kind == "permanent":
                attempts = item.attempt + 1
                template = (item.metadata or {}).get("template", "unknown")
                rcpt_hash = _recipient_hash(item.to)
                action = {
                    "template": template,
                    "attempts": attempts,
                    "error_class": type(exc).__name__,
                    "failure_kind": failure_kind,
                    "recipient_hash": rcpt_hash,
                }
                logger.warning(
                    "dropping email (rcpt %s) on attempt %d (permanent): %s",
                    rcpt_hash, attempts, exc,
                    extra={"action": action},
                )
                _safe_sentry_capture(
                    exc,
                    tags={
                        "template": template,
                        "attempts": str(attempts),
                        "failure_kind": failure_kind,
                        "recipient_hash": rcpt_hash,
                    },
                )
                return
            if item.attempt >= len(self._retry_delays):
                attempts = item.attempt + 1
                template = (item.metadata or {}).get("template", "unknown")
                rcpt_hash = _recipient_hash(item.to)
                action = {
                    "template": template,
                    "attempts": attempts,
                    "error_class": type(exc).__name__,
                    "failure_kind": failure_kind,
                    "recipient_hash": rcpt_hash,
                }
                logger.warning(
                    "dropping email (rcpt %s) after %d attempts: %s",
                    rcpt_hash, attempts, exc,
                    extra={"action": action},
                )
                _safe_sentry_capture(
                    exc,
                    tags={
                        "template": template,
                        "attempts": str(attempts),
                        "failure_kind": failure_kind,
                        "recipient_hash": rcpt_hash,
                    },
                )
                return
            delay = self._retry_delays[item.attempt]
            jitter = delay * self._jitter_frac
            delay = delay + random.uniform(-jitter, jitter)
            delay = max(0.0, delay)
            logger.info(
                "email to %s failed (attempt %d); retrying in %.2fs: %s",
                item.to, item.attempt + 1, delay, exc,
            )
            item.attempt += 1
            asyncio.create_task(self._requeue_after(item, delay))
        except Exception as exc:
            # Unexpected error — drop, don't poison the queue.
            logger.exception("unexpected error sending email to %s: %s", item.to, exc)

    async def _requeue_after(self, item: _Item, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            if self._stopped.is_set():
                return
            self._queue.put_nowait(item)
        except asyncio.CancelledError:
            return
