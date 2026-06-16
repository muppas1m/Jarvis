// AudioWorklet: mic float32 @ context rate → 16 kHz mono int16 PCM, posted in
// 1280-sample (80 ms) frames — the cadence openWakeWord expects. Simple
// decimation (no anti-alias filter); adequate for wake-word, a low-pass is a
// refinement. Audio only flows while the chat page streams it to the wake WS.
class PCMWorklet extends AudioWorkletProcessor {
  constructor() {
    super();
    this._ratio = sampleRate / 16000; // `sampleRate` is the context rate (global)
    this._frame = 1280;
    this._buf = new Float32Array(this._frame);
    this._n = 0;
    this._acc = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || !input[0]) return true;
    const ch = input[0];
    for (let i = 0; i < ch.length; i++) {
      this._acc += 1;
      if (this._acc >= this._ratio) {
        this._acc -= this._ratio;
        this._buf[this._n++] = ch[i];
        if (this._n >= this._frame) {
          const out = new Int16Array(this._frame);
          for (let j = 0; j < this._frame; j++) {
            let s = this._buf[j];
            s = s < -1 ? -1 : s > 1 ? 1 : s;
            out[j] = s < 0 ? s * 0x8000 : s * 0x7fff;
          }
          this.port.postMessage(out.buffer, [out.buffer]);
          this._n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-worklet", PCMWorklet);
