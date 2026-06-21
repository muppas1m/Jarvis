"use client";

import { useEffect, useRef, useState } from "react";

import dynamic from "next/dynamic";
import Link from "next/link";
import { signOut, useSession } from "next-auth/react";

import { ApprovalCard } from "@/components/ApprovalCard";
import { BootSequence } from "@/components/BootSequence";
import { ContextMeterBar } from "@/components/ContextMeterBar";
import { UploadChip } from "@/components/UploadChip";
import { clearBootPending } from "@/lib/boot";
import { useVoiceLoop } from "@/lib/useVoiceLoop";

// Client-only — Three.js must not run during SSR (Next 16: ssr:false is only
// allowed inside a Client Component, which this page is).
const OrbCanvas = dynamic(() => import("@/components/OrbCanvas"), {
  ssr: false,
  loading: () => <div className="h-full w-full animate-pulse rounded-full bg-cyan/5" />,
});

const STATE_LABEL: Record<string, string> = {
  idle: "STANDING BY",
  listening: "LISTENING",
  thinking: "THINKING",
  responding: "RESPONDING",
};

export default function ChatPage() {
  const [input, setInput] = useState("");
  const [wakeOn, setWakeOn] = useState(false);
  const [dragging, setDragging] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Full-duplex voice loop (4.3a): wake → capture → turn → barge-in → continuity.
  // Owns the turn, the orb state, and the wake-word transport.
  const {
    items,
    caption,
    needsApproval,
    decideApproval,
    uploadDocument,
    voiceEnabled,
    setVoiceEnabled,
    getAmplitude,
    send,
    orbState,
    statusLabel,
    turnError,
    retry,
    context,
  } = useVoiceLoop({ enabled: wakeOn });

  // Composer readiness: the session must be established before a turn can
  // authenticate, and a turn is "in flight" while Jarvis is thinking/responding.
  // Gate the composer on both so a fresh-load first message never fires into a
  // void or double-submits mid-turn.
  const { status: sessionStatus } = useSession();
  const ready = sessionStatus === "authenticated";
  const busy = orbState === "thinking" || orbState === "responding";

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [items]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || busy || !ready) return;
    send(input);
    setInput("");
  }

  function toggleWake() {
    setWakeOn((on) => !on); // the loop flips voiceEnabled on when enabled
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

  const voiceActive = voiceEnabled || wakeOn;

  return (
    <main className="flex h-screen flex-col p-3 md:p-5">
      <BootSequence />

      <header className="glass mb-3 flex items-center justify-between rounded-xl px-4 py-2">
        <div className="font-mono text-lg tracking-[0.35em] text-cyan glow">JARVIS</div>
        <nav className="flex items-center gap-3 text-xs uppercase tracking-widest text-ink-dim">
          <button
            onClick={toggleWake}
            className={`rounded-md border px-3 py-1 transition ${
              wakeOn
                ? "border-cyan/60 bg-cyan/15 text-cyan glow"
                : "border-ink-dim/30 hover:text-cyan"
            }`}
            title='Continuous wake-word — say "Hey Jarvis…"'
          >
            {wakeOn ? "🎙 Wake-word on" : "🎙 Wake-word"}
          </button>
          <button
            onClick={() => setVoiceEnabled(!voiceEnabled)}
            className={`rounded-md border px-3 py-1 transition ${
              voiceEnabled
                ? "border-cyan/60 bg-cyan/15 text-cyan glow"
                : "border-ink-dim/30 hover:text-cyan"
            }`}
            title="Speak responses aloud"
          >
            {voiceEnabled ? "🔊 Voice on" : "🔈 Voice off"}
          </button>
          <Link href="/approvals" className="relative transition hover:text-cyan">
            Approvals
            {needsApproval && (
              <span className="absolute -right-3 -top-1 h-2 w-2 rounded-full bg-amber" />
            )}
          </Link>
          <button
            onClick={() => {
              clearBootPending();
              signOut({ callbackUrl: "/login" });
            }}
            className="transition hover:text-danger"
          >
            Sign out
          </button>
        </nav>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        {/* Orb panel — orb is absolutely centred so the labels below never move it */}
        <section className="glass relative flex h-72 items-center justify-center overflow-hidden rounded-xl md:h-auto md:w-2/5">
          <div className="absolute inset-0 flex items-center justify-center">
            <div
              className="h-[min(72vmin,520px)] w-[min(72vmin,520px)]"
              style={{
                // Circular mask: fades the glow out in a circle so the square
                // canvas edge never shows (and a bigger orb can spill glow).
                maskImage: "radial-gradient(circle, #000 72%, transparent 84%)",
                WebkitMaskImage: "radial-gradient(circle, #000 72%, transparent 84%)",
              }}
            >
              <OrbCanvas state={orbState} getAmplitude={voiceActive ? getAmplitude : undefined} />
            </div>
          </div>
          {/* labels pinned to the bottom, independent of the orb's centre */}
          <div className="pointer-events-none absolute inset-x-0 bottom-3 flex flex-col items-center gap-1 px-2 text-center">
            <div className="font-mono text-xs uppercase tracking-[0.3em] text-cyan-soft">
              {STATE_LABEL[orbState] ?? orbState}
            </div>
            {voiceActive && caption && (
              <div className="max-w-[90%] text-sm text-ink glow">{caption}</div>
            )}
            {wakeOn && (
              <div className="font-mono text-[11px] text-ink-dim">{statusLabel}</div>
            )}
          </div>
        </section>

        {/* Transcript panel */}
        <section
          className="glass relative flex min-h-0 flex-1 flex-col rounded-xl"
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
          <ContextMeterBar ctx={context} />
          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
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
                    className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-4 py-2 text-sm ${
                      it.role === "user"
                        ? "border border-cyan/30 bg-cyan/10 text-ink"
                        : "border border-white/5 bg-black/30 text-ink"
                    }`}
                  >
                    {it.content || (
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
                      onDecide={(approved) =>
                        decideApproval(it.approval.approval_id, approved)
                      }
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

          <form onSubmit={submit} className="flex gap-2 border-t border-cyan/10 p-3">
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
              className="rounded-lg border border-cyan/30 px-3 py-2.5 text-base text-cyan transition hover:bg-cyan/10"
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
              className="flex-1 rounded-lg border border-cyan/20 bg-black/30 px-4 py-2.5 text-sm text-ink outline-none transition focus:border-cyan focus:ring-1 focus:ring-cyan/40 disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={!ready || busy || !input.trim()}
              title={!ready ? "Connecting…" : busy ? "Jarvis is responding…" : "Send"}
              className="rounded-lg border border-cyan/50 bg-cyan/10 px-5 py-2.5 font-mono text-sm uppercase tracking-widest text-cyan transition hover:bg-cyan/20 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-cyan/10"
            >
              {busy ? "···" : "Send"}
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
