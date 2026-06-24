"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  AgentState,
  ApprovalRequest,
  ApprovalStatus,
  ContextMeter,
  StreamEvent,
  StreamItem,
  UploadItem,
} from "./types";

// In-chat document upload (A3) — mirror the backend's allow-list + 25 MB cap so
// an unsupported / oversized file fails INSTANTLY client-side, before a doomed
// round-trip. The backend re-validates (it's the authority).
const ALLOWED_UPLOAD_EXTS = new Set([".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"]);
const MAX_UPLOAD_BYTES = 25 * 1024 * 1024;

// Playback gain. Piper runs with normalize_audio=False (no buzz), which leaves
// the JARVIS voice quiet (~-14 dBFS); this lifts it back to a clean level
// (~1.8x → peak ≈ 11k/32767, no clipping). Tune by ear.
const PLAYBACK_GAIN = 1.8;

// Conversation persistence (A1/A2 hardened): the thread is SERVER-AUTHORITATIVE
// (the backend resolves the master's single canonical thread from the session),
// and the conversation is an ordered `items` timeline — message bubbles AND
// decision cards interleaved in position — so a reload re-renders resolved /
// discarded cards exactly where they happened, not just plain text.

/** A raw row of GET /api/chat/history `items` (message bubble or decision card). */
interface BackendItem {
  type: "message" | "decision";
  role?: "user" | "assistant";
  content?: string;
  approval_id?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown>;
  description?: string;
  status?: string;
}

/** The decide endpoint returns a TurnEnvelope; we only read these fields. */
interface DecideEnvelope {
  status?: string;
  response?: string;
  interrupt?: unknown;
}

/** GET /api/approvals/inbound/next → the next inbound (email-reply) card, or null. */
interface InboundApprovalCard {
  approval_id: string;
  thread_id: string;
  action_type: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  description?: string;
  status: string;
  created_at: string;
}

function normalizeStatus(s?: string): ApprovalStatus {
  if (s === "approved") return "approved";
  if (s === "rejected") return "rejected";
  if (s === "discarded" || s === "expired") return "discarded";
  return "pending";
}

/** GET /api/chat/history `items` → renderable StreamItem[]. */
function itemsFromHistory(raw: BackendItem[]): StreamItem[] {
  return raw.map((it) =>
    it.type === "decision"
      ? {
          type: "decision" as const,
          id: it.approval_id ?? crypto.randomUUID(),
          approval: {
            approval_id: it.approval_id ?? "",
            tool_name: it.tool_name ?? "action",
            tool_args: it.tool_args ?? {},
            description: it.description,
            status: normalizeStatus(it.status),
          },
        }
      : {
          type: "message" as const,
          id: crypto.randomUUID(),
          role: it.role === "user" ? ("user" as const) : ("assistant" as const),
          content: it.content ?? "",
        },
  );
}

