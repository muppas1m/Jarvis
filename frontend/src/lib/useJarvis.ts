"use client";

import { useCallback, useRef, useState } from "react";

import type { AgentState, ChatMessage, StreamEvent } from "./types";

// Playback gain. Piper runs with normalize_audio=False (no buzz), which leaves
// the JARVIS voice quiet (~-14 dBFS); this lifts it back to a clean level
// (~1.8x → peak ≈ 11k/32767, no clipping). Tune by ear.
const PLAYBACK_GAIN = 1.8;

/**
 * Unified Jarvis turn hook — text or voice.
 *
 * Text mode → /api/chat/stream (tokens into the bubble).
 * Voice mode → /api/voice/stream: tokens build the transcript AND per-sentence
 * audio events are decoded and **scheduled gaplessly on the AudioContext clock**
 * (running cursor + short fades), through a shared AnalyserNode so the orb pulses
 * to Jarvis's voice. Captions fire when each chunk actually starts playing.
 *
 * Turns are cancellable: a new turn (or `stop()`) aborts the in-flight fetch and
 * silences playback — the barge-in foundation.
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
  const nextStartRef = useRef(0); // AudioContext time the next chunk should start
  const activeSrcRef = useRef<Set<AudioBufferSourceNode>>(new Set());
  const pendingRef = useRef(0); // scheduled-but-not-yet-ended chunks
  const streamDoneRef = useRef(false);
  const capTimersRef = useRef<Set<ReturnType<typeof setTimeout>>>(new Set());

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

  // Schedule one decoded chunk back-to-back with the previous (no gap), with a
  // few-ms fade in/out so chunk boundaries don't click.
  const scheduleChunk = useCallback((buffer: AudioBuffer, text: string) => {
    const ctx = ctxRef.current;
    const analyser = analyserRef.current;
    if (!ctx || !analyser) return;
    const now = ctx.currentTime;
    const startAt = Math.max(now + 0.02, nextStartRef.current);
    const dur = buffer.duration;
    const fade = Math.min(0.012, dur / 4);

    const gain = ctx.createGain();
    gain.connect(analyser);
    gain.gain.setValueAtTime(0, startAt);
    gain.gain.linearRampToValueAtTime(PLAYBACK_GAIN, startAt + fade);
    gain.gain.setValueAtTime(PLAYBACK_GAIN, Math.max(startAt + fade, startAt + dur - fade));
    gain.gain.linearRampToValueAtTime(0, startAt + dur);

    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(gain);

    activeSrcRef.current.add(src);
    pendingRef.current += 1;
    setAgentState("responding");

    // Caption fires when this chunk actually starts (synced to audio, not tokens).
    const timer = setTimeout(
      () => setCaption(text),
      Math.max(0, (startAt - now) * 1000),
    );
    capTimersRef.current.add(timer);

    src.onended = () => {
      activeSrcRef.current.delete(src);
      pendingRef.current -= 1;
      if (pendingRef.current <= 0 && streamDoneRef.current) {
        setAgentState("idle");
        setCaption("");
      }
    };
    src.start(startAt);
    nextStartRef.current = startAt + dur;
  }, []);

  const enqueueAudio = useCallback(
    async (b64: string, text: string) => {
      const ctx = ensureAudio();
      try {
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        const buf = await ctx.decodeAudioData(bytes.buffer);
        scheduleChunk(buf, text);
      } catch {
        /* a bad audio chunk shouldn't break the turn */
      }
    },
    [ensureAudio, scheduleChunk],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    for (const src of activeSrcRef.current) {
      try {
        src.onended = null;
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    activeSrcRef.current.clear();
    for (const t of capTimersRef.current) clearTimeout(t);
    capTimersRef.current.clear();
    pendingRef.current = 0;
    nextStartRef.current = 0;
    setAgentState("idle");
    setCaption("");
  }, []);

  const send = useCallback(
    async (text: string) => {
      const trimmed = text.trim();
      if (!trimmed) return;

      stop(); // cancel any in-flight turn (barge-in foundation)
      const voice = voiceEnabled;
      if (voice) {
        const ctx = ensureAudio();
        nextStartRef.current = ctx.currentTime;
      }
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
        // Text mode (or voice with nothing scheduled) settles now; voice settles
        // when the last scheduled chunk ends (see scheduleChunk.onended).
        if (!voice || pendingRef.current <= 0) {
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
