import type { GroupedHealth, SubsystemStatus } from "./types";

/** Status → palette. Literal class strings (not interpolated) so Tailwind's
 *  scanner emits them. Shared by the status pill + health ring + group dots. */
export const STATUS_DOT: Record<SubsystemStatus, string> = {
  ok: "bg-ok",
  degraded: "bg-amber",
  down: "bg-danger",
  skipped: "bg-ink-dim",
};

export const STATUS_TEXT: Record<SubsystemStatus, string> = {
  ok: "text-ok",
  degraded: "text-amber",
  down: "text-danger",
  skipped: "text-ink-dim",
};

/** SVG stroke hexes (mirror the @theme tokens) for the ring. */
export const STATUS_HEX: Record<SubsystemStatus, string> = {
  ok: "#3ddc97",
  degraded: "#ffb454",
  down: "#ff5c7a",
  skipped: "#6b7da3",
};

/** Worst status across all groups — drives the ring's single colour. Any group
 *  down → "down" (red); any degraded → "degraded" (amber); else "ok" (green). */
export function worstGroupStatus(h: GroupedHealth): SubsystemStatus {
  const statuses = Object.values(h.groups).map((g) => g.status);
  if (statuses.includes("down")) return "down";
  if (statuses.some((s) => s === "degraded")) return "degraded";
  return "ok";
}
