"""EmailDispatcher unit tests — enqueue, worker, jittered exponential retry, drop."""

import asyncio
from unittest.mock import MagicMock

import pytest

from markland.service.email import EmailSendError
from markland.service.email_dispatcher import EmailDispatcher


class _FakeClient:
    def __init__(self, *, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls: list[dict] = []

    def send(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.fail_times:
            raise EmailSendError("boom")
        return "email_ok"


@pytest.mark.asyncio
async def test_enqueue_and_send_once_on_success():
    client = _FakeClient(fail_times=0)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(
            to="a@b",
            subject="s",
            html="<p>h</p>",
            text="h",
            metadata={"template": "user_grant"},
        )
        await disp.drain()
    finally:
        await disp.stop()

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["to"] == "a@b"
    assert call["subject"] == "s"
    assert call["html"] == "<p>h</p>"
    assert call["text"] == "h"
    assert call["metadata"] == {"template": "user_grant"}


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    client = _FakeClient(fail_times=2)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
        # Give time for retries to cycle
        for _ in range(50):
            await asyncio.sleep(0.02)
            if len(client.calls) >= 3:
                break
        await disp.drain()
    finally:
        await disp.stop()

    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_drops_after_three_retries(caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="markland.email_dispatcher")
    client = _FakeClient(fail_times=99)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
        # Wait for all 4 attempts to complete
        for _ in range(80):
            await asyncio.sleep(0.02)
            if len(client.calls) >= 4:
                # Give the drop log a moment to fire
                await asyncio.sleep(0.05)
                break
        await disp.drain()
    finally:
        await disp.stop()

    # Four total attempts: initial + 3 retries = 4 tries, then dropped.
    assert len(client.calls) == 4
    assert any("dropping email" in r.message.lower() for r in caplog.records)


@pytest.mark.asyncio
async def test_stop_is_idempotent_and_drains_in_flight():
    client = _FakeClient(fail_times=0)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
    # Give the worker a moment to pick it up before stop.
    await asyncio.sleep(0.05)
    await disp.stop()
    await disp.stop()  # second stop is a no-op
    # Enqueue after stop is allowed but not worked on — we just verify no crash.
    disp.enqueue(to="c@d", subject="s", html="<p>h</p>", text="h")
    assert len(client.calls) == 1  # only the first one was processed


@pytest.mark.asyncio
async def test_client_that_returns_none_noop_is_treated_as_success():
    client = MagicMock()
    client.send = MagicMock(return_value=None)
    disp = EmailDispatcher(client, retry_delays=(0.01, 0.01, 0.01))
    await disp.start()
    try:
        disp.enqueue(to="a@b", subject="s", html="<p>h</p>", text="h")
        await disp.drain()
    finally:
        await disp.stop()
    assert client.send.call_count == 1
