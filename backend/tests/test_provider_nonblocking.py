"""Part A proof: the Gmail adapter does NOT block the event loop. Each sync SDK
call runs via asyncio.to_thread, so a concurrent async task keeps making progress
while a Gmail call is in flight. We prove it by having a (mocked) send do a real
BLOCKING sleep inside the SDK call and reading, FROM that blocked thread, how far
a concurrently-running loop ticker got — if the loop were blocked the ticker
couldn't have advanced.
"""
import asyncio
import time

import pytest

from app.email.provider import GmailProvider


class _BlockingMessages:
    """A fake Gmail messages() whose send().execute() blocks the calling thread
    and snapshots the loop ticker at the moment it unblocks."""

    def __init__(self, sink, get_ticks):
        self.sink = sink
        self.get_ticks = get_ticks

    def send(self, **k):
        outer = self

        class _Req:
            def execute(self):
                time.sleep(0.3)  # a slow Gmail round-trip
                outer.sink["ticks_during_send"] = outer.get_ticks()
                return {"id": "sent-1"}

        return _Req()


class _Users:
    def __init__(self, messages):
        self._m = messages

    def messages(self):
        return self._m


class _Service:
    def __init__(self, messages):
        self._u = _Users(messages)

    def users(self):
        return self._u


async def test_send_does_not_block_the_event_loop(monkeypatch):
    sink: dict = {}
    ticks = 0

    p = GmailProvider()
    monkeypatch.setattr(
        p, "_service", lambda: _Service(_BlockingMessages(sink, lambda: ticks))
    )

    async def ticker():
        nonlocal ticks
        for _ in range(40):
            await asyncio.sleep(0.01)
            ticks += 1

    # Send (blocks 0.3s in a worker thread) CONCURRENTLY with the loop ticker.
    await asyncio.gather(p.send("bob@example.com", "Hi", "body"), ticker())

    # If send blocked the loop, the ticker couldn't advance during the 0.3s call
    # → ticks_during_send ≈ 0. Off-loop (to_thread) → it advances freely.
    assert sink["ticks_during_send"] >= 5, (
        f"loop was blocked during send (ticker only reached "
        f"{sink.get('ticks_during_send')} of ~30 expected)"
    )


async def test_blocking_call_is_bounded(monkeypatch):
    """A hung Gmail call can't wedge the agent — wait_for bounds it."""
    p = GmailProvider()

    class _HangMessages:
        def get(self, **k):
            class _Req:
                def execute(self):
                    time.sleep(5)  # simulate a hung round-trip
                    return {"id": "x"}

            return _Req()

    monkeypatch.setattr(p, "_service", lambda: _Service2(_HangMessages()))
    with pytest.raises(asyncio.TimeoutError):
        await p._blocking(
            lambda: p._service().users().messages().get(userId="me", id="x").execute(),
            timeout=0.2,
        )


class _Users2:
    def __init__(self, messages):
        self._m = messages

    def messages(self):
        return self._m


class _Service2:
    def __init__(self, messages):
        self._u = _Users2(messages)

    def users(self):
        return self._u
