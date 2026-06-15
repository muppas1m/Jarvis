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

  thread_id is optional. When missing we mint a fresh "web:<uuid>" thread
  so the dashboard can start a new conversation without juggling IDs.

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
import uuid
from typing import Any, AsyncIterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.runner import run_turn, stream_turn
from app.security.auth import UserContext, get_current_user

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: Optional[str] = Field(
        default=None,
        description="Existing conversation thread. If omitted a fresh web:<uuid> thread is minted.",
    )


@router.post("", response_model=None)
async def chat(
    payload: ChatRequest,
    user: UserContext = Depends(get_current_user),
) -> dict[str, Any]:
    thread_id = payload.thread_id or f"web:{uuid.uuid4().hex[:12]}"
    return await run_turn(
        user_message=payload.message,
        thread_id=thread_id,
        platform="web",
        channel_user_id=user.user_id,
    )


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
    thread_id = payload.thread_id or f"web:{uuid.uuid4().hex[:12]}"

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
