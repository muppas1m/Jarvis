"""Step A — `card_resolution_node`: presented-card interactions run THROUGH the graph.

Proves the node-level routing + the L1 invariants (the STRONG-model judge + the ATOMIC
claim both run here) + the `card_outcome` state the runner turns into frontend events.
The runner pure helpers (`route_after_card` / `_card_outcome_events`) are covered too.

Deterministic: the judge (`_judge_presented`) and the claim/dispatch (`resolve_and_dispatch`)
are mocked — those are exercised end-to-end by `test_approval_dispatch` /
`test_text_presented_approval`. Here we test the NODE's wiring of them.
"""
import pytest

import app.agent.approval_dispatch as approval_dispatch
import app.agent.nodes as nodes
import app.agent.runner as runner
from app.agent.approval_dispatch import ApprovalDispatchOutcome
from app.email.approval_handler import EmailApprovalOutcome


class _Row:
    def __init__(self, status="pending", action_type="email_reply", thread_id="email:gmail:msg-1"):
        self.id = "uuid-1"
        self.thread_id = thread_id
        self.status = status
        self.action_type = action_type
        self.description = "Reply to 'Q3' from Priya"
        self.payload = {"sender": "Priya <p@x.com>", "subject": "Q3", "draft": "On it."}


def _judgment(intent, *, row=None, change=""):
    return runner._PresentedJudgment(
        approval_id="uuid-1", row=row or _Row(), intent=intent, change=change
    )


def _linked_msg(aid="uuid-1", solicited=True):
    from langchain_core.messages import AIMessage
    return AIMessage(content="I've queued it for your approval, Sir — shall I go ahead?",
                     additional_kwargs={"jarvis": {"type": "approval", "approval_ids": [aid],
                                                   "mint_class": "fresh", "solicited": solicited}})


def _state(**kw):
    # A2 s2: the referent is the CONVERSATION's jarvis-linked message (aid is context-only)
    base = {
        "user_message": "go", "thread_id": "web:master", "messages": [_linked_msg()],
    }
    base.update(kw)
    return base


def _patch_judge(monkeypatch, judged):
    async def fake(*a, **k):
        return judged
    monkeypatch.setattr(runner, "_judge_presented", fake)


def _patch_dispatch(monkeypatch, outcome):
    rec: dict = {}

    async def fake(approval_id, action, resolved_via, decision, *, ground_thread=True):
        rec["call"] = (approval_id, action, resolved_via, decision)
        rec["ground_thread"] = ground_thread
        return outcome
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    return rec


def _live_card(approval_id="uuid-1", kind="email", tool_name="email_reply", **targs):
    from app.approvals_service import UnifiedApprovalCard
    return UnifiedApprovalCard(
        approval_id=approval_id, kind=kind, thread_id="email:gmail:msg-1", tool_name=tool_name,
        tool_args=targs or {"to": "p@x.com", "subject": "Q3"}, description="d", status="pending",
        created_at="2026-06-30T00:00:00+00:00")


def _patch_targets(monkeypatch, cards):
    """A2 s2: the node's live targets come from the referent's linked ids
    (_live_linked_targets → _fetch_queued_cards); [] = stale (already resolved)."""
    async def fake(ids):
        return list(cards)
    monkeypatch.setattr(nodes, "_fetch_queued_cards", fake)


_patch_live = None  # retired with the seal's live-set matching (kept name for grep history)


# --- no presented card → pass straight through to the agent ------------------
async def test_no_card_passes_through():
    # A2 s3: "no card" = no jarvis-linked message in the conversation
    assert await nodes.card_resolution_node(_state(messages=[])) == {}


# --- approve → the ATOMIC claim runs + outcome reply + flip state (L1) --------
async def test_approve_goes_through_claim(monkeypatch):
    _patch_judge(monkeypatch, _judgment("approve"))
    _patch_targets(monkeypatch, [_live_card()])  # one live card → the gate resolves it
    rec = _patch_dispatch(monkeypatch, ApprovalDispatchOutcome(
        kind="email", status="sent", success=True, thread_id="email:gmail:msg-1",
        email_outcome=EmailApprovalOutcome(status="sent", recipient="p@x.com")))
    out = await nodes.card_resolution_node(_state(user_message="yes, send it"))
    assert rec["call"] == ("uuid-1", "approve", "web", {"approved": True})  # the LIVE target, claimed
    assert rec["ground_thread"] is False  # no double-write: the node owns the thread reply
    assert out["card_handled"] is True
    assert out["card_outcomes"][0]["decision_status"] == "approved"
    assert "Sent to p@x.com" in out["final_response"]
    # the reply is also written to messages → it persists in the checkpoint (kills D2)
    assert out["messages"] and out["messages"][0].content == out["final_response"]


# --- approve, LOST claim (graph re-process / race) → NOT double-executed ------
async def test_approve_lost_claim_no_double_dispatch(monkeypatch):
    _patch_judge(monkeypatch, _judgment("approve"))
    _patch_targets(monkeypatch, [_live_card()])  # one live card → gate dispatches → claim is lost
    _patch_dispatch(monkeypatch, ApprovalDispatchOutcome(kind="none", status="not_claimed"))
    out = await nodes.card_resolution_node(_state())
    assert out["card_handled"] is True
    # a lost claim emits NO flip event (stale), and never re-dispatches
    assert out["card_outcomes"][0]["decision_status"] == "stale"
    assert "already taken care of" in out["final_response"]


