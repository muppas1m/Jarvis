"""Inbound-email approval resolution — the ONE shared core every transport drives,
now provider-agnostic. Covers the neutral payload + the LEGACY (gmail:) payload
compat, the send via the provider-neutral send_email (mocked), the stale-row
provider fetch, the exact channel-alert wording (Telegram regression guard), and
the router prefix-dispatch for BOTH email: and gmail: origins.
"""
# Importing the handler at collection pulls in app.email.send (which binds
# async_session at module scope) UNPATCHED — so a later async_session fake can't
# leak into the real send path (project_async_state_rebind_pattern sibling).
import app.messaging.router as router_mod
from app.email.approval_handler import (
    EMAIL_THREAD_PREFIXES,
    EmailApprovalOutcome,
    channel_alert_for,
    dispatch_email_approval,
    is_email_approval,
)
from app.email.provider import InboundMessage, SendResult

# New-shape payload (provider-tagged, neutral keys).
NEW_PAYLOAD = {
    "provider": "gmail",
    "message_id": "msg-123",
    "thread_ref": "thread-9",
    "rfc822_message_id": "<abc@mail>",
    "subject": "Project update",
    "sender": "Priya Rao <priya@example.com>",
    "draft": "Thanks Priya — confirmed for Thursday.",
}
# Legacy gmail: row (no provider, gmail_message_id key).
LEGACY_PAYLOAD = {
    "gmail_message_id": "msg-legacy",
    "rfc822_message_id": "<leg@mail>",
    "subject": "Old thread",
    "sender": "bob@example.com",
    "draft": "On it.",
}


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
    monkeypatch.setattr("app.db.engine.async_session", lambda: _FakeSession(row))


def _patch_send(monkeypatch, sink, *, raises=None):
    async def fake_send(to, subject, body, reply_to=None, *, source_message_id="", provider_name=""):
        sink.update(
            to=to, subject=subject, body=body, reply_to=reply_to,
            source_message_id=source_message_id, provider_name=provider_name,
        )
        if raises:
            raise raises
        return SendResult(provider=provider_name or "gmail", sent_message_id="sent-1")

    monkeypatch.setattr("app.email.approval_handler.send_email", fake_send)


def test_prefixes_and_predicate():
    assert EMAIL_THREAD_PREFIXES == ("email:", "gmail:")
    assert is_email_approval("email:gmail:abc") and is_email_approval("gmail:abc")
    assert not is_email_approval("web:master") and not is_email_approval("telegram:42")


# --- approve: sends via the neutral provider path with the right ReplyRef ----
async def test_approve_new_payload_sends_with_replyref(monkeypatch):
    sink: dict = {}
    _patch_row(monkeypatch, _Row(NEW_PAYLOAD))
    _patch_send(monkeypatch, sink)

    outcome = await dispatch_email_approval("email:gmail:msg-123", {"approved": True})

    assert outcome.status == "sent"
    assert outcome.recipient == "priya@example.com"  # parseaddr stripped the name
    assert outcome.subject == "Re: Project update"
    assert sink["to"] == "priya@example.com"
    assert sink["body"] == NEW_PAYLOAD["draft"]
    assert sink["source_message_id"] == "msg-123"
    assert sink["provider_name"] == "gmail"
    rr = sink["reply_to"]
    assert rr.provider == "gmail" and rr.message_id == "msg-123"
    assert rr.thread_ref == "thread-9" and rr.rfc822_message_id == "<abc@mail>"


async def test_approve_legacy_payload_still_resolves(monkeypatch):
    """A pre-generalization gmail: row (gmail_message_id key, no provider) must
    still send — backward-compat for the live pending row."""
    sink: dict = {}
    _patch_row(monkeypatch, _Row(LEGACY_PAYLOAD))
    _patch_send(monkeypatch, sink)
    outcome = await dispatch_email_approval("gmail:msg-legacy", {"approved": True})
    assert outcome.status == "sent"
    assert sink["source_message_id"] == "msg-legacy"  # read from gmail_message_id
    assert sink["provider_name"] == "gmail"  # defaulted
    assert sink["reply_to"].rfc822_message_id == "<leg@mail>"


async def test_reject_does_not_send(monkeypatch):
    sink: dict = {}
    _patch_send(monkeypatch, sink)
    outcome = await dispatch_email_approval("email:gmail:x", {"approved": False})
    assert outcome.status == "rejected" and sink == {}


