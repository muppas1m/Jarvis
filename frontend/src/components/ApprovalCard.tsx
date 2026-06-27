"use client";

import { cardButtonLabels, isResolvedStatus, resolvedBadge } from "@/lib/approvalQueue";
import type { ApprovalKind, ApprovalRequest } from "@/lib/types";

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
  original: "Replying to", // the original inbound email being replied to
  original_email: "Replying to",
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

/** A tool card may carry empty-string arg sentinels (the open-weights tool schema
 *  uses "" for "not provided") — hide those rows so the card shows only real
 *  fields, never a wall of "—". */
function isEmptyValue(v: unknown): boolean {
  return v === null || v === undefined || v === "" || (Array.isArray(v) && v.length === 0);
}

export function ApprovalCard({
  approval,
  onDecide,
  onSkip,
  queueCount = 0,
}: {
  approval: ApprovalRequest;
  onDecide: (approved: boolean) => void;
  onSkip?: () => void;
  queueCount?: number;
}) {
  const { tool_name, tool_args, status } = approval;
  const resolving = status === "resolving";
  const discarded = status === "discarded";
  const skipped = status === "skipped";
  const greyed = discarded || skipped; // deferred/superseded — muted, no actions
  // A decision OR a terminal outcome → resolved, NO buttons. A sent/failed action must never
  // render as actionable (the backend claim-gate already 404s a re-approve; this closes the UX).
  const resolved = isResolvedStatus(status);
  // Render off kind: an email reply reads as "Email reply", a tool as its name.
  // (kind is carried by queue cards; inferred from tool_name otherwise.)
  const kind: ApprovalKind = approval.kind ?? (tool_name === "email_reply" ? "email" : "tool");
  // A COMPLEX-email heads-up: no draft yet — render the email + "Draft it"/"Leave it",
  // so approving DRAFTS (it re-queues a normal card to approve-to-send), not sends.
  const needsDrafting = !!approval.needs_drafting;
  const actionLabel = needsDrafting ? "Email — needs drafting" : kind === "email" ? "Email reply" : tool_name;
  const { approve: approveLabel, reject: rejectLabel, badge, helper } = cardButtonLabels(needsDrafting);
  const entries = Object.entries(tool_args ?? {}).filter(([, v]) => !isEmptyValue(v));
  const showCount = !resolved && queueCount > 1; // "1 of N" only on the live card

  return (
    <div
      className={`rounded-xl border p-4 ${
        greyed
          ? "border-ink-dim/20 bg-white/[0.02] opacity-60"
          : "border-amber/40 bg-amber/5"
      }`}
    >
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <span
          className={`rounded border px-2 py-0.5 font-mono text-xs uppercase tracking-wider ${
            greyed
              ? "border-ink-dim/30 bg-white/5 text-ink-dim"
              : "border-amber/40 bg-amber/10 text-amber"
          }`}
        >
          {greyed ? "•" : badge} · {actionLabel}
        </span>
        {resolved ? (
          <span className={`font-mono text-xs uppercase tracking-wider ${resolvedBadge(status, kind).cls}`}>
            {resolvedBadge(status, kind).text}
          </span>
        ) : (
          showCount && (
            <span className="font-mono text-xs uppercase tracking-wider text-ink-dim">
              1 of {queueCount}
            </span>
          )
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
        <>
          <div className="flex gap-2">
            <button
              disabled={resolving}
              onClick={() => onDecide(true)}
              className="rounded-lg border border-ok/50 bg-ok/10 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-ok transition hover:bg-ok/20 disabled:opacity-50"
            >
              {resolving ? "…" : approveLabel}
            </button>
            <button
              disabled={resolving}
              onClick={() => onDecide(false)}
              className="rounded-lg border border-danger/50 bg-danger/10 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-danger transition hover:bg-danger/20 disabled:opacity-50"
            >
              {resolving ? "…" : rejectLabel}
            </button>
            {onSkip && (
              <button
                disabled={resolving}
                onClick={onSkip}
                title="Not now — keep it pending and show the next"
                className="ml-auto rounded-lg border border-ink-dim/30 bg-white/5 px-4 py-1.5 font-mono text-sm uppercase tracking-widest text-ink-dim transition hover:bg-white/10 disabled:opacity-50"
              >
                Skip
              </button>
            )}
          </div>
          <p className="mt-2 text-xs text-ink-dim">
            {resolving ? "Working on it…" : helper}
          </p>
        </>
      )}
    </div>
  );
}
