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


def _wire(monkeypatch, *, row, intent, outcome=None, change=""):
    """Patch the resolver's collaborators. Records dispatch + resolve calls."""
    rec: dict = {}

    async def fake_load(_id):
        return row

    async def fake_resolve_decision(tool_name, tool_args, description, transcript):
        rec["judged"] = {"tool_args": tool_args, "transcript": transcript}
        return DecisionResolution(intent=intent, change=change)

    async def fake_dispatch(thread_id, decision):
        rec["dispatch"] = (thread_id, decision)
        return outcome or EmailApprovalOutcome(status="sent", recipient="p@x.com")

    async def fake_resolve_row(approval_id, action):
        rec["resolved"] = (approval_id, action)

    async def fake_synth(text):
        rec.setdefault("spoken", []).append(text)
        return b"AUDIO"

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_resolve_decision)
    monkeypatch.setattr(runner, "_resolve_presented_row", fake_resolve_row)
    monkeypatch.setattr(runner, "synthesize", fake_synth)
    monkeypatch.setattr(
        "app.email.approval_handler.dispatch_email_approval", fake_dispatch
    )
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

    assert rec["dispatch"] == ("gmail:msg-1", {"approved": True})  # shared core invoked
    assert rec["resolved"] == ("uuid-1", "approve")  # marked approved (resolved_via=voice)
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
    assert "dispatch" in rec
    assert _resolved_status(events) == "approved"  # the master DID approve
    assert any("couldn't be sent" in t for t in rec["spoken"])  # honest about delivery


async def test_reject_marks_and_does_not_dispatch(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="reject")
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "no, discard it"))
    assert rec["resolved"] == ("uuid-1", "reject")
    assert "dispatch" not in rec  # reject never sends
    assert _resolved_status(events) == "rejected"


async def test_ambient_unrelated_never_dispatches_or_resolves(monkeypatch):
    """The gate (axis d): an unrelated / ambient utterance leaves the card pending
    — no send, no status flip — just a nudge."""
    rec = _wire(monkeypatch, row=_Row(), intent="unrelated")
    events = await _collect(
        runner._resolve_presented_approval_voice("uuid-1", "what's the weather today")
    )
    assert "dispatch" not in rec  # NEVER sends on ambient speech
    assert "resolved" not in rec  # card not marked
    assert _resolved_status(events) is None  # card stays pending (no flip)
    assert any(e["type"] == "audio" for e in events)  # but Jarvis nudges
    assert events[-1]["type"] == "done"


async def test_edit_keeps_pending_with_constraint_nudge(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="edit", change="make it shorter")
    events = await _collect(
        runner._resolve_presented_approval_voice("uuid-1", "make it shorter")
    )
    assert "dispatch" not in rec
    assert _resolved_status(events) is None  # not supported this slice → stays pending
    assert any("send or discard" in t for t in rec["spoken"])


async def test_stale_card_acknowledges_and_ends(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(status="approved"), intent="approve")
    events = await _collect(runner._resolve_presented_approval_voice("uuid-1", "send it"))
    assert "dispatch" not in rec  # already resolved → no action
    assert "resolved" not in rec
    assert _resolved_status(events) is None
    assert events[-1]["type"] == "done"


async def test_missing_row_acknowledges_and_ends(monkeypatch):
    rec = _wire(monkeypatch, row=None, intent="approve")
    events = await _collect(runner._resolve_presented_approval_voice("gone", "send it"))
    assert "dispatch" not in rec
    assert events[-1]["type"] == "done"
