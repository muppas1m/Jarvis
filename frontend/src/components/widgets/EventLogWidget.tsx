"use client";

import type { GridSpec } from "@/lib/dashboardLayout";
import type { Activity } from "@/lib/types";
import type { PolledState } from "@/lib/usePolledJSON";

import { WidgetCard } from "../WidgetCard";

function relTime(iso: string): string {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

/** 24h activity (4.C.3): a friendly summary header + a scrollable chronological
 *  feed of Jarvis's real work, newest-first. Master-facing phrasing comes from
 *  the backend; long entries truncate (full text on hover). Error → "—". */
export function EventLogWidget({
  spec,
  state,
}: {
  spec: GridSpec;
  state: PolledState<Activity>;
}) {
  const { data, error, loading } = state;
  const off = error || !data;

  return (
    <WidgetCard spec={spec} title="Activity — last 24h" hint={off ? "offline" : null}>
      {off ? (
        <div className="flex h-full items-center justify-center text-sm text-ink-dim">
          {loading ? "…" : "—"}
        </div>
      ) : (
        <div className="flex h-full min-h-0 flex-col">
          <div className="flex flex-wrap gap-x-4 gap-y-1 border-b border-cyan/10 px-3 py-1.5 text-[11px]">
            {data.summary.length === 0 ? (
              <span className="text-ink-dim">No activity in the last 24 hours.</span>
            ) : (
              data.summary.map((s) => (
                <span key={s.label} className="flex items-center gap-1.5 text-ink-dim">
                  <span>{s.glyph}</span>
                  <span className="font-mono tabular-nums text-cyan-soft">{s.count}</span>
                  {s.label}
                </span>
              ))
            )}
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 py-1.5">
            {data.feed.length === 0 ? (
              <p className="mt-4 text-center text-xs text-ink-dim">
                Nothing to report just yet, Sir.
              </p>
            ) : (
              data.feed.map((it, i) => (
                <div key={i} className="flex items-start gap-2 text-[12px]">
                  <span className="mt-px shrink-0 opacity-70">{it.glyph}</span>
                  <span className="min-w-0 flex-1 truncate text-ink" title={it.text}>
                    {it.text}
                  </span>
                  <span className="shrink-0 font-mono text-[10px] text-ink-dim">
                    {relTime(it.when)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </WidgetCard>
  );
}
