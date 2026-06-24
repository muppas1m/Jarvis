"""Gmail-approval resolution — the ONE shared core every transport drives.

Covers the extracted handler (dispatch outcomes + gmail_send call-args + the
stale-row Gmail-fetch fallback + the exact channel-alert wording the Telegram
path depends on) and the router's prefix-dispatch (gmail: → handler, else
resume). The wording assertions are the regression guard for failure axis (a):
the working Telegram approve path must stay byte-identical.
"""
# Force-import gmail_send NOW, at collection time, BEFORE any test patches
# `app.db.engine.async_session`. gmail_send.py binds `async_session` at MODULE
# scope (`from app.db.engine import async_session`); if its first import happened
# inside a test where that name is monkeypatched to a fake, gmail_send would
# capture the fake permanently — monkeypatch can't restore a binding it never saw
# — and the fake would leak into a later test's REAL gmail_send (auto_sent flip
# silently fails). Importing it unpatched here pins the real sessionmaker.
# (Sibling of the async-state footgun the conftest rebind guards against.)
import app.agent.tools.gmail_send  # noqa: F401
import app.messaging.router as router_mod
from app.email.gmail_approval_handler import (
    GmailApprovalOutcome,
    channel_alert_for,
    dispatch_gmail_approval,
)

PAYLOAD = {
    "gmail_message_id": "msg-123",
    "rfc822_message_id": "<abc@mail.example>",
    "subject": "Project update",
    "sender": "Priya Rao <priya@example.com>",
    "draft": "Thanks Priya — confirmed for Thursday.",
}


# --- DB + gmail_send boundary fakes ----------------------------------------
class _Row:
    def __init__(self, payload):
        self.payload = payload


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self._row = row

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, *a, **k):
        return _FakeResult(self._row)


def _patch_row(monkeypatch, row):
    """Make the handler's `from app.db.engine import async_session` yield `row`."""
    monkeypatch.setattr("app.db.engine.async_session", lambda: _FakeSession(row))


def _patch_gmail_send(monkeypatch, sink, *, raises=None):
    async def fake_send(**kwargs):
        sink.update(kwargs)
        if raises:
            raise raises
        return "sent_id=xyz"

    monkeypatch.setattr("app.agent.tools.gmail_send.gmail_send", fake_send)


# --- dispatch: approve sends with the right payload -------------------------
async def test_approve_sends_with_correct_payload(monkeypatch):
    sink: dict = {}
    _patch_row(monkeypatch, _Row(PAYLOAD))
    _patch_gmail_send(monkeypatch, sink)

    outcome = await dispatch_gmail_approval("gmail:msg-123", {"approved": True})

    assert outcome.status == "sent"
    assert outcome.recipient == "priya@example.com"  # parseaddr stripped the name
    assert outcome.subject == "Re: Project update"  # Re: prefix added
    # gmail_send reached with the recovered draft + threading headers (axis b:
    # we verify the INVOCATION, not a delivered email — OAuth is expired).
    assert sink["to"] == "priya@example.com"
    assert sink["subject"] == "Re: Project update"
    assert sink["body"] == PAYLOAD["draft"]
    assert sink["in_reply_to_message_id"] == "<abc@mail.example>"
    assert sink["gmail_message_id"] == "msg-123"


async def test_approve_keeps_existing_re_prefix(monkeypatch):
    sink: dict = {}
    _patch_row(monkeypatch, _Row({**PAYLOAD, "subject": "Re: Project update"}))
    _patch_gmail_send(monkeypatch, sink)
    outcome = await dispatch_gmail_approval("gmail:msg-123", {"approved": True})
    assert outcome.subject == "Re: Project update"  # not doubled to "Re: Re:"


# --- dispatch: reject is a no-op (no send) ----------------------------------
async def test_reject_does_not_send(monkeypatch):
    sink: dict = {}
    _patch_gmail_send(monkeypatch, sink)
    outcome = await dispatch_gmail_approval("gmail:msg-123", {"approved": False})
    assert outcome.status == "rejected"
    assert sink == {}  # gmail_send never called


# --- dispatch: missing row / incomplete payload -----------------------------
async def test_row_missing(monkeypatch):
    _patch_row(monkeypatch, None)
    outcome = await dispatch_gmail_approval("gmail:gone", {"approved": True})
    assert outcome.status == "row_missing"


async def test_payload_incomplete(monkeypatch):
    sink: dict = {}
    _patch_row(monkeypatch, _Row({"gmail_message_id": "x"}))  # no draft / sender
    _patch_gmail_send(monkeypatch, sink)
    outcome = await dispatch_gmail_approval("gmail:x", {"approved": True})
    assert outcome.status == "payload_incomplete"
    assert sink == {}  # never attempts a send on incomplete data


