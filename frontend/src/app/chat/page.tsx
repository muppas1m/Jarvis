"use client";

import { useEffect, useRef, useState } from "react";

import dynamic from "next/dynamic";
import Link from "next/link";
import { signOut } from "next-auth/react";

import { BootSequence } from "@/components/BootSequence";
import { useChatStream } from "@/lib/useChatStream";

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
  const { messages, agentState, activeTool, needsApproval, send } = useChatStream();
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    send(input);
    setInput("");
  }

  return (
    <main className="flex h-screen flex-col p-3 md:p-5">
      <BootSequence />

      {/* Top HUD bar */}
      <header className="glass mb-3 flex items-center justify-between rounded-xl px-4 py-2">
        <div className="font-mono text-lg tracking-[0.35em] text-cyan glow">JARVIS</div>
        <nav className="flex items-center gap-4 text-xs uppercase tracking-widest text-ink-dim">
          <Link href="/approvals" className="relative transition hover:text-cyan">
            Approvals
            {needsApproval && (
              <span className="absolute -right-3 -top-1 h-2 w-2 rounded-full bg-amber" />
            )}
          </Link>
          <button
            onClick={() => signOut({ callbackUrl: "/login" })}
            className="transition hover:text-danger"
          >
            Sign out
          </button>
        </nav>
      </header>

      <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row">
        {/* Orb panel */}
        <section className="glass relative flex h-56 flex-col items-center justify-center rounded-xl md:h-auto md:w-2/5">
          <div className="h-44 w-44 md:h-72 md:w-72">
            <OrbCanvas state={agentState} />
          </div>
          <div className="mt-2 font-mono text-xs uppercase tracking-[0.3em] text-cyan-soft">
            {STATE_LABEL[agentState] ?? agentState}
          </div>
          {activeTool && (
            <div className="mt-1 font-mono text-[11px] text-violet">⚙ {activeTool}</div>
          )}
        </section>

        {/* Chat panel */}
        <section className="glass flex min-h-0 flex-1 flex-col rounded-xl">
          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto p-4">
            {messages.length === 0 && (
              <p className="mt-8 text-center text-sm text-ink-dim">
                At your service, Sir. How may I help?
              </p>
            )}
            {messages.map((m) => (
              <div
                key={m.id}
                className={m.role === "user" ? "flex justify-end" : "flex justify-start"}
              >
                <div
                  className={`max-w-[85%] whitespace-pre-wrap rounded-xl px-4 py-2 text-sm ${
                    m.role === "user"
                      ? "border border-cyan/30 bg-cyan/10 text-ink"
                      : "border border-white/5 bg-black/30 text-ink"
                  }`}
                >
                  {m.content || (
                    <span className="text-ink-dim caret" />
                  )}
                </div>
              </div>
            ))}
          </div>

          <form onSubmit={submit} className="flex gap-2 border-t border-cyan/10 p-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Message Jarvis…"
              className="flex-1 rounded-lg border border-cyan/20 bg-black/30 px-4 py-2.5 text-sm text-ink outline-none focus:border-cyan focus:ring-1 focus:ring-cyan/40"
            />
            <button
              type="submit"
              className="rounded-lg border border-cyan/50 bg-cyan/10 px-5 py-2.5 font-mono text-sm uppercase tracking-widest text-cyan transition hover:bg-cyan/20"
            >
              Send
            </button>
          </form>
        </section>
      </div>
    </main>
  );
}
