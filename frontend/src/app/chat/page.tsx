"use client";

import { useState } from "react";

import dynamic from "next/dynamic";
import { signOut, useSession } from "next-auth/react";

import { BootSequence } from "@/components/BootSequence";
import { ChatPanel } from "@/components/ChatPanel";
import { CircuitBackdrop } from "@/components/CircuitBackdrop";
import { HudControls } from "@/components/HudControls";
import { WidgetCard } from "@/components/WidgetCard";
import { ClockWidget } from "@/components/widgets/ClockWidget";
import { EventLogWidget } from "@/components/widgets/EventLogWidget";
import { HealthRingWidget } from "@/components/widgets/HealthRingWidget";
import { StatusPillWidget } from "@/components/widgets/StatusPillWidget";
import { SystemStatsWidget } from "@/components/widgets/SystemStatsWidget";
import { UptimeWidget } from "@/components/widgets/UptimeWidget";
import { WeatherWidget } from "@/components/widgets/WeatherWidget";
import { clearBootPending } from "@/lib/boot";
import { DASHBOARD_LAYOUT as L, GRID_COLS, GRID_ROWS } from "@/lib/dashboardLayout";
import type { Activity, BriefingLatest, GroupedHealth, SystemStats, Weather } from "@/lib/types";
import { usePolledJSON } from "@/lib/usePolledJSON";
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
    skipApproval,
    queueCount,
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

  // Two shared polls (4.C.2) feed the data widgets via the one usePolledJSON
  // hook — lifted here so System+Uptime share a /api/system poll and
  // Status+Health share a /api/system/health poll (no double-fetch, no CPU-delta
  // contention). System stats tick faster than the heavier subsystem probes.
  const sys = usePolledJSON<SystemStats>("/api/system", 4000);
  const health = usePolledJSON<GroupedHealth>("/api/system/health", 7000);
  // Weather changes slowly (20 min); the activity feed is near-live (20 s).
  const weather = usePolledJSON<Weather>("/api/weather", 1_200_000);
  const activity = usePolledJSON<Activity>("/api/activity", 20_000);
  // The proactive morning brief is Celery-driven (~once/day) → poll slowly. It
  // surfaces as a card at the top of the conversation (persist-then-poll, survives
  // reload). null when none is within the freshness window.
  const briefing = usePolledJSON<BriefingLatest>("/api/briefing/latest", 60_000);

  return (
    <main className="relative isolate flex h-screen flex-col overflow-hidden p-3">
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

        {/* Chat — tall corner widget (context meter re-homed to its top) */}
        <WidgetCard spec={L.chat}>
          <ChatPanel
            items={items}
            brief={briefing.data?.brief ?? null}
            ctx={context}
            send={send}
            decideApproval={decideApproval}
            skipApproval={skipApproval}
            queueCount={queueCount}
            uploadDocument={uploadDocument}
            turnError={turnError}
            retry={retry}
            ready={ready}
            busy={busy}
            wakeOn={wakeOn}
            voiceEnabled={voiceEnabled}
          />
        </WidgetCard>

        {/* Live data widgets (4.C.2) — real data via the shared polls */}
        <ClockWidget spec={L.clock} />
        <StatusPillWidget spec={L.status} state={health} />
        <SystemStatsWidget spec={L.system} state={sys} />
        <HealthRingWidget spec={L.health} state={health} />
        <UptimeWidget spec={L.uptime} state={sys} />

        {/* Weather (Open-Meteo) + 24h activity feed (4.C.3) */}
        <WeatherWidget spec={L.weather} state={weather} />
        <EventLogWidget spec={L.eventlog} state={activity} />
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
