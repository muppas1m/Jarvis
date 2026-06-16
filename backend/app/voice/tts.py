"""Streaming TTS — provider-pluggable, sentence-at-a-time.

`synthesize(text)` returns audio bytes for one chunk (a sentence). The voice
orchestrator calls it per sentence so audio starts on the first sentence, not
the full turn (§D-1 latency lever). Best-effort by contract: a provider failure
returns b"" and logs — a TTS miss must never kill the agent turn.

Providers (settings.TTS_PROVIDER):
  - "piper"  local jgkawell/jarvis "JARVIS" voice (baked into the image at
             PIPER_VOICE_PATH). WAV. The default — $0, private, the real timbre,
             sub-300ms/sentence on in-container CPU. ElevenLabs is intentionally
             not wired (ruled out as a low-cost path).
  - "edge"   edge-tts, free cloud British male — the fallback. MP3.
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
        if provider == "piper":
            return await _piper(text)
        if provider == "edge":
            return await _edge(text)
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
        import time

        from piper.config import SynthesisConfig

        voice = _get_piper_voice()
        # length_scale<1 = faster pace; noise knobs tune timbre (None = model default).
        syn = SynthesisConfig(
            length_scale=settings.PIPER_LENGTH_SCALE,
            noise_scale=settings.PIPER_NOISE_SCALE,
            noise_w_scale=settings.PIPER_NOISE_W,
            normalize_audio=settings.PIPER_NORMALIZE_AUDIO,
        )
        buf = io.BytesIO()
        _t = time.monotonic()
        with wave.open(buf, "wb") as wav:
            # piper-tts 1.4.x: synthesize_wav sets channels/rate/width itself.
            voice.synthesize_wav(text, wav, syn_config=syn)
        logger.info("tts_synth", provider="piper", chars=len(text), ms=int((time.monotonic() - _t) * 1000))
        return buf.getvalue()

    # Piper is CPU-bound + synchronous — keep it off the event loop.
    return await asyncio.to_thread(_run)
