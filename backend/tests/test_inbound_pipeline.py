"""The inbound pipeline is provider-agnostic — it drives a FAKE provider (not
Gmail) through the EmailProvider interface. Spam routes to provider.archive();
an action_required email mints a provider-TAGGED approval (email:<provider>:<id>)
with neutral payload keys. Real DB for the EmailLog gate + approval row (cleaned
up in finally); classify/draft are mocked to fix the branch.
"""
import uuid
from unittest.mock import AsyncMock

from sqlalchemy import delete, select

from app.db.engine import async_session
from app.db.models import EmailLog, PendingApproval
from app.email.classifier import EmailTriageResult
from app.email.inbound import _process_message
from app.email.provider import EmailProvider, InboundMessage


class _FakeProvider(EmailProvider):
    """A non-Gmail adapter, just enough to prove the pipeline calls the INTERFACE.
    Unused methods raise — if the pipeline reached for Gmail directly (or an
    unstubbed method) the test would fail loudly."""

    name = "fakemail"

    def __init__(self):
        self.archived: list[str] = []

    async def archive(self, message_id: str) -> None:
        self.archived.append(message_id)

    async def send(self, *a, **k):
        raise NotImplementedError

    async def fetch_message(self, message_id: str):
        raise NotImplementedError

    async def list_recent_message_ids(self, cursor=None):
        raise NotImplementedError

    async def setup_watch(self):
        raise NotImplementedError

    async def stop_watch(self):
        raise NotImplementedError

    def parse_push(self, push_payload):
        raise NotImplementedError


def _msg(mid: str) -> InboundMessage:
    return InboundMessage(
        provider="fakemail", message_id=mid, thread_ref="conv-1",
        rfc822_message_id="<x@fakemail>", sender="Carol <carol@fake.com>",
        subject="Hello", body="some text",
    )


def _triage(classification: str, confidence: float = 0.95, reply_effort: str = "simple") -> EmailTriageResult:
    return EmailTriageResult(
        classification=classification, urgency="none", intent="fyi",
        confidence=confidence, suggested_action="none", reply_effort=reply_effort,
    )


async def _cleanup(mid: str):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == f"email:fakemail:{mid}"))
        await s.execute(delete(EmailLog).where(EmailLog.gmail_message_id == mid))
        await s.commit()


async def test_spam_archives_via_provider_interface(monkeypatch):
    mid = f"pipe-spam-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr("app.email.inbound.classify_email", AsyncMock(return_value=_triage("spam")))
    monkeypatch.setattr("app.email.inbound.record_briefing_item", AsyncMock())
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        assert p.archived == [mid]  # archived via the INTERFACE, not any Gmail call
    finally:
        await _cleanup(mid)


async def test_simple_action_required_drafts_and_queues_with_original(monkeypatch):
    mid = f"pipe-act-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(
        "app.email.inbound.classify_email",
        AsyncMock(return_value=_triage("action_required", reply_effort="simple")),
    )
    gen = AsyncMock(return_value="Drafted reply.")  # generate_draft → a STRING now
    monkeypatch.setattr("app.email.inbound.generate_draft", gen)
    monkeypatch.setattr("app.email.inbound.send_approval_request_to_master", AsyncMock())
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        async with async_session() as s:
            approval = (await s.execute(
                select(PendingApproval).where(PendingApproval.thread_id == f"email:fakemail:{mid}")
            )).scalar_one_or_none()
        assert approval is not None and approval.action_type == "email_reply"
        assert approval.payload["provider"] == "fakemail"
        assert approval.payload["message_id"] == mid
        assert approval.payload["rfc822_message_id"] == "<x@fakemail>"
        assert approval.payload["draft"] == "Drafted reply."
        assert approval.payload["needs_drafting"] is False
        assert approval.payload["body"] == "some text"  # the ORIGINAL email rides on the card
        assert gen.await_count == 1                       # a simple one IS drafted
        assert p.archived == []
    finally:
        await _cleanup(mid)


async def test_complex_action_required_queues_headsup_without_drafting(monkeypatch):
    mid = f"pipe-cplx-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(
        "app.email.inbound.classify_email",
        AsyncMock(return_value=_triage("action_required", reply_effort="complex")),
    )
    gen = AsyncMock(return_value="should NOT be called")
    monkeypatch.setattr("app.email.inbound.generate_draft", gen)
    monkeypatch.setattr("app.email.inbound.send_approval_request_to_master", AsyncMock())
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        async with async_session() as s:
            approval = (await s.execute(
                select(PendingApproval).where(PendingApproval.thread_id == f"email:fakemail:{mid}")
            )).scalar_one_or_none()
        assert approval is not None and approval.action_type == "email_reply"
        assert approval.payload["needs_drafting"] is True   # a heads-up card
        assert approval.payload["draft"] == ""              # NO draft
        assert approval.payload["body"] == "some text"      # original carried for the on-go re-draft
        assert "say the word and I'll draft it" in approval.description
        assert gen.await_count == 0                          # NO wasted drafting on a complex one
        assert p.archived == []
    finally:
        await _cleanup(mid)


async def test_low_confidence_spam_downgrades_to_digest_not_archive(monkeypatch):
    mid = f"pipe-lowspam-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(
        "app.email.inbound.classify_email", AsyncMock(return_value=_triage("spam", confidence=0.1))
    )
    digest = AsyncMock()
    monkeypatch.setattr("app.email.inbound.record_briefing_item", digest)
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        assert p.archived == []  # low-confidence spam is NOT archived
        assert digest.await_count == 1  # routed to the briefing so a misclassified real email stays visible
    finally:
        await _cleanup(mid)
