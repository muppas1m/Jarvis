"""Deploy-time drain of pre-cutover paused-at-interrupt() checkpoints (Phase 3).

Before the cutover, an APPROVE-tier tool call paused the graph at ``interrupt()``
and left a checkpoint whose ``next`` is non-empty with a live ``task.interrupts``
and an UNanswered tool_call. The cutover retired ``interrupt()``, so nothing new
pauses — but checkpoints paused at deploy time are still out there. Run this ONCE
after deploying the cutover to clear them.

For each paused thread it injects a ``[DRAINED]`` ToolMessage answering the
orphaned tool_call(s) — advancing the checkpoint past the interrupt (the SAME
``aupdate_state(as_node=...)`` mechanism ``_recover_cancellation_residue`` uses).
The action is NOT executed and the thread is NOT resumed: the corresponding
``PendingApproval`` row is left PENDING, so the master still approves/rejects it
on the Approvals screen (resolving through the claim-gated dispatcher, executing
out-of-band) — or it expires. Draining only un-wedges the graph + answers the
orphan so a future free-text turn can't 400 on it (the Jun-11 shape).

Idempotent: a thread with no live interrupt is skipped, so a re-run is a no-op.

Run:  python -m app.agent.approval_drain
"""
from __future__ import annotations

import asyncio
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import text

from app.agent.runner import _collect_interrupts, graph
from app.db.engine import async_session
from app.utils.logging import get_logger

logger = get_logger(__name__)

_DRAIN_MARKER = (
    "[DRAINED] This action was queued for the master's approval and is still "
    "awaiting it on the Approvals screen — it was NOT executed. (Deploy-time "
    "drain of a pre-cutover paused turn.)"
)

# The interrupted node in the prod topology (graph.py: add_node("tool_executor", …)).
# Injecting the answering ToolMessage AS this node clears its task.interrupts and
# lets should_continue_tools route onward — validated against a real paused
# checkpoint before this shipped.
_INTERRUPTED_NODE = "tool_executor"


def _orphaned_tool_calls(state: Any) -> list[str]:
    """The tool_call ids in the thread's AIMessages that have no answering
    ToolMessage yet — i.e. the calls the interrupt paused on."""
    msgs = (getattr(state, "values", None) or {}).get("messages") or []
    answered = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage)}
    orphans: list[str] = []
    for m in msgs:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            orphans.extend(tc["id"] for tc in m.tool_calls if tc["id"] not in answered)
    return orphans


async def drain_thread(thread_id: str) -> str:
    """Drain ONE thread. Returns 'skipped' (not paused at an interrupt), 'drained'
    (interrupt cleared), or 'still_paused' (the advance didn't take — surfaced, not
    swallowed). Never touches PendingApproval rows."""
    config = {"configurable": {"thread_id": thread_id}}
    state = await graph().aget_state(config)
    if not _collect_interrupts(state):
        return "skipped"

    orphans = _orphaned_tool_calls(state)
    drained = [ToolMessage(content=_DRAIN_MARKER, tool_call_id=tc) for tc in orphans]
    # Empty `drained` still advances the paused step (mirrors the cancellation-
    # residue recovery): the as_node write supersedes the interrupt task.
    await graph().aupdate_state(config, {"messages": drained}, as_node=_INTERRUPTED_NODE)

    after = await graph().aget_state(config)
    if _collect_interrupts(after):
        logger.warning("drain_thread_still_paused", thread_id=thread_id)
        return "still_paused"
    logger.info("drain_thread_drained", thread_id=thread_id, orphans=len(orphans))
    return "drained"


async def _all_checkpoint_thread_ids() -> list[str]:
    """Distinct thread_ids in the AsyncPostgresSaver checkpoint store."""
    async with async_session() as session:
        rows = await session.execute(text("SELECT DISTINCT thread_id FROM checkpoints"))
        return [r[0] for r in rows.all()]


async def drain_all_paused() -> dict[str, list[str]]:
    """Drain every paused-at-interrupt checkpoint in the store. Idempotent."""
    report: dict[str, list[str]] = {"drained": [], "skipped": [], "still_paused": []}
    for thread_id in await _all_checkpoint_thread_ids():
        report[await drain_thread(thread_id)].append(thread_id)
    logger.info(
        "drain_all_paused_complete",
        drained=len(report["drained"]),
        skipped=len(report["skipped"]),
        still_paused=len(report["still_paused"]),
    )
    return report


async def _main() -> None:
    from app.agent.graph import init_checkpointer

    await init_checkpointer()
    report = await drain_all_paused()
    print(  # noqa: T201 — a deploy command's stdout summary
        f"drain complete: drained={len(report['drained'])} "
        f"skipped={len(report['skipped'])} still_paused={len(report['still_paused'])}"
    )
    if report["still_paused"]:
        print(f"  STILL PAUSED (inspect): {report['still_paused']}")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(_main())
