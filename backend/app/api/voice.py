"""POST /api/voice/stream — SSE token-streamed + spoken agent turn (Phase 4 4.1).

Same logical turn as /api/chat/stream, but routed to the fast tier (§B two-speed
cascade) and carrying per-sentence audio events. The event contract lives in
`app.agent.runner.voice_turn`:
  thread_id · token (caption) · tool · audio {text, audio(b64), mime, filler} ·
  approval_required · done · error.

The browser plays the audio and feeds it through an AnalyserNode so the orb
pulses to Jarvis's voice. Auth is the standard protected-router dependency
(the dashboard BFF attaches X-API-Key).
"""
import json
import uuid
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.runner import voice_turn
from app.security.auth import UserContext, get_current_user

router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: Optional[str] = Field(default=None)


@router.post("/stream", response_model=None)
async def voice_stream(
    payload: VoiceRequest,
    user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    thread_id = payload.thread_id or f"web:{uuid.uuid4().hex[:12]}"

    async def event_stream() -> AsyncIterator[str]:
        async for event in voice_turn(
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
