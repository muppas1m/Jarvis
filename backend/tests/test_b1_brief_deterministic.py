"""B1-brief — deterministic delivery + offered|delivered state + HWM-after-persist
(CH-10 / D-B1-7 / NEW-1). Red-first for the three failing scenarios."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.agent.nodes as nodes

_MARK = f"test-b1br-{uuid.uuid4().hex[:8]}"


def _offer(state=None, text="3 items await, Sir. Shall I brief you?", mid=None):
    meta = {"type": "briefing"}
    if state is not None:
        meta["state"] = state
    return AIMessage(content=text, id=mid, additional_kwargs={"jarvis": meta})


def _verb(monkeypatch, verb, committed=False, hedged=False):
    async def fake(user_message, question, recent_context=""):
        return SimpleNamespace(verb=verb, hedged=hedged, change="", committed=committed)
    import app.agent.decision_resolver as dr
    monkeypatch.setattr(dr, "resolve_answer_verb", fake)


def _fetch(monkeypatch, text="• item one\n• item two"):
    calls = {"n": 0}

    async def fake():
        calls["n"] += 1
        return text
    import app.agent.tools.briefing_tool as bt
    monkeypatch.setattr(bt, "fetch_latest_brief", fake)
    return calls


# ---------------- scenario 1 — "yes" to an offer DELIVERS, by code ------------- #
@pytest.mark.asyncio
async def test_yes_to_offer_delivers_deterministically(monkeypatch):
    _verb(monkeypatch, "none", committed=True)                 # a committed bare "yes"
    calls = _fetch(monkeypatch)
    out = await nodes.card_resolution_node({
        "user_message": "yes", "thread_id": f"web:{_MARK}-d1",
        "messages": [_offer(state="offered", mid="off-1"), HumanMessage(content="yes")]})
    assert calls["n"] == 1, "the CODE must fetch — no model signal involved"
    assert "item one" in (out.get("final_response") or "")
    assert out.get("card_handled") is True
    assert out.get("briefing_attached") is True                 # persist won't double-attach
    delivered = [m for m in out["messages"]
                 if ((m.additional_kwargs or {}).get("jarvis") or {}).get("state") == "delivered"]
    assert delivered, "the brief message must be stamped state=delivered"
    stamped = [m for m in out["messages"] if getattr(m, "id", None) == "off-1"]
    assert stamped and stamped[0].additional_kwargs["jarvis"]["state"] == "accepted"


@pytest.mark.asyncio
async def test_decline_stamps_and_routes_to_agent(monkeypatch):
    _verb(monkeypatch, "reject")
    calls = _fetch(monkeypatch)
    out = await nodes.card_resolution_node({
        "user_message": "no thanks", "thread_id": f"web:{_MARK}-d2",
        "messages": [_offer(state="offered", mid="off-2"), HumanMessage(content="no thanks")]})
    assert calls["n"] == 0                                      # nothing fetched
    assert out.get("card_handled") is not True                  # the agent phrases the ack
    stamped = [m for m in out.get("messages", []) if getattr(m, "id", None) == "off-2"]
    assert stamped and stamped[0].additional_kwargs["jarvis"]["state"] == "declined"


@pytest.mark.asyncio
async def test_unrelated_leaves_the_offer_outstanding(monkeypatch):
    _verb(monkeypatch, "unrelated")
    out = await nodes.card_resolution_node({
        "user_message": "what's on my calendar?", "thread_id": f"web:{_MARK}-d3",
        "messages": [_offer(state="offered", mid="off-3"), HumanMessage(content="what's on my calendar?")]})
    assert out.get("card_handled") is not True
    assert not [m for m in out.get("messages", []) if getattr(m, "id", None) == "off-3"]


# ---------------- scenario 2 (NEW-1) — delivered ≠ offered --------------------- #
def test_delivered_brief_never_sets_offer_pending():
    ref = nodes._conversation_referent([_offer(state="delivered", text="Here's your brief …"),
                                        HumanMessage(content="yes")])
    assert ref is None, f"a DELIVERED brief read as an outstanding offer: {ref}"


def test_offered_still_sets_offer_pending():
    ref = nodes._conversation_referent([_offer(state="offered"), HumanMessage(content="yes")])
    assert ref is not None and ref["offer_pending"] is True


def test_legacy_untagged_briefing_reads_as_offered():
    """Consent-safe default: a legacy (state-less) briefing message counts as an offer —
    a bare 'yes' goes to the offer/agent, never to a card."""
    ref = nodes._conversation_referent([_offer(state=None), HumanMessage(content="yes")])
    assert ref is not None and ref["offer_pending"] is True


@pytest.mark.asyncio
async def test_bare_yes_after_delivered_brief_is_a_normal_agent_turn(monkeypatch):
    _verb(monkeypatch, "none", committed=True)
    calls = _fetch(monkeypatch)
    out = await nodes.card_resolution_node({
        "user_message": "yes", "thread_id": f"web:{_MARK}-n1",
        "messages": [_offer(state="delivered", text="Here's your brief …"), HumanMessage(content="yes")]})
    assert out == {} or out.get("card_handled") is not True     # agent turn — no re-deliver
    assert calls["n"] == 0                                      # and no "already queued"


# ---------------- scenario 3 — the HWM advances only after persist ------------- #
@pytest.mark.asyncio
async def test_fetch_does_not_advance_the_hwm(monkeypatch):
    import app.agent.tools.briefing_tool as bt
    spy = AsyncMock()
    monkeypatch.setattr(bt, "mark_briefed", spy, raising=False)
    monkeypatch.setattr("app.agent.briefing_state.mark_briefed", spy)
    win = SimpleNamespace(start=None, end=None)
    monkeypatch.setattr(bt, "seen_window", AsyncMock(return_value=win), raising=False)
    text = await bt.fetch_latest_brief()
    assert spy.await_count == 0, "the fetch must NEVER advance the HWM (crash-loss window)"


@pytest.mark.asyncio
async def test_compact_advances_the_hwm_after_persist(monkeypatch):
    """B1-brief-2 migration: the channel is STATE (a ContextVar dies at the node boundary —
    the graph-level tests below prove the live wiring; this pins compact's consumption)."""
    import app.agent.briefing_state as bs
    spy = AsyncMock()
    monkeypatch.setattr(bs, "mark_briefed", spy)
    now = __import__("datetime").datetime.now(__import__("datetime").UTC)
    await nodes.compact_node({"messages": [], "thread_id": f"web:{_MARK}-h1",
                              "running_summary": "", "hwm_pending_advance": now.isoformat()})
    assert spy.await_count == 1, "compact (post-persist) must consume the pending advance"
    assert spy.await_args.args[0] == now


@pytest.mark.asyncio
async def test_crash_before_compact_leaves_items_unseen(monkeypatch):
    """The crash corner: fetch happened, the turn died before compact → the var dies with the
    task; nothing marks the items seen. (Here: simply assert no advance happened at fetch.)"""
    import app.agent.briefing_state as bs
    spy = AsyncMock()
    monkeypatch.setattr(bs, "mark_briefed", spy)
    import app.agent.tools.briefing_tool as bt
    win = SimpleNamespace(start=None, end=None)
    monkeypatch.setattr(bt, "seen_window", AsyncMock(return_value=win), raising=False)
    await bt.fetch_latest_brief()
    assert spy.await_count == 0


# --------------------------------------------------------------------------- #
# B1-brief-2 (#1 BLOCKER) — the keep-rule is STATE-gated: the outstanding OFFER  #
# survives compaction, not whichever briefing message is most recent            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_keep_rule_keeps_the_offer_not_the_delivered_brief():
    from datetime import UTC, datetime, timedelta
    from sqlalchemy import delete
    from app.db.engine import async_session
    from app.db.models import PendingApproval
    thread = f"web:{_MARK}-keep"
    async with async_session() as s:
        row = PendingApproval(thread_id=thread, interrupt_id=f"{_MARK}-k", action_type="email_send",
                              description="d", payload={"tool_name": "email_send",
                                                        "tool_args": {"to": "b@x.com", "subject": "S", "body": "x"}},
                              status="pending", expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row); await s.commit(); await s.refresh(row)
        rid = str(row.id)
    approval = AIMessage(content="queued — shall I go ahead?", additional_kwargs={"jarvis": {
        "type": "approval", "approval_ids": [rid], "mint_class": "fresh", "solicited": True}})
    offered = _offer(state="offered", text="3 items await. Shall I brief you?")
    delivered = _offer(state="delivered", text="Here's your brief …")
    try:
        removable = await nodes._drop_pending_linked([approval, offered, delivered])
        assert offered not in removable, "the OUTSTANDING offer was compactable (#1)"
        kept = [m for m in [approval, offered, delivered] if m not in removable]
        ref = nodes._conversation_referent(kept + [HumanMessage(content="yes")])
        assert ref["offer_pending"] is True, "post-compaction, the bare yes lost its offer owner"
    finally:
        async with async_session() as s:
            await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
            await s.commit()


# --------------------------------------------------------------------------- #
# B1-brief-2 (#2) — "yes" consumes EVERY outstanding offer, not just the latest  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_yes_stamps_all_outstanding_offers(monkeypatch):
    _verb(monkeypatch, "none", committed=True)
    _fetch(monkeypatch)
    out = await nodes.card_resolution_node({
        "user_message": "yes", "thread_id": f"web:{_MARK}-two",
        "messages": [_offer(state="offered", text="old offer", mid="off-a"),
                     AIMessage(content="chat"),
                     _offer(state="offered", text="new offer", mid="off-b"),
                     HumanMessage(content="yes")]})
    stamped = {getattr(m, "id", None): ((m.additional_kwargs or {}).get("jarvis") or {}).get("state")
               for m in out.get("messages", []) if getattr(m, "id", None) in ("off-a", "off-b")}
    assert stamped.get("off-a") == "accepted" and stamped.get("off-b") == "accepted", \
        f"an offer stayed outstanding → the next yes re-delivers: {stamped}"


# --------------------------------------------------------------------------- #
# B1-brief-2 (#3 BLOCKER) — GRAPH-level: the HWM advance actually fires in the   #
# live graph (a ContextVar dies at the node boundary; the channel must be state) #
# --------------------------------------------------------------------------- #
@pytest.fixture
async def _real_graph():
    import contextlib
    import app.agent.runner as runner
    from app.agent import graph as graph_module
    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None
    from app.agent.graph import init_checkpointer
    await init_checkpointer()
    runner._graph = None
    yield runner
    runner._graph = None


def _initial(thread, msgs, user):
    return {"messages": [*msgs, HumanMessage(content=user)], "thread_id": thread,
            "platform": "web", "channel_user_id": "u", "user_message": user,
            "tool_calls_this_turn": 0, "queued_signatures": [], "queued_this_turn": [],
            "final_response": "", "terminal_delta": "", "briefing_attached": False,
            "card_context": "", "card_handled": False, "card_outcomes": [],
            "edit_expected": False, "edit_target_id": "", "edit_tool_name": "",
            "hwm_pending_advance": ""}


@pytest.mark.asyncio
async def test_graph_ainvoke_advances_hwm_exactly_once(monkeypatch, _real_graph):
    import app.agent.briefing_state as bs
    spy = AsyncMock()
    monkeypatch.setattr(bs, "mark_briefed", spy)
    _verb(monkeypatch, "none", committed=True)
    _fetch(monkeypatch)
    g = _real_graph.graph()
    thread = f"web:{_MARK}-g1"
    await g.ainvoke(_initial(thread, [_offer(state="offered", mid="off-g1")], "yes"),
                    config={"configurable": {"thread_id": thread}})
    assert spy.await_count == 1, \
        f"mark_briefed fired {spy.await_count}× in the LIVE graph (the channel died at a node boundary)"


@pytest.mark.asyncio
async def test_graph_astream_advances_hwm_exactly_once(monkeypatch, _real_graph):
    import app.agent.briefing_state as bs
    spy = AsyncMock()
    monkeypatch.setattr(bs, "mark_briefed", spy)
    _verb(monkeypatch, "none", committed=True)
    _fetch(monkeypatch)
    g = _real_graph.graph()
    thread = f"web:{_MARK}-g2"
    async for _ in g.astream(_initial(thread, [_offer(state="offered", mid="off-g2")], "yes"),
                             config={"configurable": {"thread_id": thread}}):
        pass
    assert spy.await_count == 1, f"astream: mark_briefed fired {spy.await_count}×"
