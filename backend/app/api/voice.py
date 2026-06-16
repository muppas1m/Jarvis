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
import asyncio
import json
import uuid
from typing import AsyncIterator, Optional

import numpy as np
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agent.runner import voice_turn
from app.config import settings
from app.security.auth import UserContext, get_current_user
from app.utils.logging import get_logger
from app.voice.wakeword import new_model, score_key

logger = get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# Separate router for the wake-word WS: it cannot use the protected router's HTTP
# `get_current_user` dependency (a browser WebSocket can't set X-API-Key headers),
# so it self-authenticates on a short-lived JWT ticket — see `wake_ws`. Mounted
# in the public tier by app/api/router.py.
ws_router = APIRouter(prefix="/voice", tags=["voice"])


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


@ws_router.websocket("/wake")
async def wake_ws(websocket: WebSocket, ticket: str = Query(default="")) -> None:
    """Always-on wake-word stream (Phase 4.2). The browser sends 16 kHz mono
    int16 PCM frames; we score each with openWakeWord "hey jarvis" and push back
    {"event":"wake","score":…} when it crosses WAKE_THRESHOLD.

    Auth: the browser can't set X-API-Key on a WS handshake, so it authenticates
    with a **short-lived JWT ticket** (HS256, signed by the BFF with the shared
    AUTH_SECRET, ~60s expiry) passed as `?ticket=`. We validate it with the same
    `_verify_jwt` the HTTP auth uses. No long-lived secret reaches the browser.
    """
    # Local import keeps the validator next to its HTTP sibling without exporting it.
    from app.security.auth import _verify_jwt

    claims = _verify_jwt(ticket) if ticket else None
    if not claims or not claims.get("sub"):
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()
    # Per-connection model (prediction state is per-stream); load off the loop.
    # The model's VAD gate uses WAKE_VAD_THRESHOLD; the fire score uses
    # WAKE_THRESHOLD below — the two are decoupled.
    model = await asyncio.to_thread(new_model, settings.WAKE_VAD_THRESHOLD)
    key = score_key(model)
    logger.info("wake_ws_open", user=claims.get("sub"))
    try:
        while True:
            data = await websocket.receive_bytes()
            audio = np.frombuffer(data, dtype=np.int16)
            if audio.size == 0:
                continue
            scores = await asyncio.to_thread(model.predict, audio)
            score = float(scores.get(key, 0.0))
            if score > settings.WAKE_THRESHOLD:
                await websocket.send_json({"event": "wake", "score": score})
                model.reset()  # don't re-fire on the tail of the same utterance
    except WebSocketDisconnect:
        logger.info("wake_ws_closed")
    except Exception as exc:  # noqa: BLE001 — never crash the worker on a bad frame
        logger.warning("wake_ws_error", error=str(exc))
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
