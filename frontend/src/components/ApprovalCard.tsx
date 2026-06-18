"use client";

import type { ApprovalRequest } from "@/lib/types";

/**
 * Inline approval card (A2a). Renders the REAL structured action from
 * `tool_args` field-by-field — never an LLM re-summary — so the master can
 * review exactly what will execute before approving. Pending → Approve/Reject;
 * resolving → buttons disabled; approved/rejected → a resolved badge (no buttons).
 */
const FIELD_LABELS: Record<string, string> = {
  to: "To",
  cc: "Cc",
  bcc: "Bcc",
  subject: "Subject",
  body: "Body",
  summary: "Title",
  title: "Title",
  location: "Location",
  start_iso: "Start",
  end_iso: "End",
  attendees: "Attendees",
};

function label(key: string): string {
  return (
    FIELD_LABELS[key] ??
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

function renderValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "string") return v;
  if (Array.isArray(v)) return v.map(renderValue).join(", ");
  if (typeof v === "object") return JSON.stringify(v, null, 2);
  return String(v);
}

export function ApprovalCard({
  approval,
  onDecide,
}: {
  approval: ApprovalRequest;
  onDecide: (approved: boolean) => void;
}) {
  const { tool_name, tool_args, status } = approval;
  const resolving = status === "resolving";
  const discarded = status === "discarded";
  const resolved = status === "approved" || status === "rejected" || discarded;
  const entries = Object.entries(tool_args ?? {});

  return (
    <div
      className={`rounded-xl border p-4 ${
        discarded
          ? "border-ink-dim/20 bg-white/[0.02] opacity-60"
          : "border-amber/40 bg-amber/5"
      }`}
    >
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span
          className={`rounded border px-2 py-0.5 font-mono text-xs uppercase tracking-wider ${
            discarded
              ? "border-ink-dim/30 bg-white/5 text-ink-dim"
              : "border-amber/40 bg-amber/10 text-amber"
          }`}
        >
          {discarded ? "•" : "⚠ Approve"} · {tool_name}
        </span>
        {resolved && (
          <span
            className={`font-mono text-xs uppercase tracking-wider ${
              status === "approved"
                ? "text-ok"
                : status === "rejected"
                  ? "text-danger"
                  : "text-ink-dim"
            }`}
          >
            {status === "approved"
              ? "Approved ✓"
              : status === "rejected"
                ? "Rejected ✗"
                : "Discarded — superseded"}
          </span>
        )}
      </div>

      <dl className="mb-3 space-y-1.5">
        {entries.length === 0 ? (
          <p className="text-xs text-ink-dim">(no parameters)</p>
        ) : (
          entries.map(([k, v]) => (
            <div key={k} className="grid grid-cols-[5.5rem_1fr] gap-2 text-sm">
              <dt className="pt-0.5 font-mono text-xs uppercase tracking-wide text-ink-dim">
                {label(k)}
              </dt>
              <dd className="max-h-44 overflow-y-auto whitespace-pre-wrap break-words text-ink">
                {renderValue(v)}
              </dd>
            </div>
          ))
        )}
      </dl>

      {!resolved && (
        <div className="flex gap-2">
          <button
            disabled={resolving}
            onClick={() => onDecide(true)}
            className="rounded-lg border border-ok/50 bg-ok/10 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-ok transition hover:bg-ok/20 disabled:opacity-50"
          >
            {resolving ? "…" : "Approve"}
          </button>
          <button
            disabled={resolving}
            onClick={() => onDecide(false)}
            className="rounded-lg border border-danger/50 bg-danger/10 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-danger transition hover:bg-danger/20 disabled:opacity-50"
          >
            {resolving ? "…" : "Reject"}
          </button>
        </div>
      )}
    </div>
  );
}
