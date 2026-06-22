"use client";

import { useEffect, useState } from "react";

import type { GridSpec } from "@/lib/dashboardLayout";

import { WidgetCard } from "../WidgetCard";

/**
 * Local wall-clock (4.C.2) — frontend-only, 12h + seconds, ticking 1s.
 * `now` is null on the server + first client render (the server can't know the
 * browser's clock) → no hydration mismatch; the effect fills it in client-side.
 */
export function ClockWidget({ spec }: { spec: GridSpec }) {
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    const tick = () => setNow(new Date());
    // First value on the next frame (a callback, not a synchronous setState in
    // the effect body) — keeps the clock hydration-safe without a 1s blank.
    const raf = requestAnimationFrame(tick);
    const t = setInterval(tick, 1000);
    return () => {
      cancelAnimationFrame(raf);
      clearInterval(t);
    };
  }, []);

  const time = now
    ? now.toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
        second: "2-digit",
        hour12: true,
      })
    : "—:—:—";
  const date = now
    ? now.toLocaleDateString([], { month: "short", day: "numeric", year: "numeric" })
    : "";

  return (
    <WidgetCard spec={spec} title="Clock">
      <div className="flex h-full flex-col items-center justify-center gap-1">
        <div className="font-mono text-2xl tabular-nums text-cyan glow">{time}</div>
        <div className="font-mono text-[11px] uppercase tracking-[0.2em] text-ink-dim">{date}</div>
      </div>
    </WidgetCard>
  );
}
