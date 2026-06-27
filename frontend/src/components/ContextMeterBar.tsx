"use client";

import type { ContextMeter } from "@/lib/types";

/**
 * Slim HUD gauge (4.B.3) for the thread's context. The bar tracks COMPACTION HEADROOM —
 * the RECENT verbatim turns vs the compaction threshold, i.e. exactly what compaction
 * watches (`compact_node` triggers on the verbatim token count, not the summary). At ~100%
 * the next turn folds the oldest turns into the rolling summary and the bar drops back.
 *
 * The rolling summary is shown SEPARATELY ("↻ already-compressed memory"), NOT added into the
 * threshold budget — so the meter never reads a misleading >100% just because a summary exists
 * (the old bug: recent 5,885 + summary 345 = 6,230 shown against the 6,000 verbatim threshold).
 * Sits at the top of the chat panel; hidden until the first context snapshot arrives.
 */
export function ContextMeterBar({ ctx }: { ctx: ContextMeter | null }) {
  if (!ctx) return null;
  const { threshold_tokens, recent_tokens, summary_tokens } = ctx;
  const thr = Math.max(threshold_tokens, 1);
  const recentPct = Math.min(100, (recent_tokens / thr) * 100);
  const near = recent_tokens >= threshold_tokens * 0.85; // approaching the compaction trigger

  return (
    <div
      className="flex items-center gap-2 border-b border-cyan/10 px-3 py-1.5 text-[10px] text-ink-dim"
      title={
        `Context: ${recent_tokens.toLocaleString()} / ${threshold_tokens.toLocaleString()} verbatim tokens ` +
        `before the next compaction` +
        (summary_tokens > 0
          ? ` · ${summary_tokens.toLocaleString()} older turns already compressed into the rolling summary`
          : "")
      }
    >
      <span className="font-mono uppercase tracking-[0.2em] text-cyan-soft">context</span>
      <div className="relative h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
        {/* compaction headroom — recent verbatim vs the threshold */}
        <div className="absolute inset-y-0 left-0 bg-cyan/80" style={{ width: `${recentPct}%` }} />
      </div>
      {summary_tokens > 0 && (
        <span
          className="font-mono tabular-nums text-cyan/40"
          title="older turns already compressed into the rolling summary"
        >
          ↻{summary_tokens.toLocaleString()}
        </span>
      )}
      <span className={`font-mono tabular-nums ${near ? "text-amber" : ""}`}>
        {recent_tokens.toLocaleString()} / {threshold_tokens.toLocaleString()}
      </span>
    </div>
  );
}
