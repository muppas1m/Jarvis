"use client";

import type { GridSpec } from "@/lib/dashboardLayout";
import type { SystemStats } from "@/lib/types";
import type { PolledState } from "@/lib/usePolledJSON";

import { WidgetCard } from "../WidgetCard";

function fmtUptime(s: number): string {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (d) return `${d}d ${h}h ${m}m`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${String(sec).padStart(2, "0")}s`;
  return `${sec}s`;
}

function Stat({ label, value, hot }: { label: string; value: string; hot?: boolean }) {
  return (
    <div className="flex flex-col">
      <span className="font-mono text-[9px] uppercase tracking-[0.18em] text-ink-dim">{label}</span>
      <span className={`font-mono text-sm tabular-nums ${hot ? "text-amber" : "text-cyan-soft"}`}>
        {value}
      </span>
    </div>
  );
}

/** Backend uptime (since restart) · this-session turns · today's turns · load
 *  (4.C.2). Turn counts are real (incremented per agent turn); load is
 *  /proc/loadavg, coloured amber when 1-min load exceeds the core count. */
export function UptimeWidget({
  spec,
  state,
}: {
  spec: GridSpec;
  state: PolledState<SystemStats>;
}) {
  const { data, error } = state;
  const d = error ? null : data;
  const loadHot = d?.load_1m != null && d.cpu_count ? d.load_1m / d.cpu_count > 0.9 : false;

  return (
    <WidgetCard spec={spec} title="Uptime" hint={d ? null : "offline"}>
      <div className="flex h-full flex-col justify-center gap-2 px-3">
        <div>
          <span className="font-mono text-[9px] uppercase tracking-[0.2em] text-ink-dim">
            backend uptime
          </span>
          <div className="font-mono text-xl tabular-nums text-cyan glow">
            {d ? fmtUptime(d.uptime_s) : "—"}
          </div>
        </div>
        <div className="flex items-end justify-between gap-2">
          <Stat label="Session" value={d ? String(d.session_turns) : "—"} />
          <Stat label="Today" value={d ? String(d.today_turns) : "—"} />
          <Stat
            label="Load"
            value={d?.load_1m != null ? d.load_1m.toFixed(2) : "—"}
            hot={loadHot}
          />
        </div>
      </div>
    </WidgetCard>
  );
}
