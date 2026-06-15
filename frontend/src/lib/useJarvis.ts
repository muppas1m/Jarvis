"use client";

import { useCallback, useRef, useState } from "react";

import type { AgentState, ChatMessage, StreamEvent } from "./types";

/**
 * Unified Jarvis turn hook — text or voice.
 *
 * Text mode → /api/chat/stream (tokens into the bubble).
 * Voice mode → /api/voice/stream: tokens build the transcript AND per-sentence
 * audio events are decoded + played in order through a shared AnalyserNode, so
 * `getAmplitude()` lets the orb pulse to Jarvis's voice. Captions track the
 * spoken sentence (not the faster-running token stream).
 *
 * Turns are cancellable: starting a new turn (or `stop()`) aborts the in-flight
 * fetch (the backend cancels the graph turn) and silences playback — the
 * barge-in foundation architected from 4.1.
 */
export function useJarvis() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [caption, setCaption] = useState("");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  const [needsApproval, setNeedsApproval] = useState(false);

  const threadRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Web Audio — lazily created on first send (a user gesture, per autoplay rules).
  const ctxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const queueRef = useRef<Array<{ buf: AudioBuffer; text: string }>>([]);
  const playingRef = useRef(false);
  const streamDoneRef = useRef(false);
  const currentSrcRef = useRef<AudioBufferSourceNode | null>(null);

  const ensureAudio = useCallback((): AudioContext => {
    if (!ctxRef.current) {
      const Ctor =
        window.AudioContext ||
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new Ctor();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      analyser.connect(ctx.destination);
      ctxRef.current = ctx;
      analyserRef.current = analyser;
    }
    if (ctxRef.current.state === "suspended") void ctxRef.current.resume();
    return ctxRef.current;
  }, []);

  const getAmplitude = useCallback((): number => {
    const a = analyserRef.current;
    if (!a) return 0;
    const data = new Uint8Array(a.frequencyBinCount);
    a.getByteFrequencyData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) sum += data[i];
    return sum / data.length / 255; // 0..1
  }, []);

  const playNext = useCallback(() => {
    const ctx = ctxRef.current;
    const analyser = analyserRef.current;
    const item = queueRef.current.shift();
    if (!ctx || !analyser || !item) {
      playingRef.current = false;
      currentSrcRef.current = null;
      if (streamDoneRef.current) {
        setAgentState("idle");
        setCaption("");
      }
      return;
    }
    playingRef.current = true;
    setCaption(item.text);
    const src = ctx.createBufferSource();
    src.buffer = item.buf;
    src.connect(analyser);
    src.onended = () => {
      if (currentSrcRef.current === src) playNext();
    };
    currentSrcRef.current = src;
    src.start();
  }, []);

  const enqueueAudio = useCallback(
    async (b64: string, text: string) => {
      const ctx = ensureAudio();
      try {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const buf = await ctx.decodeAudioData(bytes.buffer);
        queueRef.current.push({ buf, text });
        if (!playingRef.current) playNext();
      } catch {
        /* a bad audio chunk shouldn't break the turn */
      }
    },
    [ensureAudio, playNext],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    queueRef.current = [];
    if (currentSrcRef.current) {
      try {
        currentSrcRef.current.onended = null;
        currentSrcRef.current.stop();
      } catch {
        /* already stopped */
      }
      currentSrcRef.current = null;
    }
    playingRef.current = false;
    setAgentState("idle");
    setCaption("");
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      stop(); // cancel any in-flight turn (barge-in foundation)
      const voice = voiceEnabled;
      if (voice) ensureAudio();
      streamDoneRef.current = false;
      setNeedsApproval(false);

      const userMsg: ChatMessage = { id: crypto.randomUUID(), role: "user", content: trimmed };
      const aiId = crypto.randomUUID();
      setMessages((m) => [...m, userMsg, { id: aiId, role: "assistant", content: "" }]);
      setAgentState("thinking");

      const patch = (content: string) =>
        setMessages((m) => m.map((x) => (x.id === aiId ? { ...x, content } : x)));

      const ac = new AbortController();
      abortRef.current = ac;
      let acc = "";

      try {
        const res = await fetch(voice ? "/api/voice/stream" : "/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: trimmed, thread_id: threadRef.current }),
          signal: ac.signal,
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let firstText = true;

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split("\n\n");
          buffer = frames.pop() ?? "";
          for (const frame of frames) {
            const line = frame.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            let ev: StreamEvent;
            try {
              ev = JSON.parse(line.slice(6)) as StreamEvent;
            } catch {
              continue;
            }
            switch (ev.type) {
              case "thread_id":
                threadRef.current = ev.content;
                break;
              case "token":
                if (firstText && !voice) {
                  setAgentState("responding");
                  firstText = false;
                }
                acc += ev.content;
                patch(acc);
                break;
              case "audio":
                setAgentState("responding");
                void enqueueAudio(ev.content.audio, ev.content.text);
                break;
              case "tool":
                break;
              case "approval_required":
                setNeedsApproval(true);
                patch("⚠ Approval required — open the Approvals panel to decide.");
                break;
              case "done":
                patch(ev.content.response || acc);
                break;
              case "error":
                patch(`⚠ ${ev.content}`);
                break;
            }
          }
        }
        streamDoneRef.current = true;
        // Text mode (or voice with nothing queued) settles immediately;
        // voice mode settles when the audio queue drains (see playNext).
        if (!voice || !playingRef.current) {
          setAgentState("idle");
          setCaption("");
        }
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          patch("⚠ Could not reach Jarvis. Please try again.");
        }
        streamDoneRef.current = true;
        if (!voice) setAgentState("idle");
      } finally {
        if (abortRef.current === ac) abortRef.current = null;
      }
    },
    [voiceEnabled, ensureAudio, enqueueAudio, stop],
  );

  return {
    messages,
    agentState,
    caption,
    voiceEnabled,
    setVoiceEnabled,
    needsApproval,
    getAmplitude,
    send,
    stop,
  };
}
