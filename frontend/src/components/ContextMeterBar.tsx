"use client";

import type { ContextMeter } from "@/lib/types";

/**
 * Slim segmented HUD gauge (4.B.3) for the thread's context window: how much is
 * spent on RECENT verbatim turns vs the ROLLING summary, against the compaction
 * threshold — with headroom as the remaining dark track. Sits at the top of the
 * chat panel. Hidden until the first context snapshot arrives.
 */
export function ContextMeterBar({ ctx }: { ctx: ContextMeter | null }) {
  if (!ctx) return null;
  const { used_tokens, threshold_tokens, recent_tokens, summary_tokens } = ctx;
  const thr = Math.max(threshold_tokens, 1);
  const recentPct = Math.min(100, (recent_tokens / thr) * 100);
  const summaryPct = Math.max(0, Math.min(100 - recentPct, (summary_tokens / thr) * 100));
  const near = used_tokens >= threshold_tokens * 0.85;

  return (
    <div
      className="flex items-center gap-2 border-b border-cyan/10 px-3 py-1.5 text-[10px] text-ink-dim"
      title={`Context: ${recent_tokens.toLocaleString()} recent + ${summary_tokens.toLocaleString()} summary tokens of ${threshold_tokens.toLocaleString()} (compaction threshold)`}
    >
      <span className="font-mono uppercase tracking-[0.2em] text-cyan-soft">context</span>
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
        {/* recent-verbatim tier (bright) */}
        <div className="absolute inset-y-0 left-0 bg-cyan/80" style={{ width: `${recentPct}%` }} />
        {/* rolling-summary tier (dim) */}
        <div
          className="absolute inset-y-0 bg-cyan/35"
          style={{ left: `${recentPct}%`, width: `${summaryPct}%` }}
        />
      </div>
      <span className={`font-mono tabular-nums ${near ? "text-amber" : ""}`}>
        {used_tokens.toLocaleString()} / {threshold_tokens.toLocaleString()}
      </span>
    </div>
  );
}
