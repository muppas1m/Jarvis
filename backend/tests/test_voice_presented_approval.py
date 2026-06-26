"""Voice rendering of the shared presented-card resolution (speak=True).

Voice and text now share ONE judge + ONE resolver (`_presented_disposition` →
`_resolve_presented_decision` / `_reask_presented`); the modality-agnostic disposition,
reminder, and re-ask logic is covered in test_text_presented_approval. Here we assert
the VOICE rendering: an actionable resolution + a re-ask both SPEAK (audio events),
approve/reject still claim-gate via resolve_and_dispatch, a lost claim never
double-sends, and a voice edit re-drafts + speaks the change echo.
"""
import app.agent.runner as runner
from app.email.approval_handler import EmailApprovalOutcome


class _Row:
    def __init__(self, status="pending", thread_id="gmail:msg-1"):
        self.id = "uuid-1"
        self.thread_id = thread_id
        self.status = status
        self.action_type = "gmail_reply"
        self.description = "Reply to 'Q3' from Priya"
        self.payload = {"sender": "Priya <p@x.com>", "subject": "Q3", "draft": "On it."}


def _judgment(intent, *, change="", row=None):
    return runner._PresentedJudgment(approval_id="uuid-1", row=row or _Row(), intent=intent, change=change)


async def _collect(agen):
    return [ev async for ev in agen]


def _resolved_status(events):
    for ev in events:
        if ev["type"] == "decision_resolved":
            return ev["content"]["status"]
    return None


def _wire(monkeypatch, *, outcome=None, claimed=True):
    """Patch the dispatch gate + TTS. Records the gate call + every spoken line."""
    from app.agent.approval_dispatch import ApprovalDispatchOutcome

    rec = {"spoken": []}

    async def fake_rad(approval_id, action, resolved_via, decision):
        rec["resolved"] = (approval_id, action, resolved_via, decision)
        if not claimed:
            return ApprovalDispatchOutcome(kind="none", status="not_claimed")
        if action == "reject":
            return ApprovalDispatchOutcome(kind="email", status="rejected", thread_id="gmail:msg-1")
        eo = outcome or EmailApprovalOutcome(status="sent", recipient="p@x.com")
        return ApprovalDispatchOutcome(
            kind="email", status=eo.status, success=(eo.status == "sent"),
            thread_id="gmail:msg-1", email_outcome=eo,
        )

    async def fake_synth(text):
        rec["spoken"].append(text)
        return b"AUDIO"

    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", fake_rad)
    monkeypatch.setattr(runner, "synthesize", fake_synth)
    return rec


async def test_voice_approve_dispatches_and_speaks(monkeypatch):
    rec = _wire(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(_judgment("approve"), speak=True))
    assert rec["resolved"] == ("uuid-1", "approve", "voice", {"approved": True})
    assert _resolved_status(events) == "approved"
    assert any(e["type"] == "audio" for e in events)          # VOICE → spoke the outcome
    assert any("Sent to p@x.com" in t for t in rec["spoken"])  # email taxonomy
    assert events[-1]["type"] == "done"


async def test_voice_approve_send_failure_speaks_honestly(monkeypatch):
    rec = _wire(monkeypatch, outcome=EmailApprovalOutcome(status="send_failed", detail="token expired"))
    events = await _collect(runner._resolve_presented_decision(_judgment("approve"), speak=True))
    assert _resolved_status(events) == "approved"  # the master DID approve
    assert any("couldn't be sent" in t for t in rec["spoken"])  # honest about delivery


async def test_voice_reject_speaks_no_send(monkeypatch):
    rec = _wire(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(_judgment("reject"), speak=True))
    assert rec["resolved"][1] == "reject"
    assert _resolved_status(events) == "rejected"
    assert any("Discarded" in t for t in rec["spoken"])


async def test_voice_approve_lost_claim_no_double_send(monkeypatch):
    rec = _wire(monkeypatch, claimed=False)
    events = await _collect(runner._resolve_presented_decision(_judgment("approve"), speak=True))
    assert rec["resolved"][1] == "approve"      # asked, lost the claim
    assert _resolved_status(events) is None      # no flip, no second send
    assert events[-1]["type"] == "done"


async def test_voice_skip_emits_nav_and_speaks(monkeypatch):
    rec = _wire(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(
        _judgment("skip"), speak=True, conversation_thread_id="web:master"))
    nav = [e for e in events if e["type"] == "presented_nav"]
    assert nav and nav[0]["content"] == {"action": "skip", "approval_id": "uuid-1"}
    assert "resolved" not in rec                 # skip never claims/sends
    assert any("skipped" in t.lower() for t in rec["spoken"])


async def test_voice_show_others_speaks_summary(monkeypatch):
    rec = _wire(monkeypatch)

    async def fake_summary(exclude_approval_id=""):
        rec["excluded"] = exclude_approval_id
        return "You have one other pending, Sir: a reply to bob@x.com."

    monkeypatch.setattr(runner, "_pending_queue_summary", fake_summary)
    events = await _collect(runner._resolve_presented_decision(
        _judgment("show_others"), speak=True, conversation_thread_id="web:master"))
    assert rec["excluded"] == "uuid-1"           # excludes the presented card
    assert any("one other pending" in t for t in rec["spoken"])
    assert events[-1]["type"] == "done"


async def test_voice_edit_redrafts_and_speaks_change(monkeypatch):
    rec = _wire(monkeypatch)

    async def fake_claim(aid, action, via):
        rec["claim"] = (aid, action, via)
        return "gmail:msg-1"

    async def fake_revise(*, subject, sender, draft, change):
        rec["change"] = change
        return "Shorter draft."

    async def fake_requeue(row, revised):
        return {"approval_id": "uuid-NEW", "tool_name": "email_reply",
                "tool_args": {"to": "p@x.com", "subject": "Q3", "body": revised}, "description": "d"}

    async def fake_persist(t, m):
        rec["persist"] = (t, m)

    monkeypatch.setattr("app.api.approvals.resolve_approval", fake_claim)
    monkeypatch.setattr("app.email.responder.revise_draft", fake_revise)
    monkeypatch.setattr(runner, "_requeue_revised_email", fake_requeue)
    monkeypatch.setattr(runner, "_persist_edit_to_conversation", fake_persist)

    events = await _collect(runner._resolve_presented_decision(
        _judgment("edit", change="make it shorter"), speak=True,
        message="make it shorter", conversation_thread_id="web:master"))
    assert rec["claim"][1] == "discard" and rec["change"] == "make it shorter"
    assert any("make it shorter" in t for t in rec["spoken"])  # spoke the change echo
    cards = [e for e in events if e["type"] == "approval_required"]
    assert cards and cards[0]["content"]["approval_id"] == "uuid-NEW"


async def test_voice_reask_speaks_and_names_card(monkeypatch):
    rec = _wire(monkeypatch)
    events = await _collect(runner._reask_presented(_judgment("unclear"), speak=True))
    assert any("Priya" in t for t in rec["spoken"])     # re-ask names the pending card
    assert any(e["type"] == "audio" for e in events)
    assert "resolved" not in rec                          # re-ask never sends
    assert events[-1]["type"] == "done"