# --- dispatch: send failure -------------------------------------------------
async def test_send_failure_surfaces(monkeypatch):
    _patch_row(monkeypatch, _Row(PAYLOAD))
    _patch_gmail_send(monkeypatch, {}, raises=RuntimeError("token expired"))
    outcome = await dispatch_gmail_approval("gmail:msg-123", {"approved": True})
    assert outcome.status == "send_failed"
    assert "token expired" in outcome.detail


# --- dispatch: stale-row fallback fetches headers from Gmail ----------------
async def test_stale_row_fetches_headers_from_gmail(monkeypatch):
    """A pre-Turn-17.5 row has no subject / rfc822_message_id in its payload →
    the handler fetches them from Gmail before sending."""
    sink: dict = {}
    stale = {
        "gmail_message_id": "msg-stale",
        "sender": "bob@example.com",
        "draft": "On it.",
        # subject + rfc822_message_id ABSENT
    }
    _patch_row(monkeypatch, _Row(stale))
    _patch_gmail_send(monkeypatch, sink)

    class _Exec:
        def execute(self):
            return {
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Quick question"},
                        {"name": "Message-ID", "value": "<stale@mail>"},
                    ]
                }
            }

    class _Messages:
        def get(self, **k):
            return _Exec()

    class _Users:
        def messages(self):
            return _Messages()

    class _Service:
        def users(self):
            return _Users()

    monkeypatch.setattr("app.email.gmail_watch.get_gmail_service", lambda: _Service())

    outcome = await dispatch_gmail_approval("gmail:msg-stale", {"approved": True})
    assert outcome.status == "sent"
    assert outcome.subject == "Re: Quick question"  # fetched + Re:-prefixed
    assert sink["in_reply_to_message_id"] == "<stale@mail>"  # fetched Message-ID


# --- channel alert wording (Telegram regression guard) ----------------------
def test_channel_alert_wording_is_unchanged():
    assert channel_alert_for(GmailApprovalOutcome(status="rejected"), "gmail:x") is None

    sent = GmailApprovalOutcome(
        status="sent", recipient="priya@example.com", subject="Re: Hi", detail="sent_id=xyz"
    )
    assert channel_alert_for(sent, "gmail:x") == (
        "✅ Reply sent to priya@example.com\nSubject: Re: Hi\nsent_id=xyz"
    )

    assert channel_alert_for(GmailApprovalOutcome(status="row_missing"), "gmail:abc") == (
        "Approval for gmail:abc couldn't be dispatched — the "
        "PendingApproval row wasn't found in the database."
    )
    assert channel_alert_for(GmailApprovalOutcome(status="payload_incomplete"), "gmail:abc") == (
        "Approval for gmail:abc can't be sent — the stored draft data "
        "is incomplete. Check the pending_approvals row."
    )
    failed = GmailApprovalOutcome(status="send_failed", detail="boom")
    assert channel_alert_for(failed, "gmail:abc") == (
        "❌ Failed to send reply for `gmail:abc`:\n```\nboom\n```"
    )


# --- router prefix-dispatch -------------------------------------------------
async def test_router_dispatches_gmail_prefix_to_handler(monkeypatch):
    called: dict = {}

    async def fake_handler(thread_id, platform, decision):
        called["args"] = (thread_id, platform, decision)

    async def fake_resume(**k):
        called["resumed"] = True
        return {"status": "interrupted"}

    monkeypatch.setitem(router_mod.CHANNEL_ORIGIN_HANDLERS, "gmail:", fake_handler)
    monkeypatch.setattr(router_mod, "resume_turn", fake_resume)

    await router_mod.route_approval_decision("gmail:m1", "telegram", {"approved": True})
    assert called["args"] == ("gmail:m1", "telegram", {"approved": True})
    assert "resumed" not in called  # the gmail: prefix short-circuits resume


async def test_router_resumes_non_channel_origin(monkeypatch):
    called: dict = {}

    async def fake_resume(**k):
        called["resumed"] = k
        return {"status": "interrupted"}  # interrupted → no channel send needed

    class _FakeCh:
        async def send_alert(self, text):  # pragma: no cover - not reached here
            called["alerted"] = text

    class _FakeRegistry:
        def get(self, platform):
            return _FakeCh()

    monkeypatch.setattr(router_mod, "resume_turn", fake_resume)
    monkeypatch.setattr(router_mod, "channel_registry", _FakeRegistry())
    await router_mod.route_approval_decision("telegram:42", "telegram", {"approved": True})
    assert called["resumed"]["thread_id"] == "telegram:42"  # fell through to resume
    assert "alerted" not in called  # interrupted status → no alert
