"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import type { AgentState } from "./types";
import { useJarvis } from "./useJarvis";
import { useWakeWord, type WakeMode } from "./useWakeWord";
import {
  BARGE_IN_IGNORE_MS,
  BARGE_IN_SUSTAIN_MS,
  BARGE_IN_THRESHOLD,
  CONTINUITY_WINDOW_MS,
  LISTEN_WINDOW_MS,
  VAD_FRAME_MS,
} from "./voiceConfig";
import { BargeInTracker, orbStateFor, voiceReducer, type VoicePhase } from "./voiceMachine";

const now = (): number =>
  typeof performance !== "undefined" ? performance.now() : Date.now();

/** Which backend mode the single mic→WS stream runs, per voice phase. */
function modeForPhase(phase: VoicePhase): WakeMode {
  if (phase === "idle") return "wake"; // cold-start: listen for "hey jarvis"
  if (phase === "responding") return "vad"; // barge-in window
  if (phase === "listening" || phase === "continuity") return "capture"; // local STT
  return "paused"; // thinking → nothing to score
}

/**
 * Full-duplex voice orchestrator (Phase 4.3a barge-in + 4.3b local STT). Wires
 * the pure state machine (`voiceMachine`) to the turn (`useJarvis`) and the
 * single mic→WS transport (`useWakeWord`).
 *
 * Command capture is now **server-side faster-whisper** (the `capture` WS mode),
 * not the browser Web Speech API — so it's browser-agnostic (works in Brave),
 * single-stream (no second getUserMedia / mic contention), cloud-free, and the
 * Silero VAD owns the listening window (no premature no-speech idle-drop). The
 * orchestrator adds the two things the machine can't express alone:
 *
 *   - **Barge-in**: per-frame VAD scores during RESPONDING feed a sustained gate
 *     past a playback grace window; on trigger we stop TTS + abort the turn and
 *     cut to a capture. The backend pre-buffers the onset so the interrupting
 *     command's first word survives the vad→capture switch.
 *   - **Continuity**: when a turn ends we open a timed capture window so the
 *     master can speak the next command WITHOUT re-saying "hey jarvis".
 *
 * A *typed* turn still drives the orb (idle phase defers to the turn state) but
 * doesn't engage the voice loop.
 */
