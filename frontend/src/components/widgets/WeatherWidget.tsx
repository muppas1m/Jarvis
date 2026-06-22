"use client";

import type { GridSpec } from "@/lib/dashboardLayout";
import type { Weather } from "@/lib/types";
import type { PolledState } from "@/lib/usePolledJSON";

import { WidgetCard } from "../WidgetCard";

/** Current weather (4.C.3) — real Open-Meteo data for the configured location.
 *  Error → dim "—". Temp/condition/humidity/wind. */
export function WeatherWidget({
  spec,
  state,
}: {
  spec: GridSpec;
  state: PolledState<Weather>;
}) {
  const { data, error } = state;
  const d = error ? null : data;

  return (
    <WidgetCard spec={spec} title="Weather" hint={d ? d.location : "offline"}>
      {d ? (
        <div className="flex h-full items-center justify-between gap-3 px-3">
          <div className="flex items-center gap-3">
            <span className="text-3xl leading-none">{d.glyph}</span>
            <div>
              <div className="font-mono text-2xl tabular-nums text-cyan glow">
                {d.temp != null ? `${Math.round(d.temp)}${d.temp_unit}` : "—"}
              </div>
              <div className="text-[11px] text-ink-dim">{d.condition}</div>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1 font-mono text-[11px] text-ink-dim">
            <span>
              Humidity{" "}
              <span className="tabular-nums text-cyan-soft">
                {d.humidity != null ? `${d.humidity}%` : "—"}
              </span>
            </span>
            <span>
              Wind{" "}
              <span className="tabular-nums text-cyan-soft">
                {d.wind != null ? `${Math.round(d.wind)} ${d.wind_unit}` : "—"}
              </span>
            </span>
          </div>
        </div>
      ) : (
        <div className="flex h-full items-center justify-center text-sm text-ink-dim">—</div>
      )}
    </WidgetCard>
  );
}
