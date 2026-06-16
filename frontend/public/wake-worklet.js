// AudioWorklet: mic float32 → 16 kHz mono int16 PCM, posted in 1280-sample
// (80 ms) frames — the cadence openWakeWord expects.
//
// The capture AudioContext is created at { sampleRate: 16000 } so the browser
// resamples with proper anti-aliasing — then this just buffers + int16-converts
// (no manual decimation → no aliasing, which is the real wake-pickup lever).
// Fallback: if a browser ignores the 16 kHz request, decimate with a one-pole
// low-pass first to limit aliasing.
const TARGET = 16000;

class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / TARGET; // `sampleRate` = the context rate (global)
    this._resample = Math.abs(this._ratio - 1) > 0.01;
    this._frame = 1280;
    this._buf = new Float32Array(this._frame);
    this._n = 0;
    this._acc = 0;
    // One-pole low-pass (~7 kHz) for the fallback decimation path only.
    const rc = 1 / (2 * Math.PI * 7000);
    const dtIn = 1 / sampleRate;
    this._alpha = dtIn / (rc + dtIn);
    this._lp = 0;
  }

  _emit(sample) {
    let s = sample < -1 ? -1 : sample > 1 ? 1 : sample;
    this._buf[this._n++] = s;
    if (this._n >= this._frame) {
      const out = new Int16Array(this._frame);
      for (let j = 0; j < this._frame; j++) {
        const v = this._buf[j];
        out[j] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
      this.port.postMessage(out.buffer, [out.buffer]);
      this._n = 0;
    }
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    if (!this._resample) {
      // Context already at 16 kHz — buffer directly.
      for (let i = 0; i < ch.length; i++) this._emit(ch[i]);
    } else {
      // Fallback: low-pass then decimate.
      for (let i = 0; i < ch.length; i++) {
        this._lp += this._alpha * (ch[i] - this._lp);
        this._acc += 1;
        if (this._acc >= this._ratio) {
          this._acc -= this._ratio;
          this._emit(this._lp);
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PCMWorklet);
