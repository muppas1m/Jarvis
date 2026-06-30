"""SAFETY SEAL (D15/D16): a generic command must NEVER resolve the WRONG card.

Reproduces the live failure — multiple live APPROVE cards + a stale oldest-pending
presented_approval_id + "Send it" → the node SENT a stale Fernandes email the master never
approved. The seal (Layer 0 + the deterministic referent gate): the node reads the
authoritative live set (NOT the client pointer) and resolves only when exactly one target is
unambiguous; otherwise it REFUSES and names the choices — it never dispatches the wrong card.

Deterministic: the intent judge + the live-set read are mocked so the GATE logic is what's under
test. The real claim/dispatch is spied (must NOT fire on a refusal).
"""
import app.agent.approval_dispatch as approval_dispatch
import app.agent.nodes as nodes
import app.agent.runner as runner
from app.agent.approval_dispatch import ApprovalDispatchOutcome
from app.approvals_service import UnifiedApprovalCard


def _card(approval_id, kind, tool_name, **targs):
    return UnifiedApprovalCard(
        approval_id=approval_id, kind=kind, thread_id="web:master", tool_name=tool_name,
        tool_args=targs, description=f"{tool_name} {targs}", status="pending",
        created_at="2026-06-30T00:00:00+00:00",
    )


E1 = _card("a35f89f5", "email", "email_send", to="fernandes@yahoo.me", subject="Amazon Delivery Pickup", body="hi")
E2 = _card("b58bad40", "email", "email_send", to="fernandes@yahoo.me", subject="Amazon Delivery Pickup", body="hi M")
C = _card("7e38148f", "tool", "calendar_create", title="Boat Party", start_iso="2026-06-30T19:00:00+00:00")


def _state(presented, message):
    return {
        "presented_approval_id": presented, "presented_via": "web",
        "user_message": message, "thread_id": "web:master", "messages": [],
    }


def _patch_judge(monkeypatch, intent):
    async def fake(aid, message, recent_context=""):
        return runner._PresentedJudgment(approval_id=aid, row=object(), intent=intent, change="")
    monkeypatch.setattr(runner, "_judge_presented", fake)


def _patch_live(monkeypatch, cards):
    async def fake():
        return list(cards)
    monkeypatch.setattr("app.approvals_service.list_pending_cards", fake)


def _spy_dispatch(monkeypatch):
    rec = {"calls": []}

    async def fake(approval_id, action, resolved_via, decision, *, ground_thread=True):
        rec["calls"].append((approval_id, action))
        return ApprovalDispatchOutcome(
            kind="tool", status="executed", success=True, detail="done", thread_id="web:master")
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    return rec


# --- THE REPRODUCTION: 2 live cards + stale pointer + "Send it" → NO wrong dispatch ---
async def test_multiple_live_cards_generic_send_refuses_not_dispatches(monkeypatch):
    _patch_judge(monkeypatch, "approve")
    _patch_live(monkeypatch, [E1, C])          # 2 live APPROVE cards (the failure shape)
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(_state(presented="a35f89f5", message="Send it"))
    # THE SEAL: nothing dispatched — it refused
    assert rec["calls"] == []
    assert out["card_handled"] is True
    assert "card_outcome" not in out or not out["card_outcome"].get("decision_status")
    # it named the choices
    low = out["final_response"].lower()
    assert "fernandes" in low and "boat party" in low.lower() or "calendar" in low


async def test_multiple_live_cards_generic_reject_also_refuses(monkeypatch):
    _patch_judge(monkeypatch, "reject")
    _patch_live(monkeypatch, [E1, C])
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(_state(presented="a35f89f5", message="reject it"))
    assert rec["calls"] == []                  # reject is sealed too (Step-4 wrong-reject)
    assert out["card_handled"] is True


# --- count==1 happy path: a bare generic command resolves the single live card ---
async def test_single_live_card_generic_send_resolves_it(monkeypatch):
    _patch_judge(monkeypatch, "approve")
    _patch_live(monkeypatch, [C])              # exactly one live card
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(_state(presented="7e38148f", message="Send it"))
    assert rec["calls"] == [("7e38148f", "approve")]   # the one live card, dispatched
    assert out["card_outcome"]["decision_status"] == "approved"


# --- count==1 KIND MISMATCH: words name a kind the one live card isn't → REFUSE (step 8) ---
async def test_single_email_card_approve_calendar_event_refuses(monkeypatch):
    _patch_judge(monkeypatch, "approve")
    _patch_live(monkeypatch, [E1])             # one EMAIL card live
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(
        _state(presented="a35f89f5", message="I approve the calendar event"))
    assert rec["calls"] == []                  # "calendar" mismatches the email card → refuse
    assert out["card_handled"] is True


# --- SUBSTITUTION hole (expiry-race / TOCTOU): presented card not live, a DIFFERENT one is → REFUSE ---
async def test_substitution_blocked_when_presented_card_not_live(monkeypatch):
    _patch_judge(monkeypatch, "approve")
    _patch_live(monkeypatch, [C])              # only C is live (id 7e38148f)
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(_state(presented="a35f89f5", message="Send it"))
    assert rec["calls"] == []                  # aid (a35f89f5) != the live card → NEVER substitute
    assert "already taken care of" in out["final_response"].lower()


# --- count==1 NAMED-target mismatch (not just a kind word): "approve the boat party" vs an email ---
async def test_named_target_mismatch_at_count1_refuses(monkeypatch):
    _patch_judge(monkeypatch, "approve")
    _patch_live(monkeypatch, [E1])             # one EMAIL card (to Fernandes)
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(
        _state(presented="a35f89f5", message="approve the boat party"))
    assert rec["calls"] == []                  # "boat party" isn't this email → refuse, don't send
    assert out["card_handled"] is True


# --- item 1: a NEW same-kind request must NOT resolve the one unrelated card (gate as backstop) ---
async def test_new_same_kind_request_does_not_resolve_wrong_card(monkeypatch):
    """If the judge mis-fires 'approve' on a NEW request ("send an email to bob") while one
    UNRELATED email card is live, the gate must still REFUSE — 'email' is a kind word (stripped),
    so the match is on 'bob', which isn't this Fernandes card. The gate is the backstop the llama
    primary needs."""
    _patch_judge(monkeypatch, "approve")
    _patch_live(monkeypatch, [E1])                 # one email card, to fernandes
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(
        _state(presented="a35f89f5", message="send an email to bob asking about lunch"))
    assert rec["calls"] == []                      # 'bob'/'lunch' != fernandes → refuse, do NOT send
    assert out["card_handled"] is True


# --- count==1 reject resolves the one card ---
async def test_single_live_card_reject_resolves_it(monkeypatch):
    _patch_judge(monkeypatch, "reject")
    _patch_live(monkeypatch, [E1])
    rec = _spy_dispatch(monkeypatch)
    out = await nodes.card_resolution_node(_state(presented="a35f89f5", message="reject it"))
    assert rec["calls"] == [("a35f89f5", "reject")]
    assert out["card_outcome"]["decision_status"] == "rejected"
    assert "fernandes" in out["final_response"].lower()  # D16: names the actual card
