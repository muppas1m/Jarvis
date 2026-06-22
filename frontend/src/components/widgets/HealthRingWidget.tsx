"use client";

import { useState } from "react";

import { STATUS_DOT, STATUS_HEX, worstGroupStatus } from "@/lib/health";
import type { GridSpec } from "@/lib/dashboardLayout";
import type { GroupedHealth } from "@/lib/types";
import type { PolledState } from "@/lib/usePolledJSON";

import { WidgetCard } from "../WidgetCard";

const R = 42;
const CIRC = 2 * Math.PI * R;

/** One overall health ring (4.C.2) aggregating the real subsystems into the five
 *  master-facing groups (Core · Brain · Memory · Voice · Background jobs). The
 *  ring's single colour is the WORST group; hover or click reveals the groups.
 *  Fetch error → offline (grey ring, "subsystems offline"). */
export function HealthRingWidget({
  spec,
  state,
}: {
  spec: GridSpec;
  state: PolledState<GroupedHealth>;
}) {
  const { data, error, loading } = state;
  const [pinned, setPinned] = useState(false);

  const off = error || !data;
  const ringStatus = data && !error ? worstGroupStatus(data) : "skipped";
  const hex = STATUS_HEX[ringStatus];
  const groups = data ? Object.entries(data.groups) : [];
  const healthy = groups.filter(([, g]) => g.status === "ok").length;
  const total = groups.length || 5;
  const dash = off ? 0 : (healthy / total) * CIRC;

  const center = off
    ? loading
      ? "…"
      : "OFF"
    : ringStatus === "ok"
      ? "OK"
      : ringStatus === "degraded"
        ? "WARN"
        : "CRIT";

  return (
    <WidgetCard spec={spec} title="Health" hint={off ? "offline" : `${healthy}/${total}`}>
      <button
        type="button"
        onClick={() => setPinned((p) => !p)}
        className="group/ring relative flex h-full w-full items-center justify-center"
        title="Click to pin the subsystem breakdown"
      >
        <div className="relative flex items-center justify-center">
          <svg viewBox="0 0 100 100" className="h-[4.5rem] w-[4.5rem] -rotate-90">
            <circle cx="50" cy="50" r={R} fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="7" />
            {!off && (
              <circle
                cx="50"
                cy="50"
                r={R}
                fill="none"
                stroke={hex}
                strokeWidth="7"
                strokeLinecap="round"
                strokeDasharray={`${dash} ${CIRC}`}
                style={{ transition: "stroke-dasharray .6s ease, stroke .3s ease" }}
              />
            )}
          </svg>
          <span
            className="absolute font-mono text-sm font-semibold tabular-nums"
            style={{ color: hex }}
          >
            {center}
          </span>
        </div>

        {/* group breakdown — hover-preview, click-pin */}
        <div
          className={`absolute inset-0 flex flex-col justify-center gap-1 rounded-xl bg-space/85 px-3 backdrop-blur-sm transition-opacity duration-200 ${
            pinned
              ? "opacity-100"
              : "pointer-events-none opacity-0 group-hover/ring:opacity-100"
          }`}
        >
          {off ? (
            <span className="text-center font-mono text-[11px] uppercase tracking-widest text-ink-dim">
              subsystems offline
            </span>
          ) : (
            groups.map(([name, g]) => (
              <div key={name} className="flex items-center justify-between gap-2 text-[11px]">
                <span className="flex items-center gap-1.5 text-ink">
                  <span className={`h-1.5 w-1.5 rounded-full ${STATUS_DOT[g.status]}`} />
                  {name}
                </span>
                <span className="font-mono uppercase tracking-wider text-ink-dim">{g.status}</span>
              </div>
            ))
          )}
        </div>
      </button>
    </WidgetCard>
  );
}