# --- reject → claim with approved=False --------------------------------------
async def test_reject(monkeypatch):
    _patch_judge(monkeypatch, _judgment("reject"))
    _patch_targets(monkeypatch, [_live_card()])  # one live card → the gate resolves it
    rec = _patch_dispatch(monkeypatch, ApprovalDispatchOutcome(
        kind="email", status="rejected", thread_id="email:gmail:msg-1"))
    out = await nodes.card_resolution_node(_state(user_message="no, cancel it"))
    assert rec["call"][1] == "reject" and rec["call"][3] == {"approved": False}
    assert out["card_outcomes"][0]["decision_status"] == "rejected"
    assert out["card_handled"] is True


# --- show_others / unclear / unrelated → AGENT with card context (kills D3) ---
@pytest.mark.parametrize("intent", ["show_others", "unclear", "unrelated"])
async def test_questions_route_to_agent(monkeypatch, intent):
    _patch_judge(monkeypatch, _judgment(intent))
    out = await nodes.card_resolution_node(
        _state(user_message="show me more about that calendar event"))
    assert out.get("card_handled") is False    # → routed to the agent, not canned
    assert "card_context" in out               # the referent is injected so it answers right


# --- skip → DB-inert client nav ----------------------------------------------
async def test_skip_nav(monkeypatch):
    _patch_judge(monkeypatch, _judgment("skip"))
    out = await nodes.card_resolution_node(_state(user_message="not now"))
    assert out["card_handled"] is True
    assert out["card_outcomes"][0]["nav"] == "skip"


# --- stale / gone card → brief ack -------------------------------------------
async def test_stale_card_acks(monkeypatch):
    """MIGRATED (A2 s2, declared): 'stale' = the linked target is no longer pending (live
    targets empty) while the master expresses consent — the honest ack, never a substitute.
    (A judge-None row-DELETED case now routes to the agent as a normal turn — {}.)"""
    _patch_judge(monkeypatch, _judgment("approve"))
    _patch_targets(monkeypatch, [])            # the linked card is already resolved
    out = await nodes.card_resolution_node(_state())
    assert out["card_handled"] is True
    assert out["card_outcomes"][0]["decision_status"] == "stale"
    assert "already taken care of" in out["final_response"]


# --- edit → claim-gated discard → re-draft → re-queue a NEW card --------------
async def test_edit_redraft(monkeypatch):
    _patch_judge(monkeypatch, _judgment("edit", change="make it shorter"))

    async def fake_resolve_approval(aid, action, via):
        assert action == "discard"
        return "email:gmail:msg-1"            # claim won

    async def fake_revise(**k):
        return "Shorter draft."

    async def fake_requeue(row, draft):
        return {"approval_id": "uuid-2", "kind": "email"}

    monkeypatch.setattr("app.api.approvals.resolve_approval", fake_resolve_approval)
    monkeypatch.setattr("app.email.responder.revise_draft", fake_revise)
    monkeypatch.setattr(runner, "_requeue_revised_email", fake_requeue)

    out = await nodes.card_resolution_node(_state(user_message="make it shorter"))
    assert out["card_handled"] is True
    assert out["card_outcomes"][0]["decision_status"] == "discarded"
    assert out["card_outcomes"][0]["new_card"]["approval_id"] == "uuid-2"
    assert "revised" in out["final_response"].lower()


# --- no double-write: in-graph grounding suppression -------------------------
async def test_record_outcome_in_graph_suppresses_thread_grounding(monkeypatch):
    """A chat-queued tool card's thread_id IS the conversation thread. The node writes the
    outcome reply itself, so resolve_and_dispatch(ground_thread=False) must persist the ROW
    (HUD) but NOT also ground the thread — else the outcome is written twice on reload."""
    from app.agent.approval_dispatch import _record_outcome

    persisted: list = []
    grounded: list = []

    async def fake_persist(aid, status, detail):
        persisted.append((status, detail))

    async def fake_note(thread_id, marker):
        grounded.append(marker)

    monkeypatch.setattr("app.agent.approval_dispatch._persist_outcome", fake_persist)
    monkeypatch.setattr("app.agent.runner.note_approval_outcome", fake_note)
    outcome = ApprovalDispatchOutcome(
        kind="tool", status="executed", success=True,
        detail="Event created.", thread_id="web:master")

    # in-graph resolver: ROW persisted, thread NOT grounded (no double)
    await _record_outcome("a", outcome, ground_thread=False)
    assert persisted == [("executed", "Event created.")]
    assert grounded == []

    # default (dashboard/Telegram button — no turn to record it): still grounds
    await _record_outcome("a", outcome, ground_thread=True)
    assert grounded == ["✅ Event created."]


# --- pure helpers -------------------------------------------------------------
def test_route_after_card():
    assert nodes.route_after_card({"card_handled": True}) == "persist"
    assert nodes.route_after_card({"card_handled": False}) == "agent"
    assert nodes.route_after_card({}) == "agent"


def test_card_outcome_events():
    assert runner._card_outcome_events("t", []) == []
    ap = runner._card_outcome_events("t", [{"approval_id": "a", "decision_status": "approved"}])
    assert ap[0]["type"] == "decision_resolved" and ap[0]["content"]["status"] == "approved"
    sk = runner._card_outcome_events("t", [{"approval_id": "a", "nav": "skip"}])
    assert sk[0]["type"] == "presented_nav"
    ed = runner._card_outcome_events(
        "t", [{"approval_id": "a", "decision_status": "discarded", "new_card": {"x": 1}}])
    assert [e["type"] for e in ed] == ["decision_resolved", "approval_required"]
    # a stale (lost-claim) outcome emits NO flip event
    assert runner._card_outcome_events("t", [{"approval_id": "a", "decision_status": "stale"}]) == []
