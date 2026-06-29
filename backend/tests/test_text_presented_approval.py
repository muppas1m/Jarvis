"""Presented-card consent gate: `_judge_presented` (the STRONG-model classifier).

Part C regression: while a card is pending the frontend tags EVERY typed turn with the card
id. `_judge_presented` marks only approve/reject/edit/skip/show_others as ACTIONABLE; an
`unrelated` intent is NOT actionable, so the turn flows through to a normal answer (the card
stays pending). The gate stays closed: a normal message can't classify as approve → can't send.

(Step A retired the old runner disposition orchestrators that resolved/re-asked these in the
runner; that resolution now runs IN the graph — see test_card_resolution_node /
test_card_resolution_graph. The judge + the outcome-line helpers it reuses are tested here.)
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


# --- the gate: actionable vs fall-through ------------------------------------
async def test_judge_marks_card_related_actionable(monkeypatch):
    async def fake_load(_id):
        return _Row()

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)

    for intent in ("approve", "reject", "edit", "skip", "show_others"):
        async def fake_decide(*a, _i=intent, **k):
            return DecisionResolution(intent=_i, change="x" if _i == "edit" else "")

        monkeypatch.setattr(runner, "resolve_decision", fake_decide)
        judged = await runner._judge_presented("uuid-1", "go")
        assert judged is not None and judged.actionable, f"{intent} must be actionable"


async def test_judge_now_handles_tool_card_not_just_email(monkeypatch):
    """A chat-queued TOOL card (non-email thread) is JUDGED, judging the REAL tool + args."""
    row = _Row()
    row.action_type, row.thread_id = "calendar_create", "web:master"
    row.payload = {"tool_name": "calendar_create", "tool_args": {"summary": "Standup"}}
    seen: dict = {}

    async def fake_load(_id):
        return row

    async def fake_decide(tool_name, tool_args, description, message, recent_context=""):
        seen["args"] = (tool_name, tool_args)
        return DecisionResolution(intent="approve", change="")

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_decide)
    judged = await runner._judge_presented("uuid-1", "yes")
    assert judged is not None and judged.actionable
    assert judged.is_email_card is False
    assert seen["args"] == ("calendar_create", {"summary": "Standup"})


async def test_judge_marks_unrelated_NOT_actionable_so_text_falls_through(monkeypatch):
    async def fake_load(_id):
        return _Row()

    async def fake_decide(*a, **k):
        return DecisionResolution(intent="unrelated", change="")

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_decide)
    judged = await runner._judge_presented("uuid-1", "what's on my calendar?")
    assert judged is not None and judged.actionable is False  # → falls through to a normal turn


async def test_judge_stale_card_returns_none(monkeypatch):
    async def fake_load(_id):
        return _Row(status="approved")  # already resolved

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    assert await runner._judge_presented("uuid-1", "send it") is None


async def test_judge_FAILS_OPEN_to_unrelated_never_approve(monkeypatch):
    """A DB/LLM judge failure must NOT error the turn and must NEVER read as approve."""
    async def boom(_id):
        raise RuntimeError("db hiccup mid-judge")

    monkeypatch.setattr(runner, "_load_approval_by_id", boom)
    judged = await runner._judge_presented("uuid-1", "send it")
    assert judged is not None  # didn't raise
    assert judged.intent == "unrelated" and judged.actionable is False  # NEVER approve
    assert judged.row is None


# --- reused outcome-line helpers (live; the node renders resolutions with these) ----
def test_with_reminder_appends_and_noops():
    assert runner._with_reminder({"response": "Done."}, "Card pending.")["response"] == "Done. Card pending."
    assert runner._with_reminder({"response": "Done."}, "")["response"] == "Done."  # no-op
    assert runner._with_reminder({"response": ""}, "Card pending.")["response"] == "Card pending."


def test_outcome_speech_distinguishes_sent_uncertain_failed():
    sent = runner._email_outcome_speech(EmailApprovalOutcome(status="sent", recipient="p@x.com"))
    assert "Sent to p@x.com" in sent

    uncertain = runner._email_outcome_speech(EmailApprovalOutcome(status="send_uncertain"))
    assert "couldn't confirm" in uncertain.lower() and "sent folder" in uncertain.lower()

    failed = runner._email_outcome_speech(EmailApprovalOutcome(status="send_failed"))
    assert "couldn't be sent" in failed.lower()
    assert "couldn't confirm" not in failed.lower()
