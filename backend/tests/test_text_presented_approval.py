"""Part B2 + Part C: typed resolution of a presented inbound card.

Part C regression: while a card is pending the frontend tags EVERY typed turn
with the card id, so the OLD code intercepted an UNRELATED typed message ("what's
on my calendar?") with a nudge — dropping the real question. The fix: `_judge_presented`
marks only approve/reject/edit as ACTIONABLE; an `unrelated` intent is NOT
actionable, so stream_turn falls THROUGH to a normal turn (card stays pending).
The gate stays closed: a normal message can't classify as approve → can't send.
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


def _judgment(intent, *, row=None):
    return runner._PresentedJudgment(
        approval_id="uuid-1", row=row or _Row(), intent=intent, change=""
    )


async def _collect(agen):
    return [ev async for ev in agen]


def _resolved(events):
    for ev in events:
        if ev["type"] == "decision_resolved":
            return ev["content"]["status"]
    return None


# --- Part C: the gate — actionable vs fall-through ---------------------------
async def test_judge_marks_card_related_actionable(monkeypatch):
    async def fake_load(_id):
        return _Row()

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)

    for intent in ("approve", "reject", "edit"):
        async def fake_decide(*a, _i=intent, **k):
            return DecisionResolution(intent=_i, change="")

        monkeypatch.setattr(runner, "resolve_decision", fake_decide)
        judged = await runner._judge_presented("uuid-1", "send it")
        assert judged is not None and judged.actionable, f"{intent} must be actionable"


async def test_judge_marks_unrelated_NOT_actionable_so_text_falls_through(monkeypatch):
    """The regression fix: an unrelated typed message is NOT actionable → stream_turn
    falls through to a normal turn instead of nudging-and-dropping it."""
    async def fake_load(_id):
        return _Row()

    async def fake_decide(*a, **k):
        return DecisionResolution(intent="unrelated", change="")

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_decide)
    judged = await runner._judge_presented("uuid-1", "what's on my calendar?")
    assert judged is not None and judged.actionable is False  # → fall through


async def test_judge_stale_card_returns_none(monkeypatch):
    async def fake_load(_id):
        return _Row(status="approved")  # already resolved

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    assert await runner._judge_presented("uuid-1", "send it") is None  # → text falls through


async def test_judge_FAILS_OPEN_to_unrelated_never_approve(monkeypatch):
    """A DB/LLM judge failure must NOT error the turn and must NEVER read as
    approve — it fails open to 'unrelated' (text falls through, voice nudges)."""
    async def boom(_id):
        raise RuntimeError("db hiccup mid-judge")

    monkeypatch.setattr(runner, "_load_approval_by_id", boom)
    judged = await runner._judge_presented("uuid-1", "send it")
    assert judged is not None  # didn't raise — turn won't error
    assert judged.intent == "unrelated" and judged.actionable is False  # NEVER approve
    assert judged.row is None  # signals the failure to the voice nudge


# --- the text (no-audio) resolution of an actionable judgment ----------------
# Phase 3: the presented-card resolver now goes through the SAME generic gate as
# every other transport — `resolve_and_dispatch` (claim + dispatch-by-row-shape),
# NOT the email-specific `dispatch_email_approval`. So a chat-queued TOOL card and
# an inbound EMAIL card both resolve here, claim-gated (invariant 3).
def _wire_decision(monkeypatch, *, claimed=True, outcome=None):
    from app.agent.approval_dispatch import ApprovalDispatchOutcome

    rec: dict = {}

    async def fake_rad(approval_id, action, resolved_via, decision):
        rec["call"] = (approval_id, action, resolved_via, decision)
        if not claimed:
            return ApprovalDispatchOutcome(kind="none", status="not_claimed")
        if action == "reject":
            return ApprovalDispatchOutcome(
                kind="email", status="rejected", thread_id="email:gmail:msg-1"
            )
        return outcome or ApprovalDispatchOutcome(
            kind="email", status="sent", success=True, thread_id="email:gmail:msg-1",
            email_outcome=EmailApprovalOutcome(status="sent", recipient="p@x.com"),
        )

    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", fake_rad)
    return rec


async def test_text_approve_dispatches_no_audio(monkeypatch):
    rec = _wire_decision(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(_judgment("approve"), speak=False))
    assert rec["call"] == ("uuid-1", "approve", "web", {"approved": True})
    assert _resolved(events) == "approved"
    assert any("Sent to p@x.com" in str(e.get("content", "")) for e in events)  # email taxonomy
    assert not any(e["type"] == "audio" for e in events)  # TEXT path → no audio
    assert events[-1]["type"] == "done"


async def test_text_approve_tool_card_renders_tool_result(monkeypatch):
    """Invariant 3: a chat-queued TOOL card resolves through the generic gate and
    its spoken/typed line is the tool's deterministic result — not email copy."""
    from app.agent.approval_dispatch import ApprovalDispatchOutcome

    rec: dict = {}

    async def fake_rad(approval_id, action, resolved_via, decision):
        rec["call"] = (approval_id, action)
        return ApprovalDispatchOutcome(
            kind="tool", status="executed", detail="Event created: Standup 9am",
            success=True, thread_id="web:master",
        )

    monkeypatch.setattr("app.agent.approval_dispatch.resolve_and_dispatch", fake_rad)
    row = _Row()
    row.action_type, row.thread_id = "calendar_create", "web:master"
    events = await _collect(
        runner._resolve_presented_decision(_judgment("approve", row=row), speak=False)
    )
    assert rec["call"] == ("uuid-1", "approve")
    assert _resolved(events) == "approved"
    assert any("Event created: Standup 9am" in str(e.get("content", "")) for e in events)


async def test_text_reject_marks_no_send(monkeypatch):
    rec = _wire_decision(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(_judgment("reject"), speak=False))
    assert rec["call"][1] == "reject"  # claimed + dispatched as a reject (no send side effect)
    assert _resolved(events) == "rejected"
    assert any("Discarded" in str(e.get("content", "")) for e in events)


async def test_text_approve_lost_claim_no_double_send(monkeypatch):
    rec = _wire_decision(monkeypatch, claimed=False)
    events = await _collect(runner._resolve_presented_decision(_judgment("approve"), speak=False))
    assert rec["call"][1] == "approve"  # the gate was asked, but it lost the claim
    assert _resolved(events) is None  # not_claimed → no card flip, no second send
    assert events[-1]["type"] == "done"


async def test_text_edit_keeps_pending(monkeypatch):
    rec = _wire_decision(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(_judgment("edit"), speak=False))
    assert "call" not in rec and _resolved(events) is None  # edit never claims → stays pending
    assert events[-1]["type"] == "done"


# --- the spoken/typed outcome line (3rd transport) distinguishes the cases ----
def test_outcome_speech_distinguishes_sent_uncertain_failed():
    sent = runner._email_outcome_speech(EmailApprovalOutcome(status="sent", recipient="p@x.com"))
    assert "Sent to p@x.com" in sent

    uncertain = runner._email_outcome_speech(EmailApprovalOutcome(status="send_uncertain"))
    assert "couldn't confirm" in uncertain.lower() and "sent folder" in uncertain.lower()

    failed = runner._email_outcome_speech(EmailApprovalOutcome(status="send_failed"))
    assert "couldn't be sent" in failed.lower()  # definite fail stays a clean failure
    assert "couldn't confirm" not in failed.lower()  # NOT the uncertain wording
