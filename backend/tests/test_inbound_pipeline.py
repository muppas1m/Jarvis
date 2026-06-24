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

    async def search(self, *a, **k):
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


def _triage(classification: str, confidence: float = 0.95) -> EmailTriageResult:
    return EmailTriageResult(
        classification=classification, urgency="none", intent="fyi",
        confidence=confidence, suggested_action="none",
    )


async def _cleanup(mid: str):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == f"email:fakemail:{mid}"))
        await s.execute(delete(EmailLog).where(EmailLog.gmail_message_id == mid))
        await s.commit()


async def test_spam_archives_via_provider_interface(monkeypatch):
    mid = f"pipe-spam-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr("app.email.inbound.classify_email", AsyncMock(return_value=_triage("spam")))
    monkeypatch.setattr("app.email.inbound.add_to_digest", AsyncMock())
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        assert p.archived == [mid]  # archived via the INTERFACE, not any Gmail call
    finally:
        await _cleanup(mid)


async def test_action_required_mints_provider_tagged_approval(monkeypatch):
    mid = f"pipe-act-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(
        "app.email.inbound.classify_email", AsyncMock(return_value=_triage("action_required"))
    )
    monkeypatch.setattr(
        "app.email.inbound.generate_draft",
        AsyncMock(return_value={"complexity": "simple", "response": "Drafted reply."}),
    )
    monkeypatch.setattr("app.email.inbound.send_approval_request_to_master", AsyncMock())
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        async with async_session() as s:
            approval = (await s.execute(
                select(PendingApproval).where(PendingApproval.thread_id == f"email:fakemail:{mid}")
            )).scalar_one_or_none()
        assert approval is not None
        assert approval.action_type == "email_reply"
        # neutral, provider-tagged payload — the approval handler reads THIS shape
        assert approval.payload["provider"] == "fakemail"
        assert approval.payload["message_id"] == mid
        assert approval.payload["rfc822_message_id"] == "<x@fakemail>"
        assert approval.payload["draft"] == "Drafted reply."
        assert p.archived == []  # action_required is NOT archived
    finally:
        await _cleanup(mid)


async def test_low_confidence_spam_downgrades_to_digest_not_archive(monkeypatch):
    mid = f"pipe-lowspam-{uuid.uuid4().hex[:10]}"
    monkeypatch.setattr(
        "app.email.inbound.classify_email", AsyncMock(return_value=_triage("spam", confidence=0.1))
    )
    digest = AsyncMock()
    monkeypatch.setattr("app.email.inbound.add_to_digest", digest)
    p = _FakeProvider()
    try:
        await _process_message(p, _msg(mid))
        assert p.archived == []  # low-confidence spam is NOT archived
        assert digest.await_count == 1  # routed to digest so a misclassified real email stays visible
    finally:
        await _cleanup(mid)
