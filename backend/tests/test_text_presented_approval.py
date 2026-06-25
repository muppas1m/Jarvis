"""Part B2 + Part C: typed resolution of a presented inbound card.

Part C regression: while a card is pending the frontend tags EVERY typed turn
with the card id, so the OLD code intercepted an UNRELATED typed message ("what's
on my calendar?") with a nudge — dropping the real question. The fix: `_judge_presented`
marks only approve/reject/edit as ACTIONABLE; an `unrelated` intent is NOT
actionable, so stream_turn falls THROUGH to a normal turn (card stays pending).
The gate stays closed: a normal message can't classify as approve → can't send.
"""
from datetime import UTC, datetime
from types import SimpleNamespace

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

    for intent in ("approve", "reject", "edit", "skip", "show_others"):
        async def fake_decide(*a, _i=intent, **k):
            return DecisionResolution(intent=_i, change="x" if _i == "edit" else "")

        monkeypatch.setattr(runner, "resolve_decision", fake_decide)
        judged = await runner._judge_presented("uuid-1", "go")
        assert judged is not None and judged.actionable, f"{intent} must be actionable"


async def test_judge_now_handles_tool_card_not_just_email(monkeypatch):
    """Parity: a chat-queued TOOL card (non-email thread) is now JUDGED (was None),
    so voice/text approve/reject/skip work for tool cards too. Its tool_args come
    from the row payload's real tool args, not the email-draft shape."""
    row = _Row()
    row.action_type, row.thread_id = "calendar_create", "web:master"
    row.payload = {"tool_name": "calendar_create", "tool_args": {"summary": "Standup"}}
    seen: dict = {}

    async def fake_load(_id):
        return row

    async def fake_decide(tool_name, tool_args, description, message):
        seen["args"] = (tool_name, tool_args)
        return DecisionResolution(intent="approve", change="")

    monkeypatch.setattr(runner, "_load_approval_by_id", fake_load)
    monkeypatch.setattr(runner, "resolve_decision", fake_decide)
    judged = await runner._judge_presented("uuid-1", "yes")
    assert judged is not None and judged.actionable  # tool card no longer falls through
    assert judged.is_email_card is False  # and it's recognised as a tool, not email
    assert seen["args"] == ("calendar_create", {"summary": "Standup"})  # REAL tool args judged


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


async def test_text_edit_without_context_nudges(monkeypatch):
    # No message/conversation_thread_id (a caller that can't re-draft) → the SAFE
    # floor: a nudge, never a claim/send. (With message+thread, edit re-drafts — and
    # voice now lands in the re-draft path too, see the voice suite.)
    rec = _wire_decision(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(_judgment("edit"), speak=False))
    assert "call" not in rec and _resolved(events) is None
    assert events[-1]["type"] == "done"


async def test_text_skip_emits_nav_no_dispatch(monkeypatch):
    """Text SKIP emits a presented_nav {skip} the client turns into markSkipped —
    DB-inert, never claims/sends. The done line acks + the next surfaces client-side."""
    rec = _wire_decision(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(
        _judgment("skip"), speak=False, conversation_thread_id="web:master"
    ))
    nav = [e for e in events if e["type"] == "presented_nav"]
    assert len(nav) == 1
    assert nav[0]["content"] == {"action": "skip", "approval_id": "uuid-1"}
    assert nav[0]["thread_id"] == "web:master"
    assert "call" not in rec  # never reached the dispatch gate
    assert _resolved(events) is None  # not a resolve (no card flip)
    assert not any(e["type"] == "audio" for e in events)  # TEXT → no audio
    assert events[-1]["type"] == "done"


async def test_text_show_others_summarizes_no_dispatch(monkeypatch):
    """Text 'what else is pending?' → the queue summary in the done response; the
    current card stays pending, nothing dispatched."""
    rec = _wire_decision(monkeypatch)

    async def fake_summary(exclude_approval_id=""):
        rec["summary_excluded"] = exclude_approval_id
        return "You have 2 others pending, Sir: a reply to a@x.com; a reply to b@x.com."

    monkeypatch.setattr(runner, "_pending_queue_summary", fake_summary)
    events = await _collect(runner._resolve_presented_decision(
        _judgment("show_others"), speak=False, conversation_thread_id="web:master"
    ))
    assert rec["summary_excluded"] == "uuid-1"
    assert "call" not in rec and _resolved(events) is None  # read-only, card stays
    done = [e for e in events if e["type"] == "done"][-1]
    assert "2 others pending" in done["content"]["response"]


# --- edit (REVISE) — TEXT re-draft: discard-FIRST (claim-gated) + re-queue -----
def _edit_judgment(change="make it shorter"):
    return runner._PresentedJudgment(
        approval_id="uuid-1", row=_Row(), intent="edit", change=change
    )


def _wire_revise(monkeypatch, *, claimed=True, revised="Shorter draft.", raises=None):
    rec: dict = {}

    async def fake_claim(approval_id, action, resolved_via):
        rec["claim"] = (approval_id, action, resolved_via)
        return ("email:gmail:msg-1" if claimed else None)

    async def fake_revise(*, subject, sender, draft, change):
        rec["revise"] = {"draft": draft, "change": change}
        if raises:
            raise raises
        return revised

    async def fake_requeue(row, revised_draft):
        rec["requeue"] = revised_draft
        return {
            "approval_id": "uuid-NEW", "tool_name": "email_reply",
            "tool_args": {"to": "p@x.com", "subject": "Q3", "body": revised_draft},
            "description": "Reply to 'Q3' from Priya",
        }

    async def fake_persist(thread_id, message):
        rec["persist"] = (thread_id, message)

    monkeypatch.setattr("app.api.approvals.resolve_approval", fake_claim)
    monkeypatch.setattr("app.email.responder.revise_draft", fake_revise)
    monkeypatch.setattr(runner, "_requeue_revised_email", fake_requeue)
    monkeypatch.setattr(runner, "_persist_edit_to_conversation", fake_persist)
    return rec


