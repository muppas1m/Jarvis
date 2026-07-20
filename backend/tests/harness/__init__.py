"""Ledger item #2 — the two-tier harness (Tier 0: the net under everything).

Two tiers, one shared machinery:
  tests/regression/     REAL graph, MODEL PINNED (scripted agent + pinned judges) →
                        deterministic GUARANTEES. A red here is a broken invariant.
  tests/live_behavior/  REAL graph, REAL model, SAMPLED → behavior-class RATES.
                        Consent classes assert ZERO leaks in N; capability classes
                        assert rates. N scales via HARNESS_N (default small so the
                        tier rides the normal suite).

The harness makes docs/testing/manual_verification_plan.md's behavior classes
EXECUTABLE — the master's sitting becomes confirmation, not debugging. Zero
backend/app/ surface: everything here drives the system through its real entries.
"""
import os
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage

HARNESS_N = int(os.environ.get("HARNESS_N", "3"))


def scratch_thread(prefix: str = "harness") -> str:
    return f"web:{prefix}-{_uuid.uuid4().hex[:8]}"


async def ensure_graph():
    """The checkpointer gate — DISPOSE + REBIND unconditionally: pytest-asyncio gives every
    test its own event loop, and a checkpointer bound to an earlier loop dies with "Future
    attached to a different loop" (the known async-rebind trap). Mirrors the established
    real_checkpointer fixture, packaged for the harness."""
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
    return runner


async def seed_card(thread: str, tool_name: str, tool_args: dict, status: str = "pending") -> str:
    from app.db.engine import async_session
    from app.db.models import PendingApproval
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=f"h-{_uuid.uuid4().hex[:6]}",
            action_type=tool_name, description="harness card",
            payload={"tool_name": tool_name, "tool_args": tool_args}, status=status,
            expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


def mint_message(ids: list[str], solicited: bool = True,
                 text: str = "I've queued that for your approval, Sir — shall I go ahead?") -> AIMessage:
    """The REAL-shape jarvis-tagged mint (what queued_finish persists)."""
    return AIMessage(content=text, additional_kwargs={"jarvis": {
        "type": "approval", "approval_ids": ids, "mint_class": "fresh", "solicited": solicited}})


async def inject_history(thread: str, messages: list) -> None:
    """Land constructed messages in the REAL checkpoint (aupdate_state — the saved technique;
    in-script minting is unreliable per describe-instead-of-call)."""
    runner = await ensure_graph()
    await runner.graph().aupdate_state({"configurable": {"thread_id": thread}}, {"messages": messages})


async def cleanup_thread(thread: str) -> None:
    from sqlalchemy import delete, text as _text

    from app.db.engine import async_session
    from app.db.models import PendingApproval
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        for tbl in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            try:
                await s.execute(_text(f"DELETE FROM {tbl} WHERE thread_id = :t"), {"t": thread})
            except Exception:  # noqa: BLE001 — table variants across langgraph versions
                pass
        await s.commit()


def spy_dispatch(monkeypatch):
    """Regression tier: record dispatches, execute nothing."""
    import app.agent.approval_dispatch as approval_dispatch
    from app.agent.approval_dispatch import ApprovalDispatchOutcome
    rec = {"calls": []}

    async def fake(approval_id, action, resolved_via, decision=None, *, ground_thread=True):
        rec["calls"].append((str(approval_id), action))
        return ApprovalDispatchOutcome(kind="tool", status="executed", success=True,
                                       detail="done", thread_id="web:h")
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    return rec


def pin_agent(monkeypatch, responses: list):
    """Regression tier: the agent model is SCRIPTED (deterministic)."""
    class _Scripted:
        def __init__(self, rs):
            self._rs = list(rs)

        async def ainvoke(self, _msgs):
            return self._rs.pop(0)
    monkeypatch.setattr("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted(responses))


def pin_decision_judge(monkeypatch, intent: str, hedged: bool = False, change: str = ""):
    """Regression tier: pin judge-1 (the presented-card judge)."""
    from types import SimpleNamespace

    import app.agent.runner as runner

    async def fake(aid, message, recent_context="", require_pending=True):
        row = SimpleNamespace(payload={"tool_name": "email_send",
                                       "tool_args": {"to": "h@x.com", "subject": "H"}},
                              action_type="email_send", thread_id="web:h", status="pending",
                              description="d")
        return runner._PresentedJudgment(approval_id=aid, row=row, intent=intent,
                                         change=change, hedged=hedged)
    monkeypatch.setattr(runner, "_judge_presented", fake)
