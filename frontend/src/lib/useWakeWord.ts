"use client";

import { useEffect, useRef, useState } from "react";

/**
 * Server-side wake-word (Phase 4.2, openWakeWord "hey jarvis"). getUserMedia
 * (echo-cancelled) → an AudioWorklet resamples to 16 kHz mono int16 PCM → ~80 ms
 * frames stream over a WebSocket to the backend, which scores them and pushes a
 * {"event":"wake"} when "hey jarvis" is heard. On wake, audio streaming pauses
 * (so the command STT can take the mic) while `onWake` runs, then resumes.
 *
 * Continuous while the tab is open and only mounted on the authenticated chat
 * page (mic gated behind the session). Auth: a short-lived JWT ticket from the
 * BFF (no long-lived secret in the browser).
 */
const WS_BASE = process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000";

export function useWakeWord({
  enabled,
  onWake,
}: {
  enabled: boolean;
  onWake: () => Promise<void>;
}) {
  const [error, setError] = useState<string | null>(null);
  const onWakeRef = useRef(onWake);
  onWakeRef.current = onWake;

  const wsRef = useRef<WebSocket | null>(null);
  const ctxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const nodeRef = useRef<AudioWorkletNode | null>(null);
  const sendingRef = useRef(true); // paused while a command is being captured
  const busyRef = useRef(false);

  const supported =
    typeof window !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof AudioWorkletNode !== "undefined";

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

        const ctx = new AudioContext();
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

        ws.onmessage = async (ev: MessageEvent) => {
          let msg: { event?: string };
          try {
            msg = JSON.parse(ev.data as string);
          } catch {
            return;
          }
          if (msg.event === "wake" && !busyRef.current) {
            busyRef.current = true;
            sendingRef.current = false; // free the mic for the command STT
            try {
              await onWakeRef.current();
            } finally {
              sendingRef.current = true;
              busyRef.current = false;
            }
          }
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

  return { supported, error };
}
