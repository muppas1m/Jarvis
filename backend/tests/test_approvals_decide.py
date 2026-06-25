"""The dashboard decide endpoint resolves through the ONE claim-then-dispatch
gate (Phase 3), unified across every origin.

`decide_approval` no longer branches gmail→dispatch / else→resume. It calls
`resolve_and_dispatch(approval_id, action, "web", decision)` — which atomically
claims the row and executes out-of-band — then renders the outcome by `kind`:
an inbound-email outcome through the maybe-delivered taxonomy, a chat-queued tool
outcome through its deterministic result, and a lost claim → 404. These tests
mock the gate (no DB / Gmail / tool execution) and assert the rendered envelope.
"""
import pytest
from fastapi import HTTPException

import app.api.approvals as ap
from app.agent.approval_dispatch import ApprovalDispatchOutcome
from app.email.approval_handler import EmailApprovalOutcome


def _patch_gate(monkeypatch, outcome):
    """Patch the gate decide_approval calls; record (approval_id, action, via)."""
    rec: dict = {}

    async def fake_rad(approval_id, action, resolved_via, decision):
        rec["call"] = (approval_id, action, resolved_via, decision)
        return outcome

    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", fake_rad)
    return rec


def _email_outcome(eo, thread_id="email:gmail:m1"):
    return ApprovalDispatchOutcome(
        kind="email", status=eo.status, success=(eo.status == "sent"),
        thread_id=thread_id, email_outcome=eo,
    )


async def test_email_approve_renders_sent(monkeypatch):
    eo = EmailApprovalOutcome(status="sent", recipient="priya@example.com", subject="Re: Hi")
    rec = _patch_gate(monkeypatch, _email_outcome(eo))

    env = await ap.decide_approval(ap.DecideRequest(approved=True), "uuid-1")

    assert rec["call"] == ("uuid-1", "approve", "web", {"approved": True})  # claim-gated
    assert env["status"] == "complete"
    assert "priya@example.com" in env["response"]
    assert env["interrupt"] is None


async def test_email_reject_renders_discarded(monkeypatch):
    rec = _patch_gate(monkeypatch, _email_outcome(EmailApprovalOutcome(status="rejected")))
    env = await ap.decide_approval(ap.DecideRequest(approved=False, reason="no thanks"), "u2")
    assert rec["call"][1] == "reject" and rec["call"][3] == {"approved": False, "reason": "no thanks"}
    assert env["status"] == "complete"
    assert "inbox" in env["response"].lower()


async def test_email_send_failure_renders_error(monkeypatch):
    eo = EmailApprovalOutcome(status="send_failed", detail="token expired")
    _patch_gate(monkeypatch, _email_outcome(eo))
    env = await ap.decide_approval(ap.DecideRequest(approved=True), "u3")
    assert env["status"] == "error"
    assert "token expired" in env["response"]


async def test_email_send_uncertain_renders_distinctly(monkeypatch):
    """Maybe-delivered (dashboard transport): NOT a flat error — soft + honest."""
    eo = EmailApprovalOutcome(status="send_uncertain", recipient="p@x.com")
    _patch_gate(monkeypatch, _email_outcome(eo))
    env = await ap.decide_approval(ap.DecideRequest(approved=True), "u4")
    assert env["status"] == "complete"  # not the red "error" of a definite fail
    assert "couldn't confirm" in env["response"].lower()
    assert "sent folder" in env["response"].lower()


async def test_tool_approve_renders_deterministic_result(monkeypatch):
    """A chat-queued TOOL approval executes out-of-band and renders the tool's own
    result string (no resume) — the path that USED to call resume_turn."""
    outcome = ApprovalDispatchOutcome(
        kind="tool", status="executed", detail="Event created: Standup 9am",
        success=True, thread_id="web:master",
    )
    rec = _patch_gate(monkeypatch, outcome)
    env = await ap.decide_approval(ap.DecideRequest(approved=True), "uuid-x")
    assert rec["call"] == ("uuid-x", "approve", "web", {"approved": True})
    assert env["status"] == "complete"
    assert env["response"] == "Event created: Standup 9am"


async def test_tool_now_blocked_renders_not_permitted(monkeypatch):
    """Defense-in-depth: a tool that became BLOCKED since queuing is refused."""
    outcome = ApprovalDispatchOutcome(kind="tool", status="blocked", thread_id="web:master")
    _patch_gate(monkeypatch, outcome)
    env = await ap.decide_approval(ap.DecideRequest(approved=True), "uuid-b")
    assert env["status"] == "error"
    assert "isn't permitted" in env["response"].lower()


async def test_lost_claim_is_404(monkeypatch):
    """not_claimed (bad UUID / gone / already resolved / EXPIRED) → 404, no execute."""
    _patch_gate(monkeypatch, ApprovalDispatchOutcome(kind="none", status="not_claimed"))
    with pytest.raises(HTTPException) as ei:
        await ap.decide_approval(ap.DecideRequest(approved=True), "gone")
    assert ei.value.status_code == 404
