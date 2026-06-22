"""Local command STT — faster-whisper (Phase 4.3b, replaces the browser Web Speech API).

The same mic→WS stream that carries wake-word + barge-in VAD also carries the
spoken *command* now: in "capture" mode the backend endpoints the utterance with
Silero VAD (`CaptureEndpointer`) and transcribes it with faster-whisper
(`transcribe_pcm`). Server-side STT makes voice-in browser-agnostic (Web Speech
is blocked in Brave), single-stream (no second getUserMedia / mic contention),
and cloud-free — and the VAD owns the listening window, so Web Speech's premature
no-speech idle-drop is gone, and a pre-roll buffer keeps a barge-in command's
first word from being clipped.

Reliability discipline mirrors the reranker (see project_rerank_sync_on_async_loop):
the CTranslate2 model lazy-loads once (double-checked lock), is warmed at startup
in the background, and the transcribe call is bounded by the caller
(`asyncio.wait_for`) so a slow model DEGRADES the turn instead of hanging it.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np
from faster_whisper import WhisperModel

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Below ~0.2s there's nothing useful to transcribe (16 kHz * 0.2s = 3200 samples).
_MIN_SAMPLES = 3200

_model: WhisperModel | None = None
_load_lock = threading.Lock()


def get_whisper() -> WhisperModel:
    """Lazy-load the faster-whisper model once. Warmed at startup so a real
    capture never pays this; the double-checked lock guards a cold-start race."""
    global _model
    if _model is None:
        with _load_lock:
            if _model is None:  # re-check under the lock
                logger.info(
                    "loading_whisper",
                    model=settings.WHISPER_MODEL,
                    device=settings.WHISPER_DEVICE,
                    compute=settings.WHISPER_COMPUTE_TYPE,
                )
                _model = WhisperModel(
                    settings.WHISPER_MODEL,
                    device=settings.WHISPER_DEVICE,
                    compute_type=settings.WHISPER_COMPUTE_TYPE,
                    cpu_threads=settings.WHISPER_CPU_THREADS,
                )
                logger.info("whisper_loaded", model=settings.WHISPER_MODEL)
    return _model


def is_loaded() -> bool:
    """True once the whisper model is resident (warmed at startup or first use).
    Cheap, non-loading — backs the dashboard's Voice health probe (4.C.2)."""
    return _model is not None


def transcribe_pcm(pcm_int16: np.ndarray) -> str:
    """Transcribe a finalized utterance (16 kHz mono int16 PCM) → text.

    Sync + CPU-bound (CTranslate2) → the caller runs it via ``asyncio.to_thread``
    and bounds it with ``asyncio.wait_for``. Too-short audio → "" (no model call).
    Greedy by default (beam_size=1) for the lowest CPU latency.
    """
    if pcm_int16 is None or pcm_int16.size < _MIN_SAMPLES:
        return ""
    audio = pcm_int16.astype(np.float32) / 32768.0
    segments, _info = get_whisper().transcribe(
        audio,
        beam_size=settings.WHISPER_BEAM_SIZE,
        language="en",
        vad_filter=False,  # we own endpointing (Silero VAD upstream)
    )
    return "".join(seg.text for seg in segments).strip()


class CaptureEndpointer:
    """VAD-driven utterance endpointing with onset pre-roll. Pure + deterministic
    (no I/O) so it's unit-testable headless; the WS handler feeds it per-frame.

    Feed ``push(frame, is_speech)`` one 80 ms int16 frame at a time. It returns
    the finalized int16 PCM the moment speech ends (trailing silence ≥ the
    hangover) or the hard max-window is hit, else ``None``. The rolling pre-roll
    is prepended to the utterance so the onset — notably a barge-in command's
    first word, spoken before the mode even switched to capture — survives.
    """

    def __init__(self, preroll_frames: int, hangover_frames: int, max_frames: int) -> None:
        self._preroll: deque[np.ndarray] = deque(maxlen=max(1, preroll_frames))
        self._hangover = max(1, hangover_frames)
        self._max = max(1, max_frames)
        self._buf: list[np.ndarray] = []
        self._capturing = False
        self._silence = 0

    def push(self, frame: np.ndarray, is_speech: bool) -> np.ndarray | None:
        # Always roll the pre-roll so the onset is preserved across a mode switch.
        self._preroll.append(frame)
        if is_speech:
            if not self._capturing:
                self._capturing = True
                self._buf = list(self._preroll)  # seed with the onset pre-roll
            else:
                self._buf.append(frame)
            self._silence = 0
        elif self._capturing:
            self._buf.append(frame)  # keep a little trailing silence
            self._silence += 1
            if self._silence >= self._hangover:
                return self._finalize()
        if self._capturing and len(self._buf) >= self._max:
            return self._finalize()
        return None

    @property
    def capturing(self) -> bool:
        return self._capturing

    def _finalize(self) -> np.ndarray:
        pcm = (
            np.concatenate(self._buf)
            if self._buf
            else np.empty(0, dtype=np.int16)
        )
        self._buf = []
        self._capturing = False
        self._silence = 0
        return pcm

    def reset(self) -> None:
        self._buf = []
        self._capturing = False
        self._silence = 0
        self._preroll.clear()