export function useVoiceLoop({ enabled }: { enabled: boolean }) {
  const jarvis = useJarvis();
  const [phase, dispatch] = useReducer(voiceReducer, "idle");

  const phaseRef = useRef<VoicePhase>(phase);
  phaseRef.current = phase;

  // Barge-in machinery.
  const trackerRef = useRef(
    new BargeInTracker(BARGE_IN_THRESHOLD, BARGE_IN_SUSTAIN_MS, VAD_FRAME_MS),
  );
  const respondingStartRef = useRef(0);
  const bargingRef = useRef(false); // set on barge-in so the stop()-induced idle
  //                                   isn't mistaken for a natural TURN_DONE.

  // Wake → start a turn-capture (honoured only from idle by the reducer).
  const handleWake = useCallback(() => dispatch({ type: "WAKE" }), []);

  // Per-frame VAD score while RESPONDING → maybe barge-in.
  const handleSpeech = useCallback(
    (score: number) => {
      if (phaseRef.current !== "responding") return;
      if (now() - respondingStartRef.current < BARGE_IN_IGNORE_MS) return;
      if (trackerRef.current.push(score)) {
        bargingRef.current = true;
        trackerRef.current.reset();
        jarvis.stop(); // cut TTS + abort the in-flight turn
        dispatch({ type: "BARGE_IN" }); // → listening → fresh capture
      }
    },
    [jarvis.stop],
  );

  // Whisper transcript from the capture-mode WS → start the turn. Honoured only
  // in a capture phase. A non-empty transcript starts the turn; an EMPTY one is
  // the backend's "no speech / unintelligible within the window" signal → idle
  // (the backend owns endpointing now, so this is the authoritative end-of-listen,
  // not a fixed frontend wall-clock that was blind to mid-speech — Bug 3 fix).
  const handleTranscript = useCallback(
    (text: string) => {
      const p = phaseRef.current;
      if (p !== "listening" && p !== "continuity") return;
      if (text.trim()) {
        dispatch({ type: "CAPTURE_RESULT", transcript: text });
        jarvis.send(text);
      } else {
        dispatch({ type: "CAPTURE_EMPTY" });
      }
    },
    [jarvis.send],
  );

  const wake = useWakeWord({
    enabled,
    mode: modeForPhase(phase),
    onWake: handleWake,
    onSpeech: handleSpeech,
    onTranscript: handleTranscript,
  });

  // Wake-word implies spoken responses.
  useEffect(() => {
    if (enabled) jarvis.setVoiceEnabled(true);
  }, [enabled, jarvis.setVoiceEnabled]);

  // Disable → hard reset to idle (the WS mode follows via modeForPhase).
  useEffect(() => {
    if (!enabled) dispatch({ type: "RESET" });
  }, [enabled]);

  // Entering RESPONDING: arm the barge-in clock + gate.
  useEffect(() => {
    if (phase !== "responding") return;
    respondingStartRef.current = now();
    trackerRef.current.reset();
    bargingRef.current = false;
  }, [phase]);

  // Capture window: in a capture phase the WS streams PCM and the backend owns
  // endpointing (transcript OR an empty "no-speech" signal → handleTranscript).
  // This timer is only a SAFETY BACKSTOP (≥ CAPTURE_MAX_MS + margin) for a backend
  // that goes silent — it must NOT race real speech, so it's generous.
  useEffect(() => {
    if (phase !== "listening" && phase !== "continuity") return;
    const windowMs = phase === "continuity" ? CONTINUITY_WINDOW_MS : LISTEN_WINDOW_MS;
    const timer = setTimeout(() => dispatch({ type: "CAPTURE_EMPTY" }), windowMs);
    return () => clearTimeout(timer);
  }, [phase]);

  // Turn lifecycle → drive the machine off the turn's own state. Guards keep a
  // typed turn (phase idle) from hijacking the loop, and the barge-in flag keeps
  // the stop()-induced idle from firing a spurious TURN_DONE.
  const prevAgent = useRef<AgentState>(jarvis.agentState);
  useEffect(() => {
    const prev = prevAgent.current;
    prevAgent.current = jarvis.agentState;
    if (jarvis.agentState === "responding") {
      dispatch({ type: "TURN_RESPONDING" });
    } else if (jarvis.agentState === "idle" && (prev === "responding" || prev === "thinking")) {
      if (bargingRef.current) bargingRef.current = false;
      else dispatch({ type: "TURN_DONE" });
    }
  }, [jarvis.agentState]);

  const orbState: AgentState = orbStateFor(phase, jarvis.agentState);
  const statusLabel = computeStatus(phase, wake.error, wake.supported);

  return {
    // turn / UI passthrough
    items: jarvis.items,
    caption: jarvis.caption,
    needsApproval: jarvis.needsApproval,
    decideApproval: jarvis.decideApproval,
    voiceEnabled: jarvis.voiceEnabled,
    setVoiceEnabled: jarvis.setVoiceEnabled,
    getAmplitude: jarvis.getAmplitude,
    send: jarvis.send, // raw send for the typed input form
    // voice loop
    phase,
    orbState,
    statusLabel,
    wakeSupported: wake.supported,
    wakeError: wake.error,
  };
}

function computeStatus(
  phase: VoicePhase,
  wakeError: string | null,
  wakeSupported: boolean,
): string {
  if (wakeError) return `⚠ ${wakeError}`;
  if (!wakeSupported) return "⚠ voice needs a mic-capable browser";
  switch (phase) {
    case "listening":
      return "listening for your command…";
    case "continuity":
      return "go ahead, Sir — I'm listening…";
    case "thinking":
      return "working on it…";
    case "responding":
      return "speak any time to interrupt…";
    default:
      return 'say "Hey Jarvis…"';
  }
}
