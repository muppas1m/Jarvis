"""The dashboard decide endpoint must origin-dispatch like the Telegram button.

A gmail: approval has no graph to resume; the old endpoint called resume_turn
unconditionally → it failed for inbound email approvals. Now it branches:
gmail: → dispatch_email_approval (send the reply), else → resume_turn. These
tests assert the BRANCH + the rendered envelope, mocking resolve_approval /
dispatch / resume so no DB or Gmail is touched (axis b: verify invocation).
"""
import pytest
from fastapi import HTTPException

import app.api.approvals as ap
from app.email.approval_handler import EmailApprovalOutcome


def _patch(monkeypatch, *, thread_id, dispatch=None, resume=None):
    async def fake_resolve(**k):
        return thread_id

    monkeypatch.setattr(ap, "resolve_approval", fake_resolve)
    if dispatch is not None:
        monkeypatch.setattr(ap, "dispatch_email_approval", dispatch)
    if resume is not None:
        monkeypatch.setattr(ap, "resume_turn", resume)


async def test_gmail_approval_dispatches_send_not_resume(monkeypatch):
    captured: dict = {}

    async def fake_dispatch(thread_id, decision):
        captured["dispatch"] = (thread_id, decision)
        return EmailApprovalOutcome(
            status="sent", recipient="priya@example.com", subject="Re: Hi", detail="id=1"
        )

    async def fake_resume(**k):
        captured["resumed"] = True
        return {"status": "complete"}

    _patch(monkeypatch, thread_id="gmail:msg-1", dispatch=fake_dispatch, resume=fake_resume)

    env = await ap.decide_approval(ap.DecideRequest(approved=True), "uuid-1")

    assert captured["dispatch"] == ("gmail:msg-1", {"approved": True})
    assert "resumed" not in captured  # gmail path never resumes a graph
    assert env["status"] == "complete"
    assert "priya@example.com" in env["response"]
    assert env["interrupt"] is None


async def test_gmail_reject_renders_discarded(monkeypatch):
    async def fake_dispatch(thread_id, decision):
        assert decision["approved"] is False  # reject flows through as not-approved
        return EmailApprovalOutcome(status="rejected")

    _patch(monkeypatch, thread_id="gmail:msg-2", dispatch=fake_dispatch)
    env = await ap.decide_approval(ap.DecideRequest(approved=False, reason="no thanks"), "u2")
    assert env["status"] == "complete"
    assert "inbox" in env["response"].lower()


async def test_gmail_send_failure_renders_error(monkeypatch):
    async def fake_dispatch(thread_id, decision):
        return EmailApprovalOutcome(status="send_failed", detail="token expired")

    _patch(monkeypatch, thread_id="gmail:msg-3", dispatch=fake_dispatch)
    env = await ap.decide_approval(ap.DecideRequest(approved=True), "u3")
    assert env["status"] == "error"
    assert "token expired" in env["response"]


async def test_gmail_send_uncertain_renders_distinctly(monkeypatch):
    """Maybe-delivered (dashboard transport): NOT a flat error — soft + honest."""
    async def fake_dispatch(thread_id, decision):
        return EmailApprovalOutcome(status="send_uncertain", recipient="p@x.com")

    _patch(monkeypatch, thread_id="gmail:msg-4", dispatch=fake_dispatch)
    env = await ap.decide_approval(ap.DecideRequest(approved=True), "u4")
    assert env["status"] == "complete"  # not the red "error" of a definite fail
    assert "couldn't confirm" in env["response"].lower()
    assert "sent folder" in env["response"].lower()


async def test_conversation_approval_still_resumes(monkeypatch):
    captured: dict = {}

    async def fake_dispatch(thread_id, decision):
        captured["dispatched"] = True
        return EmailApprovalOutcome(status="sent")

    async def fake_resume(thread_id, decision):
        captured["resume"] = (thread_id, decision)
        return {"status": "complete", "response": "Done, Sir."}

    _patch(monkeypatch, thread_id="web:master", dispatch=fake_dispatch, resume=fake_resume)

    env = await ap.decide_approval(ap.DecideRequest(approved=True), "uuid-x")
    assert captured["resume"][0] == "web:master"  # fell through to resume
    assert "dispatched" not in captured  # gmail dispatch NOT used for conversation
    assert env["response"] == "Done, Sir."


async def test_missing_approval_is_404(monkeypatch):
    _patch(monkeypatch, thread_id=None)  # resolve_approval → None (row gone)
    with pytest.raises(HTTPException) as ei:
        await ap.decide_approval(ap.DecideRequest(approved=True), "gone")
    assert ei.value.status_code == 404
