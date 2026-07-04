"""
POST /api/chat — synchronous, non-streaming agent turn over HTTP.

Phase 1 dashboard surface + the canonical curl-able entry point. The
non-streaming POST is the contract test that proves the agent works
through HTTP at all; streaming (SSE or websocket) is a Phase 4 transport
upgrade that emits the SAME shape incrementally rather than as one
final response, so clients written against this endpoint don't break
when streaming lands.

Request:
  POST /api/chat
  Body: {"message": "...", "thread_id": "optional-..."}

  thread_id is optional. When omitted, the master's canonical web thread is
  resolved SERVER-SIDE from the authenticated identity (one continuous
  conversation) — the dashboard never supplies or stores a thread id.

Response shape: see TurnEnvelope in app.agent.runner — same shape returned
by /api/approvals/{id}/decide so clients write one renderer for both
transports. status="complete" carries the assistant text; status="interrupted"
carries the interrupt payload (approval_id, tool_name, description) and
the dashboard surfaces the approve/reject UI.

Note on `usage.cost_usd`: BEST-EFFORT, computed inline from
`litellm.completion_cost`. Providers not in LiteLLM's pricing table
(Groq today) contribute 0.0 to this number even though the request did
cost something. The AUTHORITATIVE source for cost data is `GET /api/costs`
— it reads `LLMUsageLog` rows the LiteLLM persistence callback writes
with provider-reported cost. The per-turn number here is a fast-path
hint for client UIs; production accounting belongs on `/costs`.
"""
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.runner import (
    canonical_thread_id,
    get_history,
    run_turn,
    stream_turn,
    thread_context,
)
from app.api.approvals import get_thread_decisions
from app.security.auth import UserContext, get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


def _conversation_items(
    messages: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Interleave message history with decision cards into ONE ordered timeline.

    A decision is positioned by its ``interrupt_id`` (== the tool_call_id of the
    AIMessage that proposed it), so cards land in conversation position WITHOUT
    needing message timestamps. Tool messages are dropped — their outcome shows in
    the card's status + the agent's following reply. The result is what the
    dashboard renders top-to-bottom: user/assistant bubbles + decision cards
    (pending / approved / rejected / discarded) in place across reloads."""
    by_interrupt = {d["interrupt_id"]: d for d in decisions if d.get("interrupt_id")}
    items: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role == "human":
            if content:
                items.append({"type": "message", "role": "user", "content": m["content"]})
        elif role == "ai":
            if content:
                items.append({"type": "message", "role": "assistant", "content": m["content"]})
            for tc in m.get("tool_calls") or []:
                decision = by_interrupt.get(tc.get("id"))
                if decision:
                    items.append({"type": "decision", **decision})
    return items


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: str | None = Field(
        default=None,
        description="Override the conversation thread (debugging). If omitted, the master's canonical server-side thread is used.",
    )


@router.post("", response_model=None)
async def chat(
    payload: ChatRequest,
    user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    thread_id = payload.thread_id or canonical_thread_id(user.user_id)
    return await run_turn(
        user_message=payload.message,
        thread_id=thread_id,
        platform="web",
        channel_user_id=user.user_id,
    )


@router.get("/history", response_model=None)
async def chat_history(
    thread_id: str | None = None,
    user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    """Replay the master's persisted conversation for the dashboard on reload.

    thread_id is optional: when omitted (the dashboard's normal call) the master's
    canonical thread is resolved SERVER-SIDE from the authenticated identity — the
    thread is never client-supplied. Returns an ordered ``items`` timeline (message
    bubbles + decision cards interleaved in conversation position) so a reload
    re-renders the conversation — including resolved/discarded decision cards —
    exactly where they happened. Read-only — runs no turn."""
    tid = thread_id or canonical_thread_id(user.user_id)
    messages = await get_history(tid)
    decisions = await get_thread_decisions(tid)
    return {
        "thread_id": tid,
        "items": _conversation_items(messages, decisions),
        "context": await thread_context(tid),  # 4.B.3 context meter (live=False on reload)
    }


@router.post("/stream", response_model=None)
async def chat_stream(
    payload: ChatRequest,
    user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    """SSE token-streaming chat for the dashboard (Phase 4 sub-phase 4.0).

    The same logical turn as POST /api/chat, emitted incrementally — one
    `data:` line per event (thread_id, token, tool, approval_required, done,
    error). The terminal event carries the authoritative envelope subset, so
    a client renders streamed tokens for perceived latency and reconciles to
    the canonical final on done/approval_required. See
    `app.agent.runner.stream_turn` for the event contract.
    """
    thread_id = payload.thread_id or canonical_thread_id(user.user_id)

    async def event_stream() -> AsyncIterator[str]:
        async for event in stream_turn(
            user_message=payload.message,
            thread_id=thread_id,
            platform="web",
            channel_user_id=user.user_id,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