async def test_row_missing_and_payload_incomplete(monkeypatch):
    sink: dict = {}
    _patch_send(monkeypatch, sink)
    _patch_row(monkeypatch, None)
    assert (await dispatch_email_approval("email:gmail:gone", {"approved": True})).status == "row_missing"
    _patch_row(monkeypatch, _Row({"message_id": "x"}))  # no draft/sender
    assert (await dispatch_email_approval("email:gmail:x", {"approved": True})).status == "payload_incomplete"
    assert sink == {}  # never sends on incomplete data


async def test_definite_send_failure_is_send_failed(monkeypatch):
    _patch_row(monkeypatch, _Row(NEW_PAYLOAD))
    _patch_send(monkeypatch, {}, raises=RuntimeError("smtp boom"))
    outcome = await dispatch_email_approval("email:gmail:msg-123", {"approved": True})
    assert outcome.status == "send_failed" and "smtp boom" in outcome.detail


async def test_uncertain_send_is_send_uncertain(monkeypatch):
    """A maybe-delivered send (EmailSendUncertain from the provider) maps to a
    DISTINCT outcome status, not a flat send_failed."""
    from app.email.provider import EmailSendUncertain

    _patch_row(monkeypatch, _Row(NEW_PAYLOAD))
    _patch_send(monkeypatch, {}, raises=EmailSendUncertain("timeout — may have gone out"))
    outcome = await dispatch_email_approval("email:gmail:msg-123", {"approved": True})
    assert outcome.status == "send_uncertain"
    assert "may have gone out" in outcome.detail


# --- stale-row: missing subject/rfc822 → fetched from the PROVIDER ------------
async def test_stale_row_fetches_headers_from_provider(monkeypatch):
    sink: dict = {}
    stale = {"provider": "gmail", "message_id": "msg-stale", "sender": "bob@example.com", "draft": "Sure."}
    _patch_row(monkeypatch, _Row(stale))
    _patch_send(monkeypatch, sink)

    class _Provider:
        async def fetch_message(self, mid):
            return InboundMessage(
                provider="gmail", message_id=mid, thread_ref="t-stale",
                rfc822_message_id="<stale@mail>", sender="bob@example.com",
                subject="Quick question", body="",
            )

    monkeypatch.setattr("app.email.approval_handler.get_email_provider", lambda name: _Provider())
    outcome = await dispatch_email_approval("email:gmail:msg-stale", {"approved": True})
    assert outcome.status == "sent" and outcome.subject == "Re: Quick question"
    assert sink["reply_to"].rfc822_message_id == "<stale@mail>"  # recovered


# --- channel alert wording (Telegram regression guard, unchanged) ------------
def test_channel_alert_wording_unchanged():
    assert channel_alert_for(EmailApprovalOutcome(status="rejected"), "email:gmail:x") is None
    sent = EmailApprovalOutcome(status="sent", recipient="p@x.com", subject="Re: Hi", detail="sent_id=1")
    assert channel_alert_for(sent, "x") == "✅ Reply sent to p@x.com\nSubject: Re: Hi\nsent_id=1"
    assert "wasn't found" in channel_alert_for(EmailApprovalOutcome(status="row_missing"), "email:gmail:a")
    assert "incomplete" in channel_alert_for(EmailApprovalOutcome(status="payload_incomplete"), "email:gmail:a")
    failed = EmailApprovalOutcome(status="send_failed", detail="boom")
    assert channel_alert_for(failed, "email:gmail:a") == "❌ Failed to send reply for `email:gmail:a`:\n```\nboom\n```"
    # maybe-delivered reads DISTINCTLY (not the definite ❌) — "couldn't confirm".
    uncertain = channel_alert_for(EmailApprovalOutcome(status="send_uncertain", recipient="p@x.com"), "x")
    assert "couldn't confirm" in uncertain.lower() and "sent folder" in uncertain.lower()
    assert "❌" not in uncertain  # not a flat failure


# --- router prefix-dispatch (both email: and legacy gmail:) ------------------
async def test_router_dispatches_email_and_gmail_prefixes(monkeypatch):
    called: list = []

    async def fake_handler(thread_id, platform, decision):
        called.append(thread_id)

    async def fake_resume(**k):
        called.append("RESUMED")
        return {"status": "interrupted"}

    for prefix in EMAIL_THREAD_PREFIXES:
        monkeypatch.setitem(router_mod.CHANNEL_ORIGIN_HANDLERS, prefix, fake_handler)
    monkeypatch.setattr(router_mod, "resume_turn", fake_resume)

    await router_mod.route_approval_decision("email:gmail:m1", "telegram", {"approved": True})
    await router_mod.route_approval_decision("gmail:legacy", "telegram", {"approved": True})
    assert called == ["email:gmail:m1", "gmail:legacy"]  # both → handler, neither resumed
