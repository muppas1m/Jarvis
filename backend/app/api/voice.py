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
from collections.abc import AsyncIterator
from email.utils import parseaddr

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.runner import canonical_thread_id, synth_line, voice_turn
from app.config import settings
from app.security.auth import UserContext, get_current_user
from app.utils.logging import get_logger
from app.voice.transcribe import CaptureEndpointer, transcribe_pcm
from app.voice.tts import audio_mime
from app.voice.wakeword import VAD_FRAME_SIZE, new_model, new_vad, score_key

# Worklet frame cadence — 1280 samples @ 16 kHz = 80 ms (see wake-worklet.js).
_FRAME_MS = 80


def _frames(ms: int) -> int:
    return max(1, round(ms / _FRAME_MS))

logger = get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

# Separate router for the wake-word WS: it cannot use the protected router's HTTP
# `get_current_user` dependency (a browser WebSocket can't set X-API-Key headers),
# so it self-authenticates on a short-lived JWT ticket — see `wake_ws`. Mounted
# in the public tier by app/api/router.py.
ws_router = APIRouter(prefix="/voice", tags=["voice"])


class VoiceRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8000)
    thread_id: str | None = Field(default=None)
    # When a cross-thread inbound-email approval card is presented in the HUD,
    # the client sends its id so this utterance is judged against THAT card
    # (resolved by sending/discarding) rather than starting a fresh turn. None
    # for a normal voice turn. The conversation thread's own interrupts are
    # detected server-side and take priority.


@router.post("/stream", response_model=None)
async def voice_stream(
    payload: VoiceRequest,
    user: UserContext = Depends(get_current_user),
) -> StreamingResponse:
    thread_id = payload.thread_id or canonical_thread_id(user.user_id)

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


class AnnounceApprovalRequest(BaseModel):
    approval_id: str
    # False → "Here's another I've drafted…" for a 2nd+ card in a sequence.
    first: bool = True


class AnnounceApprovalResponse(BaseModel):
    text: str  # the caption / spoken words
    audio: str  # base64 PCM/WAV (empty if TTS yielded nothing)
    mime: str


async def _load_pending_approval(approval_id: str):
    """The PendingApproval row for `approval_id` IFF it's still pending — else None
    (gone / already resolved). Origin-agnostic: announces any surfaced card."""
    from app.db.engine import async_session
    from app.db.models import PendingApproval

    try:
        aid = uuid.UUID(approval_id)
    except ValueError:
        return None
    async with async_session() as session:
        row = (
            await session.execute(select(PendingApproval).where(PendingApproval.id == aid))
        ).scalar_one_or_none()
    if row is None or row.status != "pending":
        return None
    return row


def _announce_text(row, *, first: bool) -> str:
    """Concise spoken intro for a freshly-surfaced approval card so the master can
    decide by ear. Reads sensibly per origin: an email reply names sender +
    subject; a tool action speaks its description — then asks to go ahead."""
    from app.email.approval_handler import is_email_approval

    h = settings.MASTER_HONORIFIC
    if is_email_approval(row.thread_id):
        payload = row.payload or {}
        name, addr = parseaddr(payload.get("sender", ""))
        who = name or addr or "someone"
        subject = payload.get("subject") or "your message"
        if payload.get("needs_drafting"):
            # Complex — NOT drafted yet; read the heads-up + the "say go" affordance.
            lead = f"{h}, you've got a bigger one" if first else f"There's another bigger one, {h}"
            return f"{lead} from {who}, about '{subject}' — say the word and I'll draft it."
        lead = (
            f"{h}, I've drafted a reply" if first
            else f"Here's another I've drafted, {h} — a reply"
        )
        return f"{lead} to {who}, about '{subject}'. Shall I send it?"
    # Tool action — the row's description is the human action summary.
    action = (row.description or "an action").rstrip(".")
    lead = (
        f"{h}, I've queued an action for your approval" if first
        else f"Here's another awaiting you, {h}"
    )
    return f"{lead} — {action}. Shall I go ahead?"


@router.post("/announce-approval", response_model=AnnounceApprovalResponse)
async def announce_approval(
    payload: AnnounceApprovalRequest,
    user: UserContext = Depends(get_current_user),
) -> AnnounceApprovalResponse:
    """Speak a freshly-surfaced approval card aloud (voice mode) — an inbound email
    reply OR a chat-queued tool action. The HUD calls this when it presents a card
    so Jarvis reads it; the master then resolves by voice (→ /voice/stream with
    the conversation's approval message) or by button. Returns the spoken text + its audio, in
    the same shape the stream's `audio` events carry (one playback path)."""
    row = await _load_pending_approval(payload.approval_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="approval not found or already resolved",
        )
    text = _announce_text(row, first=payload.first)
    content = await synth_line(text)
    if content is None:  # TTS yielded nothing — still return the caption text.
        return AnnounceApprovalResponse(text=text, audio="", mime=audio_mime())
    return AnnounceApprovalResponse(
        text=content["text"], audio=content["audio"], mime=content["mime"]
    )


