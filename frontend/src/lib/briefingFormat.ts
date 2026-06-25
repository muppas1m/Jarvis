import type { Brief } from "./types";

/** Urgency → a semantic chip level, or null to show NO chip ("none"/unknown).
 *  The component maps the level to concrete classes (kept out of here so the
 *  mapping stays testable without asserting Tailwind strings). */
export function urgencyLevel(urgency: string): "danger" | "warn" | "info" | null {
  switch (urgency) {
    case "immediate":
      return "danger";
    case "today":
      return "warn";
    case "this_week":
      return "info";
    default:
      return null; // "none" / "" / unknown → quiet, no chip
  }
}

/** The brief's header subtitle — covers the error, empty, and count cases. */
export function briefSummary(brief: Brief): string {
  if (brief.error) return "couldn't build your digest";
  if (brief.empty || brief.total === 0) return "nothing new";
  return `${brief.total} new`;
}

/** Compact relative time for the brief's timestamp ("3h ago"). */
export function relTime(iso: string): string {
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
