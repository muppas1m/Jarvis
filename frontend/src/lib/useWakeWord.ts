"use client";

import { useEffect, useRef, useState } from "react";

/**
 * The voice-in transport (Phase 4.2 wake-word + 4.3a barge-in). ONE
 * `getUserMedia` → an AudioWorklet resamples to 16 kHz mono int16 PCM → ~80 ms
 * frames stream over ONE WebSocket. What the backend scores is controlled by the
 * `mode` prop (a control message is sent on change):
 *
 *   - "wake"    — backend scores openWakeWord "hey jarvis"; fires `onWake`.
 *   - "vad"     — backend scores Silero VAD (while Jarvis is RESPONDING); fires
 *                 `onSpeech(score)` per frame so the loop can barge-in.
 *   - "capture" — backend endpoints + transcribes the command (faster-whisper,
 *                 4.3b); fires `onTranscript(text)` on end-of-speech. Replaces the
 *                 browser Web Speech API — same stream, browser-agnostic, cloud-free.
 *   - "paused"  — stop sending PCM (e.g. while THINKING); the WS stays open so we
 *                 never re-handshake mid-conversation.
 *
 * One stream, one socket — no second `getUserMedia`. Continuous while the tab is
 * open and only mounted on the authenticated chat page (mic gated behind the
 * session). Auth: a short-lived JWT ticket from the BFF.
 */
export type WakeMode = "wake" | "vad" | "capture" | "paused";

const WS_BASE = process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000";

export function useWakeWord({
  enabled,
  mode,
  onWake,
  onSpeech,
  onTranscript,
}: {
  enabled: boolean;
  mode: WakeMode;
  onWake: () => void;
  onSpeech: (score: number) => void;
  onTranscript: (text: string) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const onWakeRef = useRef(onWake);
  onWakeRef.current = onWake;
  const onSpeechRef = useRef(onSpeech);
  onSpeechRef.current = onSpeech;
  const onTranscriptRef = useRef(onTranscript);
  onTranscriptRef.current = onTranscript;

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const modeRef = useRef<WakeMode>(mode);
  const sendingRef = useRef(mode !== "paused");

  const supported =
    typeof window !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioWorkletNode !== "undefined";

  // Declare the active scorer mode to the backend (no-op while paused or before
  // the socket opens). Reads refs only, so it's safe from any closure.
  const syncMode = useRef(() => {
    const ws = wsRef.current;
    sendingRef.current = modeRef.current !== "paused";
    if (ws && ws.readyState === WebSocket.OPEN && modeRef.current !== "paused") {
      ws.send(JSON.stringify({ mode: modeRef.current }));
    }
  });

  // --- Transport: stream + socket, set up once per `enabled` ------------------
  useEffect(() => {
    if (!enabled) return;
    if (!supported) {
      setError("this browser can't capture mic audio");
      return;
    }
    let cancelled = false;
    setError(null);

    (async () => {
      try {
        const tRes = await fetch("/api/voice/wake-ticket");
        if (!tRes.ok) throw new Error("ticket");
        const { ticket } = (await tRes.json()) as { ticket: string };

        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;

        // 16 kHz context so the browser resamples with proper anti-aliasing (the
        // worklet then just buffers + int16-converts). Some browsers ignore the
        // rate; the worklet handles either case.
        let ctx: AudioContext;
        try {
          ctx = new AudioContext({ sampleRate: 16000 });
        } catch {
          ctx = new AudioContext();
        }
        ctxRef.current = ctx;
        await ctx.audioWorklet.addModule("/wake-worklet.js");
        const src = ctx.createMediaStreamSource(stream);
        const node = new AudioWorkletNode(ctx, "pcm-worklet");
        nodeRef.current = node;
        src.connect(node); // not connected to destination — we don't echo the mic

        const ws = new WebSocket(
          `${WS_BASE}/api/voice/wake?ticket=${encodeURIComponent(ticket)}`,
        );
        ws.binaryType = "arraybuffer";
        wsRef.current = ws;

        node.port.onmessage = (e: MessageEvent) => {
          if (sendingRef.current && ws.readyState === WebSocket.OPEN) ws.send(e.data);
        };

        ws.onopen = () => syncMode.current(); // declare the starting mode
        ws.onmessage = (ev: MessageEvent) => {
          let msg: { event?: string; score?: number; text?: string };
          try {
            msg = JSON.parse(ev.data as string);
          } catch {
            return;
          }
          if (msg.event === "wake") onWakeRef.current();
          else if (msg.event === "speech") onSpeechRef.current(msg.score ?? 0);
          else if (msg.event === "transcript") onTranscriptRef.current(msg.text ?? "");
        };
        ws.onerror = () => setError("wake-word connection failed");
      } catch {
        if (!cancelled) setError("could not start the microphone");
      }
    })();

    return () => {
      cancelled = true;
      try {
        wsRef.current?.close();
      } catch {
        /* ignore */
      }
      try {
        nodeRef.current?.disconnect();
      } catch {
        /* ignore */
      }
      streamRef.current?.getTracks().forEach((t) => t.stop());
      try {
        void ctxRef.current?.close();
      } catch {
        /* ignore */
      }
      wsRef.current = null;
      nodeRef.current = null;
      streamRef.current = null;
      ctxRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled]);

  // --- Mode changes: switch the backend scorer (or pause the PCM) -------------
  useEffect(() => {
    modeRef.current = mode;
    syncMode.current();
  }, [mode]);

  return { supported, error };
}
