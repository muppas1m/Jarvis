"""Part B2: a typed "send it" resolves a presented inbound card in the TEXT turn
— the same gated cross-thread resolution the voice path uses, minus audio. Mirror
of the voice test: approve dispatches the shared core (idempotently claimed),
reject marks without sending, and ambient/unrelated leaves the card pending.
"""
import app.agent.runner as runner
from app.agent.decision_resolver import DecisionResolution
from app.email.approval_handler import EmailApprovalOutcome


class _Row:
    def __init__(self, status="pending"):
        self.id = "uuid-1"
        self.thread_id = "email:gmail:msg-1"
        self.status = status
        self.action_type = "email_reply"
        self.description = "Reply to 'Q3' from Priya"
        self.payload = {"sender": "Priya <p@x.com>", "subject": "Q3", "draft": "On it."}


def _wire(monkeypatch, *, row, intent, claimed=True, outcome=None):
    rec: dict = {}

    async def fake_load(_id):
        return row

    async def fake_decide(tool_name, tool_args, description, transcript):
        rec["judged"] = tool_args
        return DecisionResolution(intent=intent, change="")

    async def fake_dispatch(thread_id, decision):
        rec["dispatch"] = (thread_id, decision)
        return outcome or EmailApprovalOutcome(status="sent", recipient="p@x.com")

    async def fake_claim(approval_id, action):
        rec["claim"] = (approval_id, action)
        return (row.thread_id if (row and claimed) else None)

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_decide)
    monkeypatch.setattr(runner, "_resolve_presented_row", fake_claim)
    monkeypatch.setattr("app.email.approval_handler.dispatch_email_approval", fake_dispatch)
    return rec


async def _collect(agen):
    return [ev async for ev in agen]


def _resolved(events):
    for ev in events:
        if ev["type"] == "decision_resolved":
            return ev["content"]["status"]
    return None


async def test_typed_approve_dispatches_no_audio(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="approve")
    events = await _collect(runner._resolve_presented_approval_stream("uuid-1", "yes send it"))
    assert rec["dispatch"] == ("email:gmail:msg-1", {"approved": True})
    assert rec["claim"] == ("uuid-1", "approve")
    assert _resolved(events) == "approved"
    assert events[-1]["type"] == "done"
    assert not any(e["type"] == "audio" for e in events)  # TEXT path → no audio
    assert rec["judged"]["subject"] == "Q3"  # judged against the presented card


async def test_typed_reject_marks_no_dispatch(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="reject")
    events = await _collect(runner._resolve_presented_approval_stream("uuid-1", "no, discard"))
    assert "dispatch" not in rec
    assert _resolved(events) == "rejected"


async def test_typed_unrelated_keeps_pending(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="unrelated")
    events = await _collect(
        runner._resolve_presented_approval_stream("uuid-1", "what's the weather")
    )
    assert "dispatch" not in rec  # never sends on ambient
    assert _resolved(events) is None  # card stays pending
    assert events[-1]["type"] == "done"


async def test_typed_approve_lost_claim_no_double_send(monkeypatch):
    rec = _wire(monkeypatch, row=_Row(), intent="approve", claimed=False)
    events = await _collect(runner._resolve_presented_approval_stream("uuid-1", "send it"))
    assert "dispatch" not in rec  # B1: claim lost → no second send
    assert _resolved(events) is None