/** Normalize an `approval_required` / chained-interrupt payload → ApprovalRequest. */
function approvalFromInterrupt(raw: unknown): ApprovalRequest | null {
  if (!raw || typeof raw !== "object") return null;
  const c = raw as Record<string, unknown>;
  if (typeof c.approval_id !== "string") return null;
  return {
    approval_id: c.approval_id,
    tool_name: typeof c.tool_name === "string" ? c.tool_name : "action",
    tool_args:
      c.tool_args && typeof c.tool_args === "object"
        ? (c.tool_args as Record<string, unknown>)
        : {},
    description: typeof c.description === "string" ? c.description : undefined,
    status: "pending",
  };
}

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
  const [items, setItems] = useState<StreamItem[]>([]);
  const [agentState, setAgentState] = useState<AgentState>("idle");
  const [caption, setCaption] = useState("");
  const [voiceEnabled, setVoiceEnabled] = useState(false);
  // The user message of the last turn that ERRORED (network/backend) — drives the
  // retry affordance so a failed turn never just leaves the user with silence.
  const [turnError, setTurnError] = useState<string | null>(null);
  // Context-meter snapshot (4.B.3) — token usage vs the compaction threshold.
  const [context, setContext] = useState<ContextMeter | null>(null);
  // approval_ids currently being decided — guards against a double-submit.
  const decidingRef = useRef<Set<string>>(new Set());

  // Mirrors of render state read inside the inbound-approval poll interval
  // (a setInterval closure would otherwise see stale values).
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const voiceEnabledRef = useRef(voiceEnabled);
  voiceEnabledRef.current = voiceEnabled;
  const agentStateRef = useRef<AgentState>(agentState);
  agentStateRef.current = agentState;
  // Poll only AFTER the initial history hydrate, else a surfaced card would make
  // the hydrate (which only fills an EMPTY stream) bail and drop the history.
  const hydratedRef = useRef(false);
  // Count of inbound cards surfaced this session — drives the lead-in wording
  // ("I've drafted…" first, then "Here's another…").
  const inboundSeqRef = useRef(0);

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

  // Play Jarvis reading a freshly-surfaced inbound card aloud, then settle to
  // idle like a turn end — so the voice loop opens a listening window for the
  // master's spoken decision (no need to re-say "hey jarvis"). Best-effort:
  // announce failure / no audio just leaves the card for button or voice.
  const announceInbound = useCallback(
    async (approvalId: string, first: boolean) => {
      try {
        const res = await fetch("/api/voice/announce-approval", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approval_id: approvalId, first }),
        });
        if (!res.ok) return;
        const data = (await res.json()) as { text?: string; audio?: string };
        if (!data.audio) return;
        const ctx = ensureAudio();
        nextStartRef.current = ctx.currentTime;
        streamDoneRef.current = true; // no token stream; settle when audio ends
        void enqueueAudio(data.audio, data.text ?? "");
      } catch {
        /* announce is best-effort */
      }
    },
    [ensureAudio, enqueueAudio],
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

      setTurnError(null); // a fresh attempt clears any prior failure
      stop(); // cancel any in-flight turn (barge-in foundation)
      const voice = voiceEnabled;
      if (voice) {
        const ctx = ensureAudio();
        nextStartRef.current = ctx.currentTime;
      }
      streamDoneRef.current = false;
      // Resolved/discarded cards PERSIST in the stream — nothing to clear here.

      const aiId = crypto.randomUUID();
      setItems((m) => [
        ...m,
        { type: "message", id: crypto.randomUUID(), role: "user", content: trimmed },
        { type: "message", id: aiId, role: "assistant", content: "" },
      ]);
      setAgentState("thinking");

      const patch = (content: string) =>
        setItems((m) =>
          m.map((x) => (x.type === "message" && x.id === aiId ? { ...x, content } : x)),
        );

      const ac = new AbortController();
      abortRef.current = ac;
      let acc = "";

      // If a decision card is pending, tag the turn (voice OR typed, B2) so the
      // backend judges this utterance against THAT card — it resolves a
      // cross-thread inbound card; an in-thread conversation interrupt is
      // detected server-side and takes priority, so this is ignored there.
      const presented = itemsRef.current.find(
        (x): x is Extract<StreamItem, { type: "decision" }> =>
          x.type === "decision" && x.approval.status === "pending",
      );
      const presentedId = presented?.approval.approval_id;

      try {
        const res = await fetch(voice ? "/api/voice/stream" : "/api/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: trimmed,
            thread_id: threadRef.current,
            ...(presentedId ? { presented_approval_id: presentedId } : {}),
          }),
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
                threadRef.current = ev.content; // server-resolved canonical thread (session cache)
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
              case "approval_required": {
                const a = approvalFromInterrupt(ev.content);
                if (a) {
                  setItems((m) => {
                    // Drop the empty assistant placeholder (no preamble text) —
                    // the decision card is the surface — then append the card.
                    const base = acc ? m : m.filter((x) => x.id !== aiId);
                    return [...base, { type: "decision", id: a.approval_id, approval: a }];
                  });
                }
                break;
              }
              case "decision_resolved": {
                // A typed natural-language resolution flipped a card's status
                // (approved / rejected / discarded) — update it in place so the
                // live stream matches what a reload would show.
                const { approval_id, status } = ev.content;
                setItems((m) =>
                  m.map((x) =>
                    x.type === "decision" && x.approval.approval_id === approval_id
                      ? { ...x, approval: { ...x.approval, status: normalizeStatus(status) } }
                      : x,
                  ),
                );
                break;
              }
              case "done":
                patch(ev.content.response || acc);
                if (ev.content.context) {
                  setContext(ev.content.context);
                  // Compaction just fired this turn → drop a subtle live divider.
                  if (ev.content.context.compacted) {
                    setItems((m) => [
                      ...m,
                      {
                        type: "divider",
                        id: crypto.randomUUID(),
                        label: "Earlier conversation compacted",
                      },
                    ]);
                  }
                }
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
          patch("⚠ Could not reach Jarvis.");
          setTurnError(trimmed); // surface a retry affordance for this message
        }
        streamDoneRef.current = true;
        if (!voice) setAgentState("idle");
      } finally {
        if (abortRef.current === ac) abortRef.current = null;
      }
    },
    [voiceEnabled, ensureAudio, enqueueAudio, stop],
  );

  // Re-send the last failed message (the retry affordance).
  const retry = useCallback(() => {
    if (turnError) void send(turnError);
  }, [turnError, send]);

  // Decide a pending decision card inline: POST the master's approve/reject, flip
  // THAT card to its resolved state, and append the resumed turn's result to the
  // stream. A chained interrupt (the resume hit ANOTHER approval) appends a fresh
  // pending card. Resolved/discarded cards stay in the stream (persisted history).
  const decideApproval = useCallback(
    async (approvalId: string, approved: boolean, reason?: string) => {
      if (decidingRef.current.has(approvalId)) return; // no double-submit
      decidingRef.current.add(approvalId);
      const setStatus = (status: ApprovalStatus) =>
        setItems((m) =>
          m.map((x) =>
            x.type === "decision" && x.approval.approval_id === approvalId
              ? { ...x, approval: { ...x.approval, status } }
              : x,
          ),
        );
      const appendAssistant = (content: string) =>
        setItems((m) => [
          ...m,
          { type: "message", id: crypto.randomUUID(), role: "assistant", content },
        ]);
      setStatus("resolving");
      try {
        const res = await fetch(`/api/approvals/${approvalId}/decide`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            approved ? { approved } : { approved, reason: reason ?? "" },
          ),
        });
        if (!res.ok) {
          // 404 → resolved/expired elsewhere (e.g. via Telegram). Mark it done.
          setStatus(approved ? "approved" : "rejected");
          appendAssistant("⚠ That approval is no longer available.");
          return;
        }
        const env = (await res.json()) as DecideEnvelope;
        setStatus(approved ? "approved" : "rejected");
        appendAssistant(
          (env.response || "").trim() || (approved ? "Done, Sir." : "Cancelled, Sir."),
        );
        const chained =
          env.status === "interrupted" ? approvalFromInterrupt(env.interrupt) : null;
        if (chained) {
          setItems((m) => [
            ...m,
            { type: "decision", id: chained.approval_id, approval: chained },
          ]);
        }
      } catch {
        setStatus(approved ? "approved" : "rejected");
        appendAssistant("⚠ Could not reach Jarvis to record that decision.");
      } finally {
        decidingRef.current.delete(approvalId);
      }
    },
    [],
  );

  // Upload a document straight into the chat (A3): validate client-side, append a
  // live status chip to the timeline, stream the multipart to the BFF, then flip
  // the chip to its terminal state (indexed / already-indexed / re-indexed /
  // error). Passes thread_id so the backend persists a "📎 Indexed" marker.
  // Independent of the turn stream + decision cards — never interferes with either.
  const uploadDocument = useCallback(async (file: File) => {
    const id = crypto.randomUUID();
    const ext = "." + (file.name.split(".").pop() ?? "").toLowerCase();
    const append = (upload: UploadItem) =>
      setItems((m) => [...m, { type: "upload", id, upload }]);
    const patch = (u: Partial<UploadItem>) =>
      setItems((m) =>
        m.map((x) =>
          x.type === "upload" && x.id === id ? { ...x, upload: { ...x.upload, ...u } } : x,
        ),
      );

    if (!ALLOWED_UPLOAD_EXTS.has(ext)) {
      append({
        name: file.name,
        status: "error",
        error: `Unsupported type ${ext || "(none)"} — allowed: pdf, docx, xlsx, txt, md, csv.`,
      });
      return;
    }
    if (file.size > MAX_UPLOAD_BYTES) {
      append({ name: file.name, status: "error", error: "File exceeds the 25 MB limit." });
      return;
    }
    append({ name: file.name, status: "uploading" });
    try {
      const fd = new FormData();
      fd.append("file", file);
      if (threadRef.current) fd.append("thread_id", threadRef.current);
      const res = await fetch("/api/documents/upload", { method: "POST", body: fd });
      if (!res.ok) {
        const e = (await res.json().catch(() => ({}))) as { detail?: string };
        patch({ status: "error", error: e.detail || `Upload failed (${res.status}).` });
        return;
      }
      const r = (await res.json()) as {
        chunks_stored?: number;
        deduplicated?: boolean;
        replaced?: boolean;
      };
      patch({
        status: "done",
        chunks: r.chunks_stored ?? 0,
        dedup: !!r.deduplicated,
        replaced: !!r.replaced,
      });
    } catch {
      patch({ status: "error", error: "Could not reach the server." });
    }
  }, []);

  // Hydrate the master's conversation once on mount. /history resolves the
  // server-authoritative canonical thread and returns the ordered items timeline
  // (message bubbles + decision cards, incl. resolved/discarded/pending in
  // position — so a reload mid-approval re-surfaces the live card too). Race
  // guard: hydrate ONLY into an empty stream — never clobber a started turn.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch("/api/chat/history");
        if (!res.ok) return;
        const data = (await res.json()) as {
          thread_id?: string;
          items?: BackendItem[];
          context?: ContextMeter;
        };
        if (cancelled) return;
        if (data.thread_id) threadRef.current = data.thread_id;
        if (data.context) setContext(data.context);
        const hydrated = itemsFromHistory(data.items ?? []);
        if (hydrated.length) setItems((prev) => (prev.length ? prev : hydrated));
      } catch {
        /* unreachable backend → start fresh */
      } finally {
        if (!cancelled) hydratedRef.current = true; // inbound poll may start now
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Surface INBOUND-email approvals (auto-drafted replies on their own gmail:
  // threads, invisible to the conversation history) as in-chat cards — one at a
  // time. Poll the backend's "next inbound" primitive; it returns at most one
  // pending card, and we only present it when the stream is idle with no pending
  // card already shown (so we never flood, and never collide with a conversation
  // approval). Resolved cards stay in the timeline; the next surfaces on the
  // following poll. With voice on, Jarvis reads the card and the master resolves
  // it by voice (presented_approval_id, below) or by the card's buttons.
  const surfaceInbound = useCallback(async () => {
    if (!hydratedRef.current) return;
    // Don't interrupt an in-flight turn, and enforce one-at-a-time.
    if (agentStateRef.current !== "idle") return;
    if (itemsRef.current.some((x) => x.type === "decision" && x.approval.status === "pending"))
      return;
    let data: { approval?: InboundApprovalCard | null };
    try {
      const res = await fetch("/api/approvals/inbound/next");
      if (!res.ok) return;
      data = (await res.json()) as { approval?: InboundApprovalCard | null };
    } catch {
      return; // backend unreachable → try again next tick
    }
    const a = data.approval;
    if (!a) return;

    const first = inboundSeqRef.current === 0;
    let surfaced = false;
    setItems((m) => {
      // Re-check under the latest state: a pending card or this exact card may
      // have appeared since the fetch resolved.
      if (m.some((x) => x.type === "decision" && x.approval.status === "pending")) return m;
      if (m.some((x) => x.type === "decision" && x.approval.approval_id === a.approval_id))
        return m;
      surfaced = true;
      const leadIn = first
        ? "I've drafted a reply for your approval, Sir."
        : "Here's another I've drafted, Sir…";
      return [
        ...m,
        { type: "message", id: crypto.randomUUID(), role: "assistant", content: leadIn },
        {
          type: "decision",
          id: a.approval_id,
          approval: {
            approval_id: a.approval_id,
            tool_name: a.tool_name,
            tool_args: a.tool_args,
            description: a.description,
            status: "pending",
          },
        },
      ];
    });
    if (!surfaced) return;
    inboundSeqRef.current += 1;
    if (voiceEnabledRef.current) void announceInbound(a.approval_id, first);
  }, [announceInbound]);

  useEffect(() => {
    const t = setInterval(() => void surfaceInbound(), 8000);
    return () => clearInterval(t);
  }, [surfaceInbound]);

  // B3 — surface the NEXT inbound card PROMPTLY when the current one resolves
  // (by button, voice, or typed reply), instead of waiting for the ~8s poll.
  // Fires only on the pending→none transition; surfacing a card flips this back
  // to true, so there's no loop.
  const hasPendingDecision = items.some(
    (it) => it.type === "decision" && it.approval.status === "pending",
  );
  useEffect(() => {
    if (!hasPendingDecision) void surfaceInbound();
  }, [hasPendingDecision, surfaceInbound]);

  return {
    items,
    agentState,
    caption,
    voiceEnabled,
    setVoiceEnabled,
    needsApproval: items.some(
      (it) => it.type === "decision" && it.approval.status === "pending",
    ),
    decideApproval,
    uploadDocument,
    getAmplitude,
    send,
    stop,
    turnError,
    retry,
    context,
  };
}
