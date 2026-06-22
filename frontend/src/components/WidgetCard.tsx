"use client";

import type { ReactNode } from "react";

import { gridStyle, type GridSpec } from "@/lib/dashboardLayout";

interface WidgetCardProps {
  /** Cell-units placement in the dashboard grid. */
  spec: GridSpec;
  /** Eyebrow label, top-left of the card header. Omit for a header-less card. */
  title?: string;
  /** Small right-aligned header note (e.g. "soon", a live count). */
  hint?: ReactNode;
  /** Bare = a positioned cell with NO glass chrome — the orb floats over the
   *  backdrop ungrounded. Title/hint are ignored when bare. */
  bare?: boolean;
  /** Classes on the inner content region (e.g. padding, layout). */
  className?: string;
  /** Classes on the outer positioned cell. */
  cellClassName?: string;
  children?: ReactNode;
}

/**
 * The single shared HUD widget surface (4.C.1). Every dashboard tile is a
 * <WidgetCard>: a translucent `.widget-card` that reveals the blurred circuit
 * backdrop through it, with crisp neon content on top. Placement comes from the
 * resize-ready grid data model, so widgets only ever describe their cell.
 */
export function WidgetCard({
  spec,
  title,
  hint,
  bare,
  className,
  cellClassName,
  children,
}: WidgetCardProps) {
  if (bare) {
    return (
      <div style={gridStyle(spec)} className={`relative min-h-0 ${cellClassName ?? ""}`}>
        {children}
      </div>
    );
  }

  return (
    <div
      style={gridStyle(spec)}
      className={`widget-card group relative flex min-h-0 flex-col overflow-hidden rounded-xl ${
        cellClassName ?? ""
      }`}
    >
      {title && (
        <div className="flex items-center justify-between gap-2 px-3 pb-1 pt-2">
          <span className="font-mono text-[10px] uppercase tracking-[0.25em] text-cyan-soft/90">
            {title}
          </span>
          {hint != null && (
            <span className="font-mono text-[9px] uppercase tracking-widest text-ink-dim">
              {hint}
            </span>
          )}
        </div>
      )}
      <div className={`min-h-0 flex-1 ${className ?? ""}`}>{children}</div>
    </div>
  );
}
