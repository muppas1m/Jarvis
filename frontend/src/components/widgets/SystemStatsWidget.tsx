"use client";

import type { GridSpec } from "@/lib/dashboardLayout";
import type { SystemStats } from "@/lib/types";
import type { PolledState } from "@/lib/usePolledJSON";

import { WidgetCard } from "../WidgetCard";

function Bar({
  label,
  value,
  pct,
}: {
  label: string;
  value: string;
  pct: number | null;
}) {
  const p = pct == null ? 0 : Math.max(0, Math.min(100, pct));
  const hot = p >= 85;
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between font-mono text-[11px]">
        <span className="uppercase tracking-[0.18em] text-ink-dim">{label}</span>
        <span className={`tabular-nums ${hot ? "text-amber" : "text-cyan-soft"}`}>{value}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
        <div
          className={`h-full rounded-full transition-all duration-500 ${hot ? "bg-amber" : "bg-cyan/80"}`}
          style={{ width: `${p}%` }}
        />
      </div>
    </div>
  );
}

/** Real backend-VM stats (4.C.2): CPU % · RAM used/total · disk used/total.
 *  Aggregate over the VM, /proc-backed. Error/no-data → dim "—". */
export function SystemStatsWidget({
  spec,
  state,
}: {
  spec: GridSpec;
  state: PolledState<SystemStats>;
}) {
  const { data, error } = state;
  const off = error || !data;
  const d = off ? null : data;

  const gb = (mb: number | null) => (mb == null ? null : mb / 1024);
  const memUsed = gb(d?.mem_used_mb ?? null);
  const memTotal = gb(d?.mem_total_mb ?? null);
  const dash = (v: string) => (off ? "—" : v);

  return (
    <WidgetCard spec={spec} title="System" hint={off ? "offline" : null}>
      <div className="flex h-full flex-col justify-center gap-2.5 px-3">
        <Bar
          label="CPU"
          value={d?.cpu_pct != null ? `${d.cpu_pct}%` : dash("—")}
          pct={off ? null : d?.cpu_pct ?? null}
        />
        <Bar
          label="RAM"
          value={
            memUsed != null && memTotal != null
              ? `${memUsed.toFixed(1)} / ${memTotal.toFixed(1)} GB`
              : dash("—")
          }
          pct={memUsed != null && memTotal ? (memUsed / memTotal) * 100 : null}
        />
        <Bar
          label="Disk"
          value={
            d?.disk_used_gb != null && d?.disk_total_gb != null
              ? `${Math.round(d.disk_used_gb)} / ${Math.round(d.disk_total_gb)} GB`
              : dash("—")
          }
          pct={
            d?.disk_used_gb != null && d?.disk_total_gb
              ? (d.disk_used_gb / d.disk_total_gb) * 100
              : null
          }
        />
      </div>
    </WidgetCard>
  );
}
