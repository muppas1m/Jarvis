"""Tier: REGRESSION (real graph, model pinned) — deterministic consent guarantees.

Each test is a full GRAPH journey (run_turn → the production entry) with the agent
scripted and the judges pinned: a red here is a broken invariant, never model noise.
First classes: B1-1 (resolve-by-word) and B1-2's deterministic half (F4 re-ask)."""
import pytest

from tests.harness import (cleanup_thread, ensure_graph, inject_history, mint_message,
                           pin_decision_judge, scratch_thread, seed_card, spy_dispatch)


@pytest.mark.asyncio
async def test_b1_1_resolve_by_word_single_card(monkeypatch):
    """B1-1: one waiting card + a committed word → dispatches THAT card, names it, no loop."""
    runner = await ensure_graph()
    thread = scratch_thread("reg-b11")
    rid = await seed_card(thread, "email_send",
                          {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    await inject_history(thread, [mint_message([rid], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "approve")
    try:
        out = await runner.run_turn("send it", thread, "web", "harness")
        assert rec["calls"] == [(rid, "approve")], f"did not resolve: {rec['calls']}"
        text = (out.get("response") or "").lower()
        assert "chintu" in text or "lunch" in text            # names the card
        assert "which one" not in text                        # no loop
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_2_noncommittal_reasks_then_committed_sends(monkeypatch):
    """B1-2 (deterministic half): 'hmm, maybe' re-asks and sends NOTHING; the follow-up
    committed word then dispatches — the full two-turn journey on the real graph."""
    runner = await ensure_graph()
    thread = scratch_thread("reg-b12")
    rid = await seed_card(thread, "email_send",
                          {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    await inject_history(thread, [mint_message([rid], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "unclear", hedged=True)
    try:
        await runner.run_turn("hmm, maybe", thread, "web", "harness")
        assert rec["calls"] == [], "a non-committal reply dispatched"
        pin_decision_judge(monkeypatch, "approve")            # turn 2: committed
        await runner.run_turn("yes, send it", thread, "web", "harness")
        assert rec["calls"] == [(rid, "approve")], f"the committed follow-up failed: {rec['calls']}"
    finally:
        await cleanup_thread(thread)


def _cal_args():
    return {"event_id": "e1", "title": "Lunch with friends", "start_iso": "2026-07-25T17:00:00-04:00"}


def _email_args(to="chintu@gmail.com", subject="Lunch Invitation"):
    return {"to": to, "subject": subject, "body": "x"}


@pytest.mark.asyncio
async def test_b1_3_multi_card_asks_then_kind_resolves(monkeypatch):
    """B1-3: email+calendar pending; 'send it' asks which; 'the calendar one' resolves THAT."""
    from tests.harness import pin_verb_judge
    runner = await ensure_graph()
    thread = scratch_thread("reg-b13")
    r_email = await seed_card(thread, "email_send", _email_args())
    r_cal = await seed_card(thread, "calendar_update", _cal_args())
    await inject_history(thread, [mint_message([r_email, r_cal], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "approve")
    try:
        out1 = await runner.run_turn("send it", thread, "web", "harness")
        assert rec["calls"] == []                              # ambiguity never dispatches
        assert "which" in (out1.get("response") or "").lower() # asks
        pin_verb_judge(monkeypatch, "none")                    # selection-only answer
        await runner.run_turn("the calendar one", thread, "web", "harness")
        assert rec["calls"] == [(r_cal, "approve")], f"kind selection missed: {rec['calls']}"
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_4_both_dispatches_both_and_flips_both(monkeypatch):
    """B1-4: 'approve both' → BOTH dispatch; card_outcomes carries BOTH (every card greys)."""
    from tests.harness import pin_verb_judge
    runner = await ensure_graph()
    thread = scratch_thread("reg-b14")
    r1 = await seed_card(thread, "email_send", _email_args())
    r2 = await seed_card(thread, "calendar_update", _cal_args())
    await inject_history(thread, [mint_message([r1, r2], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "approve")
    try:
        await runner.run_turn("go ahead", thread, "web", "harness")       # → the question
        pin_verb_judge(monkeypatch, "none")                               # "both" = selector-only
        out = await runner.run_turn("I mean both", thread, "web", "harness")
        assert sorted(a for a, _ in rec["calls"]) == sorted([r1, r2])
        assert {v for _, v in rec["calls"]} == {"approve"}
        text = (out.get("response") or "").lower()
        assert "which one" not in text                                    # resolved, no loop
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_5_followup_resolves_the_question_that_asked(monkeypatch):
    """B1-5: the follow-up names a card NEXT TURN and resolves the question that asked it —
    never the identical re-ask loop."""
    from tests.harness import pin_verb_judge
    runner = await ensure_graph()
    thread = scratch_thread("reg-b15")
    r1 = await seed_card(thread, "email_send", _email_args(to="timmy@x.com", subject="Plans"))
    r2 = await seed_card(thread, "email_send", _email_args(to="amy@x.com", subject="Budget"))
    await inject_history(thread, [mint_message([r1, r2], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "reject")                             # reject-origin!
    try:
        out1 = await runner.run_turn("reject it", thread, "web", "harness")
        assert rec["calls"] == []
        pin_verb_judge(monkeypatch, "none")                               # name-only follow-up
        await runner.run_turn("the timmy one", thread, "web", "harness")
        assert rec["calls"] == [(r1, "reject")], f"carried intent lost: {rec['calls']}"
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_6_hedged_all_reconfirms(monkeypatch):
    """B1-6: 'maybe do them all later' over two cards re-confirms — a hedge is not consent."""
    from tests.harness import pin_verb_judge
    runner = await ensure_graph()
    thread = scratch_thread("reg-b16")
    r1 = await seed_card(thread, "email_send", _email_args())
    r2 = await seed_card(thread, "calendar_update", _cal_args())
    await inject_history(thread, [mint_message([r1, r2], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "unclear", hedged=True)
    pin_verb_judge(monkeypatch, "none", hedged=True)
    try:
        await runner.run_turn("maybe do them all later", thread, "web", "harness")
        assert rec["calls"] == [], f"a hedge dispatched: {rec['calls']}"
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_7_idiom_and_auxiliary_never_dispatch(monkeypatch):
    """B1-7: 'that's all for now' sends nothing; 'yes I will — go ahead' never resolves a
    will@ card by the auxiliary."""
    runner = await ensure_graph()
    thread = scratch_thread("reg-b17")
    r1 = await seed_card(thread, "email_send", _email_args(to="will@company.com", subject="Q3"))
    r2 = await seed_card(thread, "email_send", _email_args(to="amy@x.com", subject="Budget"))
    await inject_history(thread, [mint_message([r1, r2], solicited=True)])
    rec = spy_dispatch(monkeypatch)
    pin_decision_judge(monkeypatch, "approve")
    try:
        await runner.run_turn("that's all for now", thread, "web", "harness")
        assert rec["calls"] == [], "the idiom dispatched"
        await runner.run_turn("yes I will — go ahead", thread, "web", "harness")
        assert (r1, "approve") not in rec["calls"], "the auxiliary resolved the will@ card"
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_8_offer_yes_delivers_by_code(monkeypatch):
    """B1-8: greet-offer + 'yes' → the CODE delivers the brief (no model signal, no card)."""
    from langchain_core.messages import AIMessage

    from tests.harness import pin_brief_fetch, pin_verb_judge
    runner = await ensure_graph()
    thread = scratch_thread("reg-b18")
    offer = AIMessage(content="3 items await, Sir. Shall I brief you?",
                      additional_kwargs={"jarvis": {"type": "briefing", "state": "offered"}})
    await inject_history(thread, [offer])
    rec = spy_dispatch(monkeypatch)
    pin_verb_judge(monkeypatch, "none", committed=True)        # the committed bare "yes"
    pin_brief_fetch(monkeypatch)
    try:
        out = await runner.run_turn("yes", thread, "web", "harness")
        assert "briefing item one" in (out.get("response") or "")
        assert rec["calls"] == []                              # never a card dispatch
    finally:
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_9_tz_marker_until_set_then_wall_clock(monkeypatch):
    """B1-9: TZ unset → the queued-card floor renders the visible 'UTC' marker; column set →
    a fresh card renders the wall clock, no marker. (The capture tool itself is unit-covered;
    this is the journey render.)"""
    from sqlalchemy import select, update

    from app.db.engine import async_session
    from app.db.models import UserProfile
    runner = await ensure_graph()
    async with async_session() as s:                          # snapshot + ensure FULLY unset
        row = (await s.execute(select(UserProfile.timezone, UserProfile.always_on).limit(1))).first()
        prev, prev_ao = (row[0], dict(row[1] or {})) if row else (None, {})
        ao_cleared = {k: v for k, v in prev_ao.items() if k != "timezone"}
        await s.execute(update(UserProfile).values(timezone=None, always_on=ao_cleared))
        await s.commit()
    thread = scratch_thread("reg-b19")
    try:
        from app.approvals_service import UnifiedApprovalCard, describe_card
        from app.agent.master_tz import resolve_and_bind
        await resolve_and_bind()                              # the turn-entry bind, unset state
        card = UnifiedApprovalCard(
            approval_id="x", kind="tool", thread_id=thread, tool_name="calendar_create",
            tool_args={"title": "Lunch", "start_iso": "2026-07-25T17:00:00Z"},
            description="d", status="pending", created_at="2026-07-20T00:00:00+00:00")
        unset_render = describe_card(card)
        assert "5:00 pm UTC" in unset_render, f"the marker is missing: {unset_render!r}"
        async with async_session() as s:
            await s.execute(update(UserProfile).values(timezone="America/New_York"))
            await s.commit()
        await resolve_and_bind()                              # the next turn's bind
        set_render = describe_card(card)
        assert "1:00 pm" in set_render and "UTC" not in set_render, f"{set_render!r}"
    finally:
        async with async_session() as s:
            await s.execute(update(UserProfile).values(timezone=prev, always_on=prev_ao))
            await s.commit()
        await cleanup_thread(thread)


@pytest.mark.asyncio
async def test_b1_10_long_chat_keeps_pending_resolvable(monkeypatch):
    """B1-10: the history compacts; the pending card's mint + the open question SURVIVE and
    the card is still resolvable by word."""
    from langchain_core.messages import AIMessage, HumanMessage

    from tests.harness import pin_verb_judge
    runner = await ensure_graph()
    thread = scratch_thread("reg-b110")
    rid = await seed_card(thread, "email_send",
                          {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    filler = []
    for i in range(30):                                       # a long exchange
        filler += [HumanMessage(content=f"aside {i}: " + ("blah " * 40)),
                   AIMessage(content=f"reply {i}: " + ("word " * 40))]
    q = AIMessage(content="Just to confirm, Sir — approve the email to chintu?",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [rid], "kind": ""}})
    await inject_history(thread, [mint_message([rid], solicited=True), *filler, q])
    monkeypatch.setattr("app.config.settings.COMPACT_THRESHOLD_TOKENS", 500, raising=False)
    rec = spy_dispatch(monkeypatch)
    pin_verb_judge(monkeypatch, "none", committed=True)       # the committed "yes"
    try:
        await runner.run_turn("yes", thread, "web", "harness")
        assert rec["calls"] == [(rid, "approve")], f"pending lost after the long chat: {rec['calls']}"
    finally:
        await cleanup_thread(thread)
