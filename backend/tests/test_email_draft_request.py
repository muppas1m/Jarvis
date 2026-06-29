"""Complex inbound email → heads-up card → "go" drafts + re-queues a simple card.

The dispatch-side of the routing change: a needs_drafting email card resolves to DRAFT
(not send) on approve, LEAVE on reject, never sends; a failed draft leaves no card. Plus
the unified-card shape (heads-up vs simple) and the edit-nudge (no draft to revise yet).
"""
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import app.agent.runner as runner
from app.agent.approval_dispatch import _dispatch_email_draft_request, dispatch_approval
from app.api.approvals import _unified_card


def _row(needs_drafting=True, draft="", body="Original email body.", status="pending"):
    return SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        thread_id="email:gmail:m1", interrupt_id="email:gmail:m1",
        action_type="email_reply", status=status,
        description="📧 A reply to 'Q3' from Priya needs your input — say the word and I'll draft it.",
        payload={"provider": "gmail", "message_id": "m1", "subject": "Q3", "sender": "Priya <p@x.com>",
                 "body": body, "draft": draft, "needs_drafting": needs_drafting},
        created_at=datetime.now(UTC),
    )


def _j(intent, *, needs_drafting=True, change=""):
    return runner._PresentedJudgment(
        approval_id="11111111-1111-1111-1111-111111111111",
        row=_row(needs_drafting=needs_drafting), intent=intent, change=change,
    )


# --- the unified-card shape ---------------------------------------------------
def test_unified_card_headsup_shows_original_not_draft():
    c = _unified_card(_row(needs_drafting=True, draft=""))
    assert c.needs_drafting is True and c.kind == "email"
    assert c.tool_args["original"] == "Original email body."
    assert "body" not in c.tool_args  # no draft to show yet


def test_unified_card_simple_shows_original_and_draft():
    c = _unified_card(_row(needs_drafting=False, draft="Drafted reply."))
    assert c.needs_drafting is False
    assert c.tool_args["original"] == "Original email body."  # the email being replied to
    assert c.tool_args["body"] == "Drafted reply."            # the draft


# --- the dispatch: go → draft + re-queue (never send) ------------------------
async def test_draft_request_approve_drafts_and_requeues(monkeypatch):
    gen = AsyncMock(return_value="A careful drafted reply.")
    rq = AsyncMock()
    monkeypatch.setattr("app.email.responder.generate_draft", gen)
    monkeypatch.setattr("app.email.inbound.requeue_drafted_email_card", rq)
    out = await _dispatch_email_draft_request(_row(), {"approved": True})
    assert out.kind == "draft_request" and out.status == "drafted" and out.success
    assert gen.await_count == 1                        # drafted on go
    assert rq.await_count == 1                         # re-queued a simple card
    assert rq.await_args[0][1] == "A careful drafted reply."  # the draft passed to re-queue


async def test_draft_request_reject_leaves_in_inbox(monkeypatch):
    gen, rq = AsyncMock(), AsyncMock()
    monkeypatch.setattr("app.email.responder.generate_draft", gen)
    monkeypatch.setattr("app.email.inbound.requeue_drafted_email_card", rq)
    out = await _dispatch_email_draft_request(_row(), {"approved": False})
    assert out.status == "left" and not out.success
    assert gen.await_count == 0 and rq.await_count == 0  # nothing drafted, nothing queued


async def test_draft_request_empty_draft_leaves_no_card(monkeypatch):
    monkeypatch.setattr("app.email.responder.generate_draft", AsyncMock(return_value="   "))
    rq = AsyncMock()
    monkeypatch.setattr("app.email.inbound.requeue_drafted_email_card", rq)
    out = await _dispatch_email_draft_request(_row(), {"approved": True})
    assert out.status == "draft_failed" and not out.success
    assert rq.await_count == 0  # no card on a failed/empty draft


async def test_dispatch_approval_routes_headsup_to_draft_not_send(monkeypatch):
    """A needs_drafting row must reach the DRAFT path, never the send handler."""
    monkeypatch.setattr("app.email.responder.generate_draft", AsyncMock(return_value="d"))
    monkeypatch.setattr("app.email.inbound.requeue_drafted_email_card", AsyncMock())
    sent = AsyncMock()
    monkeypatch.setattr("app.agent.approval_dispatch.dispatch_email_approval", sent)
    monkeypatch.setattr("app.agent.approval_dispatch._load_approval", AsyncMock(return_value=_row()))
    out = await dispatch_approval("11111111-1111-1111-1111-111111111111", {"approved": True})
    assert out.kind == "draft_request" and out.status == "drafted"
    assert sent.await_count == 0  # the SEND handler was NEVER called


# --- runner side: the heads-up property --------------------------------------
def test_judgment_needs_drafting_property():
    assert _j("approve", needs_drafting=True).needs_drafting is True
    assert _j("approve", needs_drafting=False).needs_drafting is False
# (the edit-on-headsup nudge moved into the graph — covered by card_resolution_node's
#  _card_edit_redraft "I can only send or discard" branch.)
