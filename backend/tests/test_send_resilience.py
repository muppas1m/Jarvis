"""Part B: resilient send WITHOUT ever double-sending. The retry classification
is the safety-critical part, so it's tested adversarially: 429/503 (Gmail rejected
before sending → safe) retry; a read-timeout (maybe-delivered), 4xx (permanent),
and 500 (ambiguous) are NEVER retried — they surface. Plus References is chained
from the parent so the whole thread links.

`_blocking` is mocked per-attempt so we count exactly how many send attempts fire
(the no-double-send proof) without real threads/sleeps.
"""
import asyncio
import base64
import email as email_lib

import pytest
from googleapiclient.errors import HttpError

from app.config import settings
from app.email.provider import GmailProvider, ReplyRef


def _http_error(status: int) -> HttpError:
    class _Resp:
        def __init__(self, s):
            self.status = s
            self.reason = "err"

    return HttpError(_Resp(status), b"{}")


def _scripted_blocking(outcomes: list, calls: dict):
    """An async _blocking that yields each outcome in turn (raise if Exception,
    else return), counting attempts."""

    async def fake(fn, *, timeout=None):
        i = calls["n"]
        calls["n"] += 1
        outcome = outcomes[min(i, len(outcomes) - 1)]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return fake


async def test_429_retried_then_delivers_once(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_SEND_RETRY_BASE_S", 0.001)
    p = GmailProvider()
    calls = {"n": 0}
    # 429 (rejected, didn't send) → retry → success. One real delivery.
    monkeypatch.setattr(p, "_blocking", _scripted_blocking([_http_error(429), {"id": "sent-1"}], calls))
    result = await p.send("a@b.com", "Hi", "body")
    assert result.sent_message_id == "sent-1"
    assert calls["n"] == 2  # retried once → exactly one successful delivery


async def test_503_retried_then_delivers_once(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_SEND_RETRY_BASE_S", 0.001)
    p = GmailProvider()
    calls = {"n": 0}
    monkeypatch.setattr(p, "_blocking", _scripted_blocking([_http_error(503), {"id": "s2"}], calls))
    assert (await p.send("a@b.com", "Hi", "body")).sent_message_id == "s2"
    assert calls["n"] == 2


async def test_read_timeout_NOT_retried(monkeypatch):
    """A timeout may mean Gmail already ACCEPTED the request — retrying could
    DUPLICATE. So it surfaces after exactly ONE attempt."""
    p = GmailProvider()
    calls = {"n": 0}
    monkeypatch.setattr(p, "_blocking", _scripted_blocking([TimeoutError()], calls))
    with pytest.raises(asyncio.TimeoutError):
        await p.send("a@b.com", "Hi", "body")
    assert calls["n"] == 1  # NEVER retried — no duplicate risk


async def test_4xx_NOT_retried(monkeypatch):
    p = GmailProvider()
    calls = {"n": 0}
    monkeypatch.setattr(p, "_blocking", _scripted_blocking([_http_error(403)], calls))
    with pytest.raises(HttpError):
        await p.send("a@b.com", "Hi", "body")
    assert calls["n"] == 1  # permanent → retry can't help


async def test_500_NOT_retried(monkeypatch):
    """500 is ambiguous (may have delivered) → surface, don't blind-retry."""
    p = GmailProvider()
    calls = {"n": 0}
    monkeypatch.setattr(p, "_blocking", _scripted_blocking([_http_error(500)], calls))
    with pytest.raises(HttpError):
        await p.send("a@b.com", "Hi", "body")
    assert calls["n"] == 1


async def test_persistent_429_exhausts_then_surfaces(monkeypatch):
    monkeypatch.setattr(settings, "EMAIL_SEND_RETRY_BASE_S", 0.001)
    p = GmailProvider()
    calls = {"n": 0}
    monkeypatch.setattr(p, "_blocking", _scripted_blocking([_http_error(429)], calls))
    with pytest.raises(HttpError):
        await p.send("a@b.com", "Hi", "body")
    # first attempt + EMAIL_SEND_RETRIES retries, then surfaces — bounded, no infinite loop.
    assert calls["n"] == settings.EMAIL_SEND_RETRIES + 1


# --- References chaining (Part D.3) ------------------------------------------
async def test_references_chained_from_parent(monkeypatch):
    p = GmailProvider()
    sent: dict = {}

    class _Msgs:
        def get(self, **k):
            class _R:
                def execute(self):
                    return {
                        "threadId": "T1",
                        "payload": {"headers": [{"name": "References", "value": "<a@m> <b@m>"}]},
                    }

            return _R()

        def send(self, **k):
            sent["body"] = k["body"]

            class _R:
                def execute(self):
                    return {"id": "sent-1"}

            return _R()

    class _U:
        def messages(self):
            return _Msgs()

    class _S:
        def users(self):
            return _U()

    monkeypatch.setattr(p, "_service", lambda: _S())
    await p.send(
        "bob@x.com", "Re: Hi", "body",
        reply_to=ReplyRef(provider="gmail", message_id="src", rfc822_message_id="<c@m>"),
    )
    mime = email_lib.message_from_bytes(base64.urlsafe_b64decode(sent["body"]["raw"]))
    # Full chain: the parent's References + the parent's Message-ID (not just the last hop).
    assert mime["References"] == "<a@m> <b@m> <c@m>"
    assert mime["In-Reply-To"] == "<c@m>"
    assert sent["body"]["threadId"] == "T1"