@ws_router.websocket("/wake")
async def wake_ws(websocket: WebSocket, ticket: str = Query(default="")) -> None:
    """Always-on voice-in stream (Phase 4.2 wake-word + 4.3a barge-in + 4.3b local
    STT). The browser sends 16 kHz mono int16 PCM over a SINGLE stream and switches
    what the backend does with a text control message ``{"mode":"wake"|"vad"|"capture"}``:

      * **wake** (default) — score openWakeWord "hey jarvis"; push
        ``{"event":"wake","score":…}`` when it crosses WAKE_THRESHOLD.
      * **vad** ("listen-for-speech", while Jarvis is RESPONDING) — score the
        bundled Silero VAD and push per-frame ``{"event":"speech","score":…}`` so
        the client detects the master's speech onset and barges in. (It also feeds
        the capture endpointer so a barge-in command's onset is pre-buffered.)
      * **capture** (4.3b — the command STT, replaces browser Web Speech) — Silero
        VAD endpoints the utterance (`CaptureEndpointer`), faster-whisper
        transcribes it, and we push ``{"event":"transcript","text":…}`` on
        end-of-speech. The VAD owns the listening window (no Web Speech idle-drop),
        and a vad→capture switch preserves the endpointer's buffer so the onset
        survives. Bounded by WHISPER_TIMEOUT_S — a slow model degrades to "".

    One stream, three modes — no second ``getUserMedia``, browser-agnostic,
    cloud-free. Auth: the browser can't set X-API-Key on a WS handshake, so it
    authenticates with a **short-lived JWT ticket** (HS256, signed by the BFF with
    the shared AUTH_SECRET, ~60s expiry) passed as ``?ticket=``; validated with the
    same ``_verify_jwt`` the HTTP auth uses.
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
    endpointer = CaptureEndpointer(
        preroll_frames=_frames(settings.CAPTURE_PREROLL_MS),
        hangover_frames=_frames(settings.CAPTURE_SILENCE_HANGOVER_MS),
        max_frames=_frames(settings.CAPTURE_MAX_MS),
    )
    cap_threshold = settings.CAPTURE_VAD_THRESHOLD
    no_speech_frames = _frames(settings.CAPTURE_NO_SPEECH_MS)
    no_onset_frames = 0  # frames since capture began with no speech onset yet

    async def _emit_transcript(pcm: np.ndarray) -> None:
        """Transcribe a finalized utterance off the loop, BOUNDED — a slow/stuck
        whisper degrades to "" (the client re-prompts) rather than hanging."""
        try:
            transcript = await asyncio.wait_for(
                asyncio.to_thread(transcribe_pcm, pcm),
                timeout=settings.WHISPER_TIMEOUT_S,
            )
        except Exception as exc:  # noqa: BLE001 — TimeoutError or a model failure
            logger.warning("whisper_transcribe_degraded", error=f"{type(exc).__name__}: {exc}")
            transcript = ""
        await websocket.send_json({"event": "transcript", "text": transcript})

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
                if new_mode not in ("wake", "vad", "capture") or new_mode == mode:
                    continue
                if new_mode in ("vad", "capture") and vad is None:
                    vad = await asyncio.to_thread(new_vad)
                if new_mode == "vad":
                    vad.reset_states()
                    endpointer.reset()
                elif new_mode == "capture":
                    # Preserve VAD + endpointer buffer on a vad→capture switch so a
                    # barge-in command's onset (spoken during RESPONDING, before the
                    # switch) survives; reset on a fresh wake→capture.
                    if mode != "vad":
                        vad.reset_states()
                        endpointer.reset()
                    no_onset_frames = 0  # restart the no-speech timer for this capture
                elif new_mode == "wake":
                    model.reset()  # drop stale wake state on the way back in
                    endpointer.reset()
                mode = new_mode
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
                elif mode == "vad" and vad is not None:
                    score = float(await asyncio.to_thread(vad.predict, audio, VAD_FRAME_SIZE))
                    # Buffer the onset so a barge-in → capture keeps the first word.
                    endpointer.push(audio, score > cap_threshold)
                    await websocket.send_json({"event": "speech", "score": score})
                elif mode == "capture" and vad is not None:
                    score = float(await asyncio.to_thread(vad.predict, audio, VAD_FRAME_SIZE))
                    utterance = endpointer.push(audio, score > cap_threshold)
                    if utterance is not None:
                        await _emit_transcript(utterance)
                        no_onset_frames = 0
                    elif endpointer.capturing:
                        no_onset_frames = 0  # speech started → no-speech timer off;
                        #                       hangover + CAPTURE_MAX own finalization
                    else:
                        # No onset yet — idle the client if it stays silent too long.
                        no_onset_frames += 1
                        if no_onset_frames >= no_speech_frames:
                            await websocket.send_json({"event": "transcript", "text": ""})
                            no_onset_frames = 0
                            endpointer.reset()
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
