/**
 * Voice turn-taking state machine (Phase 4.3a — full-duplex + barge-in).
 *
 * A pure reducer + a pure barge-in gate, deliberately framework-free so the
 * cancel/state transitions are unit-tested headless (the duplex *feel* is the
 * live Chrome test). `useVoiceLoop` drives this and turns each phase into side
 * effects (start a capture, switch the WS to VAD mode, stop the turn).
 *
 *   idle ──WAKE──▶ listening ──CAPTURE_RESULT──▶ thinking ──TURN_RESPONDING──▶
 *   responding ──TURN_DONE──▶ continuity ──CAPTURE_RESULT──▶ thinking … (loop)
 *                    │                              │
 *           CAPTURE_EMPTY                    BARGE_IN (master speaks over Jarvis)
 *                    ▼                              ▼
 *                  idle                         listening
 *
 * "hey jarvis" stays the cold-start trigger (WAKE is honoured only from idle);
 * the continuity window lets the master speak the next command without it.
 */
import type { AgentState } from "./types";

export type VoicePhase = "idle" | "listening" | "thinking" | "responding" | "continuity";

export type VoiceEvent =
  | { type: "WAKE" } // "hey jarvis" heard
  | { type: "CAPTURE_RESULT"; transcript: string } // backend whisper transcript (a command)
  | { type: "CAPTURE_EMPTY" } // backend no-speech signal / window backstop / disabled
  | { type: "TURN_RESPONDING" } // audio started playing
  | { type: "TURN_DONE" } // turn finished, audio drained
  | { type: "BARGE_IN" } // sustained speech detected during playback
  | { type: "RESET" }; // disable / hard stop

/** Phases in which a command capture is in flight (post-wake or continuity). */
const isCapturing = (p: VoicePhase): boolean => p === "listening" || p === "continuity";

export function voiceReducer(phase: VoicePhase, ev: VoiceEvent): VoicePhase {
  switch (ev.type) {
    case "RESET":
      return "idle";
    case "WAKE":
      // Cold-start only — a mid-turn "hey jarvis" is ignored (the loop is live).
      return phase === "idle" ? "listening" : phase;
    case "CAPTURE_RESULT":
      // A captured command starts a turn; an empty/whitespace transcript drops back.
      if (isCapturing(phase)) return ev.transcript.trim() ? "thinking" : "idle";
      return phase;
    case "CAPTURE_EMPTY":
      return isCapturing(phase) ? "idle" : phase;
    case "TURN_RESPONDING":
      // Audio began → open the barge-in (VAD) window. Guard so a *typed* turn
      // (phase still idle) can't hijack the voice loop.
      return phase === "thinking" ? "responding" : phase;
    case "TURN_DONE":
      // Turn finished → continuity window for a no-wake follow-up.
      return phase === "thinking" || phase === "responding" ? "continuity" : phase;
    case "BARGE_IN":
      // Master spoke over Jarvis → cut straight to a fresh capture.
      return phase === "responding" ? "listening" : phase;
    default:
      return phase;
  }
}

/**
 * Orb visual state for a voice phase. `idle` defers to the turn's own state so a
 * *typed* turn (which doesn't run the voice loop) still animates thinking /
 * responding on the orb.
 */
export function orbStateFor(phase: VoicePhase, turnState: AgentState): AgentState {
  switch (phase) {
    case "listening":
    case "continuity":
      return "listening";
    case "thinking":
      return "thinking";
    case "responding":
      return "responding";
    default:
      return turnState;
  }
}

/**
 * Sustained-speech gate for barge-in. Feed it per-frame VAD scores; it returns
 * true on the single frame where speech has stayed at/above `threshold` for
 * `sustainMs` continuously. A sub-threshold frame resets the run (so a lone
 * leaked TTS spike never triggers). Pure + deterministic → unit-tested.
 */
export class BargeInTracker {
  private readonly threshold: number;
  private readonly framesNeeded: number;
  private count = 0;

  constructor(threshold: number, sustainMs: number, frameMs: number) {
    this.threshold = threshold;
    this.framesNeeded = Math.max(1, Math.ceil(sustainMs / frameMs));
  }

  /** True exactly once, on the frame that crosses the sustain window. */
  push(score: number): boolean {
    if (score >= this.threshold) {
      this.count += 1;
      return this.count === this.framesNeeded;
    }
    this.count = 0;
    return false;
  }

  reset(): void {
    this.count = 0;
  }
}
