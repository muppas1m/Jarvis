"use client";

import type { GridSpec } from "@/lib/dashboardLayout";

import { WidgetCard } from "./WidgetCard";

/**
 * A labeled placeholder tile (4.C.1) holding a slot for one of the upcoming
 * data widgets (Clock, Weather, Status, System, Health, Uptime, Event Log) that
 * land in 4.C.2 / 4.C.3. Shows the slot's name + a dim neon glyph so the full
 * HUD shape + aesthetic is reviewable now, before any live data is wired.
 */
export function PlaceholderWidget({
  title,
  glyph,
  spec,
}: {
  title: string;
  glyph: string;
  spec: GridSpec;
}) {
  return (
    <WidgetCard spec={spec} title={title} hint="soon">
      <div className="flex h-full flex-col items-center justify-center gap-1.5 text-center">
        <span className="text-2xl leading-none text-cyan/30 transition-colors duration-300 group-hover:text-cyan/45">
          {glyph}
        </span>
        <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-ink-dim/60">
          awaiting telemetry
        </span>
      </div>
    </WidgetCard>
  );
}
