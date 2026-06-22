"use client";

import type { GridSpec } from "@/lib/dashboardLayout";
import type { GroupedHealth } from "@/lib/types";
import type { PolledState } from "@/lib/usePolledJSON";

import { WidgetCard } from "../WidgetCard";

/** 3-state online pill (4.C.2): fetch error → Offline; overall ok → Online;
 *  degraded → Degraded. Reads the same grouped-health poll as the ring. */
export function StatusPillWidget({
  spec,
  state,
}: {
  spec: GridSpec;
  state: PolledState<GroupedHealth>;
}) {
  const { data, error, loading } = state;

  // error wins over stale data — never present an offline backend as "Online".
  const view =
    error || (!data && !loading)
      ? { label: "Offline", pill: "border-danger/40 bg-danger/10 text-danger", dot: "bg-danger" }
      : !data
        ? { label: "Connecting", pill: "border-ink-dim/30 bg-white/5 text-ink-dim", dot: "bg-ink-dim" }
        : data.status === "ok"
          ? { label: "Online", pill: "border-ok/40 bg-ok/10 text-ok", dot: "bg-ok" }
          : { label: "Degraded", pill: "border-amber/40 bg-amber/10 text-amber", dot: "bg-amber" };

  const live = view.label === "Online" || view.label === "Connecting";

  return (
    <WidgetCard spec={spec} title="Status">
      <div className="flex h-full items-center justify-center">
        <div
          className={`flex items-center gap-2 rounded-full border px-3 py-1 ${view.pill}`}
        >
          <span className="relative flex h-2 w-2">
            {live && (
              <span
                className={`absolute inline-flex h-full w-full animate-ping rounded-full opacity-60 ${view.dot}`}
              />
            )}
            <span className={`relative inline-flex h-2 w-2 rounded-full ${view.dot}`} />
          </span>
          <span className="font-mono text-xs uppercase tracking-[0.2em]">{view.label}</span>
        </div>
      </div>
    </WidgetCard>
  );
}
