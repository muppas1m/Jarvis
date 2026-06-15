"""Streaming TTS — provider-pluggable, sentence-at-a-time.

`synthesize(text)` returns audio bytes for one chunk (a sentence). The voice
orchestrator calls it per sentence so audio starts on the first sentence, not
the full turn (§D-1 latency lever). Best-effort by contract: a provider failure
returns b"" and logs — a TTS miss must never kill the agent turn.

Providers (settings.TTS_PROVIDER):
  - "edge"        edge-tts, free, no key, British male (the default). MP3.
  - "elevenlabs"  flash model, low first-audio, metered. MP3. Needs key + voice.
  - "piper"       local community "JARVIS" voice. WAV. Lazy-imported; needs the
                  piper-tts package + PIPER_VOICE_PATH set.
The browser's decodeAudioData auto-detects MP3 vs WAV, so callers only forward
the bytes + the advertised mime.
"""
from __future__ import annotations

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def audio_mime() -> str:
    """MIME for the current provider's output (informational; the browser
    sniffs the container anyway)."""
    return "audio/wav" if settings.TTS_PROVIDER.lower() == "piper" else "audio/mpeg"


async def synthesize(text: str) -> bytes:
    """Synthesize one text chunk to audio bytes. Returns b"" on empty input or
    any provider error (voice is best-effort)."""
    text = (text or "").strip()
    if not text:
        return b""
    provider = settings.TTS_PROVIDER.lower()
    try:
        if provider == "edge":
            return await _edge(text)
        if provider == "elevenlabs":
            return await _elevenlabs(text)
        if provider == "piper":
            return await _piper(text)
        logger.warning("tts_unknown_provider", provider=provider)
        return b""
    except Exception as exc:  # noqa: BLE001 — best-effort; never break the turn
        logger.error("tts_failed", provider=provider, error=str(exc))
        return b""


async def _edge(text: str) -> bytes:
    import edge_tts

    comm = edge_tts.Communicate(text, settings.EDGE_TTS_VOICE)
    buf = bytearray()
    async for chunk in comm.stream():
        if chunk["type"] == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


async def _elevenlabs(text: str) -> bytes:
    import httpx

    key = settings.ELEVENLABS_API_KEY
    voice = settings.ELEVENLABS_VOICE_ID
    if not key or not voice:
        logger.warning("elevenlabs_not_configured")
        return b""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice}"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={"xi-api-key": key, "accept": "audio/mpeg"},
            json={
                "text": text,
                "model_id": settings.ELEVENLABS_MODEL,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            },
        )
        resp.raise_for_status()
        return resp.content


_piper_voice = None


def _get_piper_voice():
    global _piper_voice
    if _piper_voice is None:
        from piper import PiperVoice  # type: ignore[import-not-found]

        _piper_voice = PiperVoice.load(settings.PIPER_VOICE_PATH)
    return _piper_voice


async def _piper(text: str) -> bytes:
    import asyncio
    import io
    import wave

    if not settings.PIPER_VOICE_PATH:
        logger.warning("piper_voice_not_configured")
        return b""

    def _run() -> bytes:
        voice = _get_piper_voice()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            voice.synthesize(text, wav)
        return buf.getvalue()

    # Piper is CPU-bound + synchronous — keep it off the event loop.
    return await asyncio.to_thread(_run)
