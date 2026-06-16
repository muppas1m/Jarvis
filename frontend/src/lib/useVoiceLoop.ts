"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

import type { AgentState } from "./types";
import { useJarvis } from "./useJarvis";
import { useSpeechInput } from "./useSpeechInput";
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

/** Which backend scorer the transport runs, per voice phase. */
function modeForPhase(phase: VoicePhase): WakeMode {
  if (phase === "idle") return "wake"; // cold-start: listen for "hey jarvis"
  if (phase === "responding") return "vad"; // barge-in window
  return "paused"; // listening / thinking / continuity → a capture owns the mic
}

/**
 * Full-duplex voice orchestrator (Phase 4.3a). Wires the pure state machine
 * (`voiceMachine`) to the turn (`useJarvis`), command capture (`useSpeechInput`),
 * and the mic→WS transport (`useWakeWord`), and adds the two things the machine
 * can't express on its own:
 *
 *   - **Barge-in**: per-frame VAD scores during RESPONDING feed a sustained gate
 *     (`BargeInTracker`) past a playback-start grace window; on trigger we stop
 *     TTS + abort the turn and cut to a fresh capture. A self-interrupt guard
 *     (high threshold + sustain + ignore-first-Nms) keeps Jarvis from barging in
 *     on his own voice leaking through the mic.
 *   - **Continuity**: when a turn ends we open a timed LISTENING window so the
 *     master can speak the next command WITHOUT re-saying "hey jarvis"; silence
 *     falls back to wake-word idle.
 *
 * A *typed* turn still drives the orb (idle phase defers to the turn state) but
 * doesn't engage the voice loop.
 */
export function useVoiceLoop({ enabled }: { enabled: boolean }) {
  const jarvis = useJarvis();
  const speech = useSpeechInput();
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
  const captureToken = useRef(0); // invalidates stale capture resolutions

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

  const wake = useWakeWord({
    enabled,
    mode: modeForPhase(phase),
    onWake: handleWake,
    onSpeech: handleSpeech,
  });

  // Wake-word implies spoken responses.
  useEffect(() => {
    if (enabled) jarvis.setVoiceEnabled(true);
  }, [enabled, jarvis.setVoiceEnabled]);

  // Disable → hard reset to idle + drop any capture.
  const speechAbort = speech.abort;
  const speechCapture = speech.capture;
  useEffect(() => {
    if (!enabled) {
      dispatch({ type: "RESET" });
      speechAbort();
    }
  }, [enabled, speechAbort]);

  // Entering RESPONDING: arm the barge-in clock + gate.
  useEffect(() => {
    if (phase !== "responding") return;
    respondingStartRef.current = now();
    trackerRef.current.reset();
    bargingRef.current = false;
  }, [phase]);

  // Entering a capture phase (post-wake LISTENING or the CONTINUITY window):
  // run one Web Speech capture, bounded by a window timer. A monotonic token
  // ignores the resolution of a capture that was superseded (React StrictMode
  // double-invoke, or a phase change mid-capture).
  useEffect(() => {
    if (phase !== "listening" && phase !== "continuity") return;
    const token = ++captureToken.current;
    const windowMs = phase === "continuity" ? CONTINUITY_WINDOW_MS : LISTEN_WINDOW_MS;
    const timer = setTimeout(() => speechAbort(), windowMs);

    const settle = (transcript: string) => {
      if (token !== captureToken.current) return; // superseded
      clearTimeout(timer);
      if (transcript.trim()) {
        dispatch({ type: "CAPTURE_RESULT", transcript });
        jarvis.send(transcript);
      } else {
        dispatch({ type: "CAPTURE_EMPTY" });
      }
    };

    speechCapture().then(settle, () => settle(""));

    return () => {
      captureToken.current++; // invalidate this run's pending resolution
      clearTimeout(timer);
      speechAbort();
    };
  }, [phase, speechCapture, speechAbort, jarvis.send]);

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
  const statusLabel = computeStatus(phase, wake.error, wake.supported, speech.supported);

  return {
    // turn / UI passthrough
    messages: jarvis.messages,
    caption: jarvis.caption,
    needsApproval: jarvis.needsApproval,
    voiceEnabled: jarvis.voiceEnabled,
    setVoiceEnabled: jarvis.setVoiceEnabled,
    getAmplitude: jarvis.getAmplitude,
    send: jarvis.send, // raw send for the typed input form
    // voice loop
    phase,
    orbState,
    statusLabel,
    wakeSupported: wake.supported,
    speechSupported: speech.supported,
    wakeError: wake.error,
  };
}

function computeStatus(
  phase: VoicePhase,
  wakeError: string | null,
  wakeSupported: boolean,
  speechSupported: boolean,
): string {
  if (wakeError) return `⚠ ${wakeError}`;
  if (!wakeSupported) return "⚠ wake-word needs a mic-capable browser";
  if (!speechSupported) return "⚠ command capture needs Chrome (Web Speech API)";
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
