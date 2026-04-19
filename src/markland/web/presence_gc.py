"""Background asyncio task that sweeps expired presence rows every N seconds.

Registered on the FastAPI app's lifespan. Failures are logged and swallowed;
the loop continues ticking so one bad DB call does not kill GC forever.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from typing import Callable

from markland.service import presence

logger = logging.getLogger("markland.presence.gc")


async def _loop(
    gc_callable: Callable[..., int],
    *,
    interval_seconds: float,
    stop_event: asyncio.Event,
) -> None:
    """Call `gc_callable()` every `interval_seconds` until `stop_event` is set.

    Factored out of `start()` so unit tests can exercise the loop without a
    full FastAPI app or DB.
    """
    while not stop_event.is_set():
        try:
            deleted = gc_callable()
            if deleted:
                logger.info("presence gc deleted %d expired rows", deleted)
        except Exception:  # defensive; tested via injected bad callable
            logger.exception("presence gc tick failed; continuing")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass


def start(
    conn: sqlite3.Connection,
    *,
    interval_seconds: float = 60.0,
) -> tuple[asyncio.Task, asyncio.Event]:
    """Start the GC task. Returns (task, stop_event) for lifespan teardown."""
    stop_event = asyncio.Event()

    def _gc_once() -> int:
        return presence.gc_expired(conn)

    task = asyncio.create_task(
        _loop(_gc_once, interval_seconds=interval_seconds, stop_event=stop_event)
    )
    return task, stop_event


async def stop(task: asyncio.Task, stop_event: asyncio.Event) -> None:
    """Signal the loop to stop, then wait for it to exit."""
    stop_event.set()
    try:
        await asyncio.wait_for(task, timeout=5.0)
    except asyncio.TimeoutError:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
