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
from app.voice.wakeword import VAD_FRAME_SIZE, new_model, new_vad, score_key

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
    """Always-on voice-in stream (Phase 4.2 wake-word + 4.3a barge-in). The
    browser sends 16 kHz mono int16 PCM frames over a SINGLE stream and switches
    what we score with a text control message ``{"mode":"wake"|"vad"}``:

      * **wake** (default) — score openWakeWord "hey jarvis"; push
        ``{"event":"wake","score":…}`` when it crosses WAKE_THRESHOLD.
      * **vad** ("listen-for-speech", used while Jarvis is RESPONDING) — score
        the bundled Silero VAD and push per-frame ``{"event":"speech","score":…}``
        so the client can detect the master's speech onset and barge in. The
        self-interrupt guard (ignore the first Nms of playback, require sustained
        speech, raised threshold) lives client-side, where playback state is.

    One stream, two scorers — no second ``getUserMedia``, no new dependency
    (reuses the already-local Silero). Auth: the browser can't set X-API-Key on a
    WS handshake, so it authenticates with a **short-lived JWT ticket** (HS256,
    signed by the BFF with the shared AUTH_SECRET, ~60s expiry) passed as
    ``?ticket=``; validated with the same ``_verify_jwt`` the HTTP auth uses.
    """
    # Local import keeps the validator next to its HTTP sibling without exporting it.
    from app.security.auth import _verify_jwt

    claims = _verify_jwt(ticket) if ticket else None
    if not claims or not claims.get("sub"):
        await websocket.close(code=1008)  # policy violation
        return

    await websocket.accept()
    # Per-connection detectors (prediction state is per-stream); load off the loop.
    # The model's VAD gate uses WAKE_VAD_THRESHOLD; the fire score uses
    # WAKE_THRESHOLD — the two are decoupled. The Silero VAD is lazy: only built
    # if the client actually enters barge-in mode.
    model = await asyncio.to_thread(new_model, settings.WAKE_VAD_THRESHOLD)
    key = score_key(model)
    vad = None
    mode = "wake"
    logger.info("wake_ws_open", user=claims.get("sub"))
    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break

            # Text frame = a mode-switch control message.
            text = msg.get("text")
            if text is not None:
                try:
                    new_mode = json.loads(text).get("mode")
                except (ValueError, AttributeError):
                    continue
                if new_mode not in ("wake", "vad") or new_mode == mode:
                    continue
                mode = new_mode
                if mode == "vad":
                    if vad is None:
                        vad = await asyncio.to_thread(new_vad)
                    vad.reset_states()
                else:
                    model.reset()  # drop stale wake state on the way back in
                continue

            data = msg.get("bytes")
            if not data:
                continue
            audio = np.frombuffer(data, dtype=np.int16)
            if audio.size == 0:
                continue

            try:
                if mode == "wake":
                    scores = await asyncio.to_thread(model.predict, audio)
                    score = float(scores.get(key, 0.0))
                    if score > settings.WAKE_THRESHOLD:
                        await websocket.send_json({"event": "wake", "score": score})
                        model.reset()  # don't re-fire on the same utterance's tail
                elif vad is not None:
                    score = float(
                        await asyncio.to_thread(vad.predict, audio, VAD_FRAME_SIZE)
                    )
                    await websocket.send_json({"event": "speech", "score": score})
            except Exception as exc:  # noqa: BLE001 — one bad frame never kills the stream
                logger.warning("wake_ws_frame_error", error=str(exc), mode=mode)
                continue
    except WebSocketDisconnect:
        logger.info("wake_ws_closed")
    except Exception as exc:  # noqa: BLE001 — never crash the worker on a bad frame
        logger.warning("wake_ws_error", error=str(exc))
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
