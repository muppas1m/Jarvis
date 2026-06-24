"""Gmail adapter — behaviour-identical wrapping of the old gmail_send/watch/pubsub
logic behind the EmailProvider interface. The Google service is mocked (the
adapter is the only googleapiclient importer); we assert the MIME + threading
headers + threadId an actual Gmail send would receive, plus the inbound mapping
and the factory selection.
"""
import base64
import email as email_lib

import pytest

from app.email.provider import GmailProvider, ReplyRef, get_email_provider


# --- fake Gmail service ------------------------------------------------------
class _Req:
    def __init__(self, result, sink, kind, kwargs):
        self._result, self._sink, self._kind, self._kwargs = result, sink, kind, kwargs

    def execute(self):
        self._sink.append((self._kind, self._kwargs))
        return self._result


class _Messages:
    def __init__(self, sink, *, get_result=None, send_result=None, list_result=None):
        self.sink = sink
        self.get_result = get_result or {}
        self.send_result = send_result or {"id": "sent-1"}
        self.list_result = list_result or {}

    def get(self, **k):
        return _Req(self.get_result, self.sink, "get", k)

    def send(self, **k):
        return _Req(self.send_result, self.sink, "send", k)

    def list(self, **k):
        return _Req(self.list_result, self.sink, "list", k)

    def modify(self, **k):
        return _Req({}, self.sink, "modify", k)


class _Users:
    def __init__(self, messages):
        self._m = messages

    def messages(self):
        return self._m

    def watch(self, **k):
        return _Req({"expiration": "999"}, self._m.sink, "watch", k)

    def stop(self, **k):
        return _Req({}, self._m.sink, "stop", k)


class _Service:
    def __init__(self, messages):
        self._u = _Users(messages)

    def users(self):
        return self._u


def _provider(monkeypatch, messages):
    p = GmailProvider()
    monkeypatch.setattr(p, "_service", lambda: _Service(messages))
    return p, messages.sink


# --- send: threading is byte-identical to the old gmail_send -----------------
async def test_send_threads_reply_with_headers_and_threadid(monkeypatch):
    sink: list = []
    msgs = _Messages(sink, get_result={"threadId": "THREAD-9"}, send_result={"id": "sent-9"})
    p, _ = _provider(monkeypatch, msgs)

    result = await p.send(
        to="bob@example.com",
        subject="Re: Lunch",
        body="Sounds good.",
        reply_to=ReplyRef(
            provider="gmail", message_id="src-1", rfc822_message_id="<orig@mail>"
        ),
    )

    assert result.provider == "gmail" and result.sent_message_id == "sent-9"
    send_call = next(c for c in sink if c[0] == "send")
    body = send_call[1]["body"]
    assert body["threadId"] == "THREAD-9"  # looked up from the source message id
    mime = email_lib.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
    assert mime["To"] == "bob@example.com"
    assert mime["Subject"] == "Re: Lunch"
    assert mime["In-Reply-To"] == "<orig@mail>"  # RFC822 threading header set
    assert mime["References"] == "<orig@mail>"
    assert "Sounds good." in mime.get_payload(decode=True).decode()


async def test_send_fresh_email_no_threading(monkeypatch):
    sink: list = []
    p, _ = _provider(monkeypatch, _Messages(sink))
    await p.send(to="x@y.com", subject="Hi", body="Hello")  # no reply_to
    send_call = next(c for c in sink if c[0] == "send")
    body = send_call[1]["body"]
    assert "threadId" not in body  # no source → fresh email
    mime = email_lib.message_from_bytes(base64.urlsafe_b64decode(body["raw"]))
    assert "In-Reply-To" not in mime
    # and no threadId lookup happened (no get call)
    assert not any(c[0] == "get" for c in sink)


# --- inbound mapping ---------------------------------------------------------
async def test_fetch_message_maps_to_inbound(monkeypatch):
    full = {
        "id": "m-1",
        "threadId": "t-1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Quarterly review"},
                {"name": "From", "value": "Priya <p@x.com>"},
                {"name": "Message-ID", "value": "<abc@mail>"},
            ],
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": base64.urlsafe_b64encode(b"the body text").decode()},
                }
            ],
        },
    }
    p, _ = _provider(monkeypatch, _Messages([], get_result=full))
    msg = await p.fetch_message("m-1")
    assert msg.provider == "gmail"
    assert msg.message_id == "m-1" and msg.thread_ref == "t-1"
    assert msg.rfc822_message_id == "<abc@mail>"  # opaque-id-distinct from message_id
    assert msg.sender == "Priya <p@x.com>" and msg.subject == "Quarterly review"
    assert msg.body == "the body text"


async def test_list_recent_and_archive(monkeypatch):
    sink: list = []
    msgs = _Messages(sink, list_result={"messages": [{"id": "a"}, {"id": "b"}]})
    p, _ = _provider(monkeypatch, msgs)
    assert await p.list_recent_message_ids() == ["a", "b"]
    await p.archive("a")
    modify = next(c for c in sink if c[0] == "modify")
    assert modify[1]["body"] == {"removeLabelIds": ["INBOX"]} and modify[1]["id"] == "a"


def test_parse_push_decodes_history_id():
    p = GmailProvider()
    data = base64.b64encode(b'{"historyId": "12345"}').decode()
    assert p.parse_push({"data": data}) == "12345"
    assert p.parse_push({}) is None  # no data → nothing actionable
    assert p.parse_push({"data": "!!notbase64!!"}) is None  # malformed → None, no raise


# --- factory -----------------------------------------------------------------
def test_factory_returns_gmail_and_caches():
    a = get_email_provider("gmail")
    b = get_email_provider("gmail")
    assert isinstance(a, GmailProvider) and a is b  # cached singleton


def test_factory_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown EMAIL_PROVIDER"):
        get_email_provider("carrier-pigeon")
