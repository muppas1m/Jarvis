"""Server-side wake-word — openWakeWord "hey jarvis" (Phase 4.2).

The browser streams 16 kHz mono int16 PCM over the WS; this scores each frame
with the wheel-bundled `hey_jarvis_v0.1` model. Each WS connection gets its OWN
Model — the sliding-window prediction state is per-stream — created off the
event loop (the model load is CPU-bound). Silero-VAD-gated, so silence/noise
score ~0.

License note: the pretrained weights are CC-BY-NC-SA 4.0 (NonCommercial) — fine
for the master's personal build; a commercial product needs a self-trained
model (openWakeWord's Apache-2.0 training pipeline, ~1h synthetic TTS).
"""
import os

import openwakeword
from openwakeword.model import Model
from openwakeword.vad import VAD

# Wheel-bundled with the openwakeword install (site-packages, outside the
# /app bind-mount → baked into the image). The shared melspectrogram +
# embedding models load automatically alongside it.
_HEY_JARVIS = os.path.join(
    os.path.dirname(openwakeword.__file__), "resources", "models", "hey_jarvis_v0.1.onnx"
)


def new_model(vad_threshold: float) -> Model:
    """A fresh "hey jarvis" detector. ONNX inference is inferred from the
    .onnx extension (no tflite). vad_threshold gates on speech."""
    return Model(wakeword_model_paths=[_HEY_JARVIS], vad_threshold=vad_threshold)


def score_key(model: Model) -> str:
    """The key `predict()` returns the hey_jarvis score under (the model's
    filename stem, e.g. "hey_jarvis_v0.1")."""
    return next(iter(model.models.keys()))


# 80 ms @ 16 kHz = 1280 samples per frame (the worklet's cadence); openWakeWord's
# own VAD splits each frame into 640-sample chunks (160*4), so 1280 → exactly 2.
VAD_FRAME_SIZE = 640


def new_vad() -> VAD:
    """A standalone Silero VAD (Phase 4.3a barge-in "listen-for-speech" mode) —
    the SAME bundled Silero the wake gate uses, but scored directly so the same
    mic→WS stream can detect the master's speech onset while Jarvis is speaking.
    Per-connection like the wake Model (the recurrent h/c state is per-stream)."""
    return VAD()
