/**
 * Voice-loop tuning knobs (Phase 4.3a — barge-in + conversation continuity).
 *
 * The frontend equivalent of the backend `settings`: every knob named in one
 * place and overridable via a `NEXT_PUBLIC_` env var, so a deployment can tune
 * it without a code change. The self-interrupt guard lives here (not in the
 * backend) because it needs client-side playback state.
 */
function num(env: string | undefined, fallback: number): number {
  const n = env ? Number(env) : NaN;
  return Number.isFinite(n) ? n : fallback;
}

/** The worklet posts one 16 kHz int16 frame every 80 ms (1280 samples). */
export const VAD_FRAME_MS = 80;

// --- Barge-in / self-interrupt guard (active ONLY while RESPONDING) -----------
// A VAD frame counts as "speech" at or above this score. The PRIMARY guard
// against Jarvis barging in on himself is echoCancellation (AEC) — the live test
// showed no self-cutoff even at 0.6/220 ms, so AEC, not this threshold, carries
// it. These values are therefore tuned for *responsiveness*, with a wide margin
// still intact (silence ≈ 0.02, noise ≈ 0.03, real speech ≈ 0.7+). 0.5 catches
// the onset ramp a frame sooner. If AEC ever lets a self-trigger through, nudge
// back toward ~0.55 / ~140 ms.
export const BARGE_IN_THRESHOLD = num(process.env.NEXT_PUBLIC_BARGE_IN_THRESHOLD, 0.5);
// Require this much *sustained* speech before triggering — rejects a single
// leaked spike. ceil(100/80) = 2 frames @ 80 ms, so it fires ~1 frame into clear
// speech (down from ~3) → stops after ~1 word + clips fewer leading words.
export const BARGE_IN_SUSTAIN_MS = num(process.env.NEXT_PUBLIC_BARGE_IN_SUSTAIN_MS, 100);
// Ignore onsets in the first N ms of playback (the gain ramp + the loud TTS
// onset are the most likely self-trigger).
export const BARGE_IN_IGNORE_MS = num(process.env.NEXT_PUBLIC_BARGE_IN_IGNORE_MS, 300);

// --- Conversation continuity -------------------------------------------------
// After a turn finishes, listen this long for the next command WITHOUT a fresh
// "hey jarvis"; silence past it falls back to wake-word idle.
export const CONTINUITY_WINDOW_MS = num(process.env.NEXT_PUBLIC_CONTINUITY_WINDOW_MS, 7000);
// Backstop wall-clock for a single post-wake command capture (over Web Speech's
// own silence endpointing, so a stuck recogniser can't pin the mic open).
export const LISTEN_WINDOW_MS = num(process.env.NEXT_PUBLIC_LISTEN_WINDOW_MS, 9000);
