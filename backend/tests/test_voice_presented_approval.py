"""Hands-free voice resolution of a CROSS-THREAD presented approval (gap 3).

An inbound email reply card lives on its own gmail:<msg_id> thread, so the
conversation thread isn't "awaiting" — voice_turn resolves it against the
PRESENTED card via the same conservative resolve_decision. These tests assert
the right card is resolved, the shared gmail dispatch is invoked on approve, and
— the safety axis (d) — that an ambient / unrelated utterance NEVER dispatches
and leaves the card pending.
"""
import app.agent.runner as runner
from app.agent.decision_resolver import DecisionResolution
from app.email.approval_handler import EmailApprovalOutcome


class _Row:
    def __init__(self, status="pending", thread_id="gmail:msg-1"):
        self.id = "uuid-1"
        self.thread_id = thread_id
        self.status = status
        self.action_type = "gmail_reply"
        self.description = "Reply to 'Q3' from Priya"
        self.payload = {"sender": "Priya <p@x.com>", "subject": "Q3", "draft": "On it."}


def _wire(monkeypatch, *, row, intent, outcome=None, change="", claimed=True):
    """Patch the resolver's collaborators. Records the generic-gate call.
    Phase 3: the voice resolver now goes through `resolve_and_dispatch` (the same
    claim-then-dispatch gate every transport uses), NOT a voice-only claim +
    `dispatch_email_approval`. ``claimed`` simulates whether THIS call won the
    atomic claim (not_claimed → a concurrent transport already resolved it)."""
    from app.agent.approval_dispatch import ApprovalDispatchOutcome

    rec: dict = {}
    thread_id = row.thread_id if row else ""

    async def fake_load(_id):
        return row

    async def fake_resolve_decision(tool_name, tool_args, description, transcript):
        rec["judged"] = {"tool_args": tool_args, "transcript": transcript}
        return DecisionResolution(intent=intent, change=change)

    async def fake_rad(approval_id, action, resolved_via, decision):
        rec["resolved"] = (approval_id, action, resolved_via, decision)
        if not claimed:
            return ApprovalDispatchOutcome(kind="none", status="not_claimed")
        if action == "reject":
            return ApprovalDispatchOutcome(kind="email", status="rejected", thread_id=thread_id)
        eo = outcome or EmailApprovalOutcome(status="sent", recipient="p@x.com")
        return ApprovalDispatchOutcome(
            kind="email", status=eo.status, success=(eo.status == "sent"),
            thread_id=thread_id, email_outcome=eo,
        )

    async def fake_synth(text):
        rec.setdefault("spoken", []).append(text)
        return b"AUDIO"

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_resolve_decision)
    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", fake_rad)
    monkeypatch.setattr(runner, "synthesize", fake_synth)
    return rec


async def _collect(agen):
    return [ev async for ev in agen]


def _resolved_status(events):
    for ev in events:
        if ev["type"] == "decision_resolved":
            return ev["content"]["status"]
    return None


async def test_approve_dispatches_and_flips_card(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="approve")
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "yes send it"))

    # the ONE generic gate, with the voice transport + approve decision
    assert rec["resolved"] == ("uuid-1", "approve", "voice", {"approved": True})
    assert _resolved_status(events) == "approved"  # card flips
    assert any(e["type"] == "audio" for e in events)  # spoke the outcome
    assert events[-1]["type"] == "done"
    # judged against THIS card's content, not a blank action
    assert rec["judged"]["tool_args"]["subject"] == "Q3"


async def test_approve_with_send_failure_still_flips_but_says_failed(monkeypatch):
    rec = _wire(
        monkeypatch, row=_Row(), intent="approve",
        outcome=EmailApprovalOutcome(status="send_failed", detail="token expired"),
    )
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "send it"))
    assert rec["resolved"][1] == "approve"  # the gate was invoked
    assert _resolved_status(events) == "approved"  # the master DID approve
    assert any("couldn't be sent" in t for t in rec["spoken"])  # honest about delivery


async def test_reject_marks_and_does_not_dispatch(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="reject")
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "no, discard it"))
    assert rec["resolved"][:3] == ("uuid-1", "reject", "voice")
    assert _resolved_status(events) == "rejected"
    assert any("Discarded" in t for t in rec["spoken"])  # reject never sends


async def test_ambient_unrelated_never_dispatches_or_resolves(monkeypatch):
    """The gate (axis d): an unrelated / ambient utterance leaves the card pending
    — no send, no status flip — just a nudge."""
    rec = _wire(monkeypatch, row=_Row(), intent="unrelated")
    events = await _collect(
        runner._resolve_presented_approval_voice("uuid-1", "what's the weather today")
    )
    assert "resolved" not in rec  # the gate is NEVER reached on ambient speech
    assert _resolved_status(events) is None  # card stays pending (no flip)
    assert any(e["type"] == "audio" for e in events)  # but Jarvis nudges
    assert events[-1]["type"] == "done"


async def test_edit_keeps_pending_with_constraint_nudge(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="edit", change="make it shorter")
    events = await _collect(
        runner._resolve_presented_approval_voice("uuid-1", "make it shorter")
    )
    assert "resolved" not in rec  # edit never claims/dispatches
    assert _resolved_status(events) is None  # not supported this slice → stays pending
    assert any("send or discard" in t for t in rec["spoken"])


async def test_stale_card_acknowledges_and_ends(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(status="approved"), intent="approve")
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "send it"))
    assert "resolved" not in rec  # already resolved → the gate is never reached
    assert _resolved_status(events) is None
    assert events[-1]["type"] == "done"


async def test_missing_row_acknowledges_and_ends(monkeypatch):
    rec = _wire(monkeypatch, row=None, intent="approve")
    events = await _collect(runner._resolve_presented_approval_voice("gone", "send it"))
    assert "resolved" not in rec
    assert events[-1]["type"] == "done"


async def test_voice_judge_fails_open_nudges_no_crash(monkeypatch):
    """A judge failure (DB raise) must fail open: voice nudges, never sends, and
    the row=None case doesn't crash the nudge path."""
    rec = _wire(monkeypatch, row=_Row(), intent="approve")

    async def boom(_id):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(runner, "_load_approval_by_id", boom)  # judge fails open
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "send it"))
    assert "resolved" not in rec  # NEVER reaches the gate on a failed-open judge
    assert _resolved_status(events) is None  # card stays pending (nudge, no flip)
    assert any(e["type"] == "audio" for e in events)  # nudged
    assert events[-1]["type"] == "done"


async def test_voice_approve_lost_claim_does_not_double_send(monkeypatch):
    """B1: a button-decide already claimed + sent this card; the voice approve
    that follows must NOT send again (the atomic claim returns not_claimed)."""
    rec = _wire(monkeypatch, row=_Row(), intent="approve", claimed=False)
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "send it"))
    assert rec["resolved"][1] == "approve"  # the gate WAS asked — and lost the claim
    assert _resolved_status(events) is None  # not_claimed → no card flip, no second send
    assert events[-1]["type"] == "done"
