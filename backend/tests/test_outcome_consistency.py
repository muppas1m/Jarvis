"""Two regressions in the outcome-visibility work (5d9e79c):

  (1) The terminal status approved→executed broke email_history_search (it rendered the
      send-status off status=="approved" and filtered on a set lacking the new states) →
      a sent inbound reply read as garble there while approvals_pending said executed. Fix:
      both agree. Test: a SENT inbound reply reads consistently (both say "sent") in BOTH.
  (2) send_uncertain was mapped to executed → a clean ✅ "sent". EmailSendUncertain means the
      send could NOT be confirmed → a DISTINCT 'unconfirmed' outcome (⚠️), never a clean ✅.
"""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.agent.approval_dispatch import ApprovalDispatchOutcome, _terminal_outcome
from app.agent.tools.approvals_pending import approvals_pending
from app.agent.tools.email_history import _status_phrase, email_history_search
from app.approvals_service import UnifiedApprovalCard, render_outcomes_for_agent
from app.db.engine import async_session
from app.db.models import EmailLog, PendingApproval

_MARK = f"test-consist-{uuid.uuid4().hex[:8]}"


# ---- (2) send_uncertain → unconfirmed, never a clean ✅ ---------------------- #
def test_send_uncertain_maps_to_unconfirmed_not_executed():
    out = ApprovalDispatchOutcome(
        kind="email", status="send_uncertain",
        detail="timeout — it may have gone out", thread_id="email:gmail:x",
    )
    terminal = _terminal_outcome(out)
    assert terminal is not None
    status, _detail = terminal
    assert status == "unconfirmed" and status != "executed"


def test_unconfirmed_renders_warning_never_a_check():
    card = UnifiedApprovalCard(
        approval_id="a", kind="email", thread_id="email:gmail:x", tool_name="email_reply",
        tool_args={"to": "bob@x.com"}, description="d", status="unconfirmed", created_at="",
        outcome_detail="couldn't confirm the send", resolved_at=datetime.now(UTC).isoformat(),
    )
    out = render_outcomes_for_agent([card], "Sir")
    assert "⚠️" in out and "✅" not in out
    assert "couldn't confirm" in out.lower()


def test_email_history_unconfirmed_phrase_is_distinct():
    r = SimpleNamespace(approval_status="unconfirmed", resolved_at=datetime.now(UTC),
                        auto_sent=False, expires_at=None, response_complexity="simple", resolved_via=None)
    phrase = _status_phrase(r, datetime.now(UTC))
    assert "couldn't confirm" in phrase.lower()
    assert "sent" not in phrase.replace("may have sent", "")  # not a clean "sent"


# ---- (1) a sent inbound reply reads consistently in BOTH tools --------------- #
@pytest.mark.asyncio
async def test_sent_inbound_reply_consistent_across_both_outcome_tools():
    gmid = f"gmid-{_MARK}"
    thread_id = f"email:gmail:{_MARK}"
    async with async_session() as s:
        s.add(EmailLog(
            gmail_message_id=gmid, sender="Priya <priya@x.com>", subject="Q3 plan",
            classification="action_required", response_complexity="simple", auto_sent=True, meta={},
        ))
        s.add(PendingApproval(
            thread_id=thread_id, interrupt_id=f"i-{_MARK}", action_type="email_reply",
            description="reply to Priya", status="executed", outcome_detail="Reply sent to Priya",
            payload={"gmail_message_id": gmid, "sender": "Priya <priya@x.com>", "subject": "Q3 plan"},
            resolved_at=datetime.now(UTC), expires_at=datetime.now(UTC) + timedelta(hours=24),
        ))
        await s.commit()
    try:
        hist = (await email_history_search()).lower()
        appr = (await approvals_pending()).lower()

        # email_history_search: the reply reads as SENT (executed → "reply sent"), NOT the raw
        # "status=executed" garble and NOT stuck at "approved".
        assert "reply sent" in hist
        assert "status=executed" not in hist

        # approvals_pending: the SAME reply reads ✅ sent. Both tools AGREE it was sent.
        assert "✅" in await approvals_pending() and "priya" in appr
        assert "reply sent to priya" in appr
    finally:
        async with async_session() as s:
            await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
            await s.execute(delete(EmailLog).where(EmailLog.gmail_message_id == gmid))
            await s.commit()