async def test_text_edit_discards_then_requeues_new_card(monkeypatch):
    rec = _wire_revise(monkeypatch)
    events = await _collect(runner._resolve_presented_decision(
        _edit_judgment(), speak=False, message="make it shorter", conversation_thread_id="web:master"
    ))
    assert rec["claim"] == ("uuid-1", "discard", "web")  # DISCARD-first, claim-gated
    assert _resolved(events) == "discarded"  # the OLD card greys to discarded
    assert rec["revise"]["change"] == "make it shorter"  # original draft + change = context
    assert rec["revise"]["draft"] == "On it."
    # exactly ONE new card (new approval_id) — no double, no two-pending window
    cards = [e for e in events if e["type"] == "approval_required"]
    assert len(cards) == 1
    assert cards[0]["content"]["approval_id"] == "uuid-NEW"
    assert cards[0]["content"]["tool_name"] == "email_reply"  # renders as an email card
    assert cards[0]["content"]["tool_args"]["body"] == "Shorter draft."
    # the master's ACTUAL words persisted (NOT a synthetic instruction)
    assert rec["persist"] == ("web:master", "make it shorter")
    assert events[-1]["type"] == "done"


async def test_text_edit_lost_claim_no_redraft_no_double(monkeypatch):
    # A concurrent approve won the claim first → discard loses → NO re-draft, no
    # new card (the original already sent/resolved). Never two approvable cards.
    rec = _wire_revise(monkeypatch, claimed=False)
    events = await _collect(runner._resolve_presented_decision(
        _edit_judgment(), speak=False, message="make it shorter", conversation_thread_id="web:master"
    ))
    assert rec["claim"][1] == "discard"  # the claim was attempted
    assert "revise" not in rec  # lost claim → never re-drafts
    assert not any(e["type"] == "approval_required" for e in events)  # no new card
    assert _resolved(events) is None
    assert events[-1]["type"] == "done"


async def test_text_edit_failed_redraft_leaves_no_card(monkeypatch):
    # Discard-FIRST, then the re-draft fails → NO new card (the old is discarded;
    # the master re-asks). Never two cards, never an error/send.
    rec = _wire_revise(monkeypatch, raises=RuntimeError("llm down"))
    events = await _collect(runner._resolve_presented_decision(
        _edit_judgment(), speak=False, message="make it shorter", conversation_thread_id="web:master"
    ))
    assert _resolved(events) == "discarded"  # old still discarded (discard-first held)
    assert "requeue" not in rec  # re-draft failed → no re-queue
    assert not any(e["type"] == "approval_required" for e in events)  # NO new card
    assert "persist" not in rec  # didn't persist a half-state
    assert events[-1]["type"] == "done"  # never errors the turn


# --- show_others queue summary (pure formatting, DB-independent) --------------
def _prow(rid, sender="", subject="", *, tool=None):
    if tool:
        return SimpleNamespace(
            id=rid, payload={"tool_name": tool, "tool_args": {}}, action_type=tool,
            thread_id="web:master", description="", status="pending", created_at=datetime.now(UTC))
    return SimpleNamespace(
        id=rid, payload={"sender": sender, "subject": subject, "draft": "b"},
        action_type="email_reply", thread_id=f"email:gmail:{rid}", description="",
        status="pending", created_at=datetime.now(UTC))


def test_summarize_pending_only_the_presented_one():
    # exclude the only pending row → the single-card corner case
    out = runner._summarize_pending([_prow("a", "Al", "X")], "a", "Sir")
    assert "only one pending" in out


def test_summarize_pending_lists_others_excluding_presented():
    rows = [_prow("a", "Alice <al@x.com>", "Budget"), _prow("b", "Bob <b@x.com>", "Lunch")]
    out = runner._summarize_pending(rows, "a", "Sir")  # 'a' is the presented card
    assert "one other pending" in out
    assert "Bob <b@x.com>" in out and "Lunch" in out  # the OTHER one is described
    assert "Alice" not in out                          # the presented one is excluded


def test_summarize_pending_bounds_to_five_with_overflow():
    rows = [_prow(str(i), f"s{i}@x.com", f"sub{i}") for i in range(8)]
    out = runner._summarize_pending(rows, "none-presented", "Sir")  # all 8 are "others"
    assert "8 others pending" in out and "and 3 more" in out


# --- the spoken/typed outcome line (3rd transport) distinguishes the cases ----
def test_outcome_speech_distinguishes_sent_uncertain_failed():
    sent = runner._email_outcome_speech(EmailApprovalOutcome(status="sent", recipient="p@x.com"))
    assert "Sent to p@x.com" in sent

    uncertain = runner._email_outcome_speech(EmailApprovalOutcome(status="send_uncertain"))
    assert "couldn't confirm" in uncertain.lower() and "sent folder" in uncertain.lower()

    failed = runner._email_outcome_speech(EmailApprovalOutcome(status="send_failed"))
    assert "couldn't be sent" in failed.lower()  # definite fail stays a clean failure
    assert "couldn't confirm" not in failed.lower()  # NOT the uncertain wording
