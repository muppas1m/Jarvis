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
