"use client";

import { useState } from "react";

import dynamic from "next/dynamic";
import { signOut, useSession } from "next-auth/react";

import { BootSequence } from "@/components/BootSequence";
import { ChatPanel } from "@/components/ChatPanel";
import { CircuitBackdrop } from "@/components/CircuitBackdrop";
import { ContextMeterBar } from "@/components/ContextMeterBar";
import { HudControls } from "@/components/HudControls";
import { PlaceholderWidget } from "@/components/PlaceholderWidget";
import { WidgetCard } from "@/components/WidgetCard";
import { clearBootPending } from "@/lib/boot";
import { DASHBOARD_LAYOUT as L, GRID_COLS, GRID_ROWS } from "@/lib/dashboardLayout";
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
  const [wakeOn, setWakeOn] = useState(false);

  // Full-duplex voice loop (4.3a): wake → capture → turn → barge-in → continuity.
  // Owns the turn, the orb state, and the wake-word transport.
  const {
    items,
    caption,
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
  // authenticate; a turn is "in flight" while Jarvis is thinking/responding.
  const { status: sessionStatus } = useSession();
  const ready = sessionStatus === "authenticated";
  const busy = orbState === "thinking" || orbState === "responding";
  const voiceActive = voiceEnabled || wakeOn;

  return (
    <main className="relative flex h-screen flex-col overflow-hidden p-3">
      <CircuitBackdrop />
      <BootSequence />

      {/* Top-left wordmark — the only chrome up top (no app-bar). */}
      <div className="pointer-events-none z-20 mb-2 shrink-0 pl-1">
        <span className="font-mono text-lg tracking-[0.4em] text-cyan glow">JARVIS</span>
        <span className="ml-2 font-mono text-[10px] uppercase tracking-[0.3em] text-ink-dim">
          HUD
        </span>
      </div>

      {/* The primitive snap-grid — every widget sized + placed in whole cells. */}
      <div
        className="grid min-h-0 flex-1 gap-2"
        style={{
          gridTemplateColumns: `repeat(${GRID_COLS}, minmax(0, 1fr))`,
          gridTemplateRows: `repeat(${GRID_ROWS}, minmax(0, 1fr))`,
        }}
      >
        {/* Orb — bare cell, floats dead-centre, large */}
        <WidgetCard spec={L.orb} bare cellClassName="flex items-center justify-center">
          <div className="relative flex h-full w-full items-center justify-center overflow-hidden">
            <div
              className="aspect-square h-full max-h-full w-auto max-w-full"
              style={{
                // Circular mask: fades the square canvas edge into a circle so a
                // big orb can spill glow without a hard corner.
                maskImage: "radial-gradient(circle, #000 70%, transparent 84%)",
                WebkitMaskImage: "radial-gradient(circle, #000 70%, transparent 84%)",
              }}
            >
              <OrbCanvas state={orbState} getAmplitude={voiceActive ? getAmplitude : undefined} />
            </div>
            {/* labels pinned to the bottom, independent of the orb's centre */}
            <div className="pointer-events-none absolute inset-x-0 bottom-1 flex flex-col items-center gap-1 px-2 text-center">
              <div className="font-mono text-xs uppercase tracking-[0.3em] text-cyan-soft glow">
                {STATE_LABEL[orbState] ?? orbState}
              </div>
              {voiceActive && caption && (
                <div className="max-w-[90%] text-sm text-ink glow">{caption}</div>
              )}
              {wakeOn && <div className="font-mono text-[11px] text-ink-dim">{statusLabel}</div>}
            </div>
          </div>
        </WidgetCard>

        {/* Chat — tall corner widget */}
        <WidgetCard spec={L.chat}>
          <ChatPanel
            items={items}
            send={send}
            decideApproval={decideApproval}
            uploadDocument={uploadDocument}
            turnError={turnError}
            retry={retry}
            ready={ready}
            busy={busy}
            wakeOn={wakeOn}
            voiceEnabled={voiceEnabled}
          />
        </WidgetCard>

        {/* Context meter — re-homed into its own full-width readout strip */}
        <WidgetCard spec={L.context} className="flex flex-col justify-center px-1">
          <ContextMeterBar ctx={context} />
        </WidgetCard>

        {/* Upcoming data widgets (4.C.2 / 4.C.3) — labeled placeholders for now */}
        <PlaceholderWidget title="Clock" glyph="◷" spec={L.clock} />
        <PlaceholderWidget title="Weather" glyph="☁" spec={L.weather} />
        <PlaceholderWidget title="Status" glyph="◉" spec={L.status} />
        <PlaceholderWidget title="System" glyph="▦" spec={L.system} />
        <PlaceholderWidget title="Health" glyph="✚" spec={L.health} />
        <PlaceholderWidget title="Uptime" glyph="⟲" spec={L.uptime} />
        <PlaceholderWidget title="Event Log" glyph="☰" spec={L.eventlog} />
      </div>

      {/* Low-prominence controls, bottom-right */}
      <HudControls
        wakeOn={wakeOn}
        onToggleWake={() => setWakeOn((on) => !on)}
        voiceEnabled={voiceEnabled}
        onToggleVoice={() => setVoiceEnabled(!voiceEnabled)}
        onSignOut={() => {
          clearBootPending();
          signOut({ callbackUrl: "/login" });
        }}
      />
    </main>
  );
}
