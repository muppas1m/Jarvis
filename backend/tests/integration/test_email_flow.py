"""Turn 20.5b task v — end-to-end email flow integration test.

Drives the REAL pipeline from a simulated inbound email through to a sent reply,
mocking only at the Google-API + Telegram boundaries (item #5), so the test
exercises the actual plumbing:
  - the 16.5 INSERT-as-gate (EmailLog claims the msg_id before side effects),
  - PendingApproval creation,
  - approve → approval_handler.dispatch_email_approval → send_email → provider,
  - the real MIME / In-Reply-To threading built by gmail_send,
  - the EmailLog.auto_sent flip + the gmail_send AuditTrail row.

Assertions are on DB STATE TRANSITIONS + the payload the mocked Google client
received, NOT on LLM wording (item #4). The two LLM decision points (classify +
draft) are mocked to fixed outputs so the FLOW BRANCH is deterministic — draft
complexity is LLM-decided, and v tests the plumbing, not classification (the eval
+ classifier smoke cover that). With both mocked, v makes no real LLM calls.

Real Postgres + Redis; only Google + Telegram are mocked.
"""
import base64
import email as email_lib
import uuid
from email.utils import parseaddr
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import delete, select

from app.db.engine import async_session
from app.db.models import AuditTrail, EmailLog, PendingApproval
from app.email.classifier import EmailTriageResult


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _make_gmail_service(email_dict: dict) -> tuple[MagicMock, list]:
    """Mock Gmail service. get() returns email_dict; send() records the body."""
    sent: list[dict] = []

    def _send(userId, body):  # noqa: N803, ARG001
        sent.append(body)
        m = MagicMock()
        m.execute.return_value = {"id": "sent-msg-123"}
        return m

    messages = MagicMock()
    messages.get.return_value.execute.return_value = email_dict
    messages.send.side_effect = _send
    service = MagicMock()
    service.users.return_value.messages.return_value = messages
    return service, sent


@pytest.mark.asyncio
async def test_inbound_action_email_to_sent_reply(_rebind_async_state) -> None:
    from app.api.approvals import DecideRequest, decide_approval
    from app.email.inbound import _process_message
    from app.email.provider import GmailProvider

    msg_id = f"vtest-{uuid.uuid4().hex[:12]}"
    rfc822_id = f"<orig-{uuid.uuid4().hex[:8]}@example.com>"
    sender = "Bob Tester <bob@example.com>"
    subject = "Quick question about the report"
    draft_body = "Hi Bob, yes — I'll send the report shortly. Thanks!"

    email_dict = {
        "id": msg_id,
        "threadId": "thread-abc-123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "Message-ID", "value": rfc822_id},
            ],
            "parts": [
                {"mimeType": "text/plain", "body": {"data": _b64url("Can you send me the report?")}},
            ],
        },
    }
    service, sent_payloads = _make_gmail_service(email_dict)

    triage = EmailTriageResult(
        classification="action_required", urgency="today", intent="request",
        confidence=0.9, suggested_action="reply",
    )

    try:
        with patch("app.email.inbound.classify_email", AsyncMock(return_value=triage)), \
             patch("app.email.inbound.generate_draft",
                   AsyncMock(return_value={"complexity": "simple", "response": draft_body})), \
             patch("app.email.inbound.send_approval_request_to_master", AsyncMock()) as mock_req, \
             patch("app.email.inbound.send_system_alert", AsyncMock()) as mock_sys_alert, \
             patch("app.email.provider.gmail.GmailProvider._service", return_value=service):

            # ---- inbound: provider fetch → classify (mocked) → draft (mocked) →
            #      EmailLog gate → queue approval. Drives the REAL pipeline through
            #      the provider interface (fetch_message maps the Gmail payload). ----
            provider = GmailProvider()
            msg = await provider.fetch_message(msg_id)
            await _process_message(provider, msg)

            async with async_session() as s:
                log = (await s.execute(
                    select(EmailLog).where(EmailLog.gmail_message_id == msg_id)
                )).scalar_one_or_none()
            assert log is not None, "EmailLog row not created (INSERT-as-gate didn't claim the msg)"
            assert log.classification == "action_required"
            assert log.draft_response == draft_body
            assert log.auto_sent is False, "auto_sent should be False before approval"

            async with async_session() as s:
                approval = (await s.execute(
                    select(PendingApproval).where(PendingApproval.thread_id == f"email:gmail:{msg_id}")
                )).scalar_one_or_none()
            assert approval is not None, "PendingApproval not created for the action email"
            assert approval.status == "pending"
            assert approval.action_type == "email_reply"  # provider-tagged shape
            assert approval.payload["provider"] == "gmail"
            assert mock_req.await_count == 1, "master should have been asked to approve exactly once"
            assert mock_sys_alert.await_count == 0, "simple-draft path must NOT emit a system alert"

            # ---- master approves via the LIVE dashboard endpoint → the claim-gated
            #      gate (resolve_and_dispatch) → dispatch_approval → dispatch_email_approval
            #      → send_email → provider → mocked send(). The REAL production path,
            #      exactly what the dashboard Approve button drives. ----
            env = await decide_approval(DecideRequest(approved=True), str(approval.id))
            assert env["status"] == "complete"
            assert "bob@example.com" in env["response"]  # "✅ Reply sent to bob@example.com"

        # ---- assert the mocked Google client got the correct MIME / threading ----
        assert len(sent_payloads) == 1, f"expected exactly one send, got {len(sent_payloads)}"
        raw = sent_payloads[0]["raw"]
        assert sent_payloads[0].get("threadId") == "thread-abc-123", "reply should set threadId for same-conversation"
        mime = email_lib.message_from_bytes(base64.urlsafe_b64decode(raw))
        assert parseaddr(mime["To"])[1] == "bob@example.com"
        assert mime["Subject"].lower().startswith("re:")
        assert mime["In-Reply-To"] == rfc822_id, "In-Reply-To must thread to the original Message-ID"
        assert draft_body in mime.get_payload(decode=True).decode("utf-8")

        # ---- assert DB closed the loop: auto_sent flipped + audit row written ----
        async with async_session() as s:
            log = (await s.execute(
                select(EmailLog).where(EmailLog.gmail_message_id == msg_id)
            )).scalar_one()
            audit = (await s.execute(
                select(AuditTrail).where(AuditTrail.thread_id == f"email:gmail:{msg_id}")
            )).scalars().all()
        assert log.auto_sent is True, "EmailLog.auto_sent must flip True after a successful send"
        send_rows = [a for a in audit if a.tool_name == "email_send" and a.success]
        assert send_rows, "a successful email_send AuditTrail row should exist"
        assert send_rows[0].latency_ms is not None, "email_send audit should carry latency_ms (17.9)"
    finally:
        async with async_session() as s:
            await s.execute(delete(AuditTrail).where(AuditTrail.thread_id == f"email:gmail:{msg_id}"))
            await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == f"email:gmail:{msg_id}"))
            await s.execute(delete(EmailLog).where(EmailLog.gmail_message_id == msg_id))
            await s.commit()
