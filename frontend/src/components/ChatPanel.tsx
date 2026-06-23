"use client";

import { useEffect, useRef, useState } from "react";

import type { ContextMeter, StreamItem } from "@/lib/types";

import { ApprovalCard } from "./ApprovalCard";
import { ContextMeterBar } from "./ContextMeterBar";
import { MarkdownMessage } from "./MarkdownMessage";
import { UploadChip } from "./UploadChip";

interface ChatPanelProps {
  items: StreamItem[];
  /** Context-meter snapshot (4.B.3) — re-homed to the top of the chat (4.C.2). */
  ctx: ContextMeter | null;
  /** Turn dispatch (typed input). */
  send: (text: string) => void;
  decideApproval: (approvalId: string, approved: boolean) => void;
  uploadDocument: (file: File) => void;
  turnError: string | null;
  retry: () => void;
  /** Session established — gate the composer so a first message never fires into a void. */
  ready: boolean;
  /** A turn is in flight (thinking/responding) — block double-submit. */
  busy: boolean;
  /** Composer placeholder hints. */
  wakeOn: boolean;
  voiceEnabled: boolean;
}

/**
 * The conversation widget (4.C.1): transcript + composer + retry, with
 * drag-drop document upload. Extracted from the old full-page chat into a
 * self-contained grid tile (the context meter is now its own re-homed widget).
 * Owns only its local input + drag state; the turn/loop comes in as props.
 */
export function ChatPanel({
  items,
  ctx,
  send,
  decideApproval,
  uploadDocument,
  turnError,
  retry,
  ready,
  busy,
  wakeOn,
  voiceEnabled,
}: ChatPanelProps) {
  const [input, setInput] = useState("");
  const [dragging, setDragging] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy || !ready) return;
    send(input);
    setInput("");
  }

  function onPickFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (f) uploadDocument(f);
    e.target.value = ""; // let the same file be re-picked
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) uploadDocument(f);
  }

  return (
    <div
      className="relative flex h-full min-h-0 flex-col"
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        e.preventDefault();
        setDragging(false);
      }}
      onDrop={onDrop}
    >
      {dragging && (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-cyan/60 bg-black/70 backdrop-blur-sm">
          <p className="font-mono text-sm uppercase tracking-widest text-cyan glow">
            Drop to upload &amp; index
          </p>
        </div>
      )}

      <ContextMeterBar ctx={ctx} />

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {items.length === 0 && (
          <p className="mt-8 text-center text-sm text-ink-dim">
            At your service, Sir. How may I help?
          </p>
        )}
        {items.map((it) =>
          it.type === "message" ? (
            <div
              key={it.id}
              className={it.role === "user" ? "flex justify-end" : "flex justify-start"}
            >
              <div
                className={`max-w-[85%] rounded-xl px-4 py-2 text-sm ${
                  it.role === "user"
                    ? "whitespace-pre-wrap border border-cyan/30 bg-cyan/10 text-ink"
                    : "border border-white/5 bg-black/30 text-ink"
                }`}
              >
                {it.content ? (
                  // User text is shown verbatim (they didn't write markdown);
                  // assistant markdown renders as HUD-themed formatting.
                  it.role === "user" ? (
                    it.content
                  ) : (
                    <MarkdownMessage content={it.content} />
                  )
                ) : (
                  <span className="inline-flex gap-1 py-1" aria-label="Jarvis is thinking">
                    {[0, 1, 2].map((i) => (
                      <span
                        key={i}
                        className="h-1.5 w-1.5 animate-pulse rounded-full bg-cyan/70"
                        style={{ animationDelay: `${i * 200}ms` }}
                      />
                    ))}
                  </span>
                )}
              </div>
            </div>
          ) : it.type === "decision" ? (
            <div key={it.id} className="flex justify-start">
              <div className="w-full max-w-[90%]">
                <ApprovalCard
                  approval={it.approval}
                  onDecide={(approved) => decideApproval(it.approval.approval_id, approved)}
                />
              </div>
            </div>
          ) : it.type === "upload" ? (
            <div key={it.id} className="flex justify-start">
              <div className="w-full max-w-[90%]">
                <UploadChip upload={it.upload} />
              </div>
            </div>
          ) : (
            <div
              key={it.id}
              className="flex items-center gap-3 py-1 text-[10px] uppercase tracking-[0.2em] text-ink-dim"
            >
              <div className="h-px flex-1 bg-cyan/15" />
              <span className="font-mono">⟳ {it.label}</span>
              <div className="h-px flex-1 bg-cyan/15" />
            </div>
          ),
        )}
      </div>

      {turnError && (
        <div className="flex items-center justify-between gap-2 border-t border-danger/20 bg-danger/5 px-3 py-2 text-xs text-danger">
          <span>⚠ That message didn&apos;t go through.</span>
          <button
            type="button"
            onClick={retry}
            className="rounded-md border border-cyan/40 px-2.5 py-1 font-mono uppercase tracking-wider text-cyan transition hover:bg-cyan/10"
          >
            ⟳ Retry
          </button>
        </div>
      )}

      <form onSubmit={submit} className="flex gap-2 border-t border-cyan/10 p-2.5">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.xlsx,.txt,.md,.csv"
          className="hidden"
          onChange={onPickFile}
        />
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          title="Attach a document (PDF, Word, Excel, text, CSV)"
          className="rounded-lg border border-cyan/30 px-3 py-2 text-base text-cyan transition hover:bg-cyan/10"
        >
          📎
        </button>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          disabled={!ready}
          placeholder={
            !ready
              ? "Connecting…"
              : wakeOn
                ? 'say "Hey Jarvis…" or type…'
                : voiceEnabled
                  ? "Message Jarvis — he'll speak…"
                  : "Message Jarvis…"
          }
          className="min-w-0 flex-1 rounded-lg border border-cyan/20 bg-black/30 px-3 py-2 text-sm text-ink outline-none transition focus:border-cyan focus:ring-1 focus:ring-cyan/40 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!ready || busy || !input.trim()}
          title={!ready ? "Connecting…" : busy ? "Jarvis is responding…" : "Send"}
          className="rounded-lg border border-cyan/50 bg-cyan/10 px-4 py-2 font-mono text-sm uppercase tracking-widest text-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-cyan/10"
        >
          {busy ? "···" : "Send"}
        </button>
      </form>
    </div>
  );
}
