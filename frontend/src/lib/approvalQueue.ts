import type { ApprovalKind, ApprovalRequest, ApprovalStatus, StreamItem } from "./types";

/**
 * The unified approval queue (3C) — consuming GET /api/approvals/queue.
 *
 * Pure, headless logic so the ONE rule that matters — dedup by approval_id — is
 * directly testable (node:test). A card surfaced in-stream the instant it was
 * queued (3B, via the `approval_required` event) and the SAME card returned by a
 * later queue poll carry an identical approval_id by design (3A + 3B made it so);
 * `selectNextCard` is what guarantees they present exactly once.
 */

/** The wire shape of GET /api/approvals/queue rows (backend UnifiedApprovalCard).
 *  A superset of ApprovalRequest, so a card renders through the same path. */
export interface UnifiedApprovalCard {
  approval_id: string;
  kind: ApprovalKind;
  thread_id: string;
  tool_name: string;
  tool_args: Record<string, unknown>;
  description?: string;
  status: string;
  created_at: string;
  needs_drafting?: boolean; // complex-email heads-up (no draft yet) — "say go to draft"
}

export interface ApprovalQueueResponse {
  approvals: UnifiedApprovalCard[];
  count: number;
}

/**
 * THE dedup contract. The queue is oldest-first across BOTH origins; `seenIds` is
 * every approval_id already on the timeline (a card surfaced in-stream by 3B, or
 * one resolved earlier — any status). Returns the first queue card NOT already
 * seen — i.e. the next to surface — or null if every queued card is already shown.
 *
 * This is why an in-stream card is never re-surfaced by a subsequent poll: its
 * approval_id is in `seenIds`, so it's skipped; the poll advances to the next.
 * One-at-a-time is the CALLER's guard (don't surface while a card is pending);
 * this function only decides WHICH card is next.
 */
export function selectNextCard(
  queue: UnifiedApprovalCard[],
  seenIds: Set<string>,
): UnifiedApprovalCard | null {
  return queue.find((c) => !seenIds.has(c.approval_id)) ?? null;
}

/** A queue card → the renderable ApprovalRequest (carrying `kind` so the card
 *  renders email vs tool with no special-casing). Always surfaced as pending. */
export function cardToApproval(c: UnifiedApprovalCard): ApprovalRequest {
  return {
    approval_id: c.approval_id,
    tool_name: c.tool_name,
    tool_args: c.tool_args,
    description: c.description,
    status: "pending",
    kind: c.kind,
    needs_drafting: c.needs_drafting,
  };
}

/** Kind-aware lead-in for a POLL-surfaced card — one the master wasn't present for
 *  (a present-in-moment card arrives via 3B with no lead-in). `first` = the first
 *  card surfaced this session. */
export function leadInFor(card: UnifiedApprovalCard, first: boolean): string {
  if (card.kind === "email") {
    if (card.needs_drafting) {
      // Complex — not drafted yet; heads-up + the "say go" affordance.
      return first
        ? "You've got a bigger one here, Sir — say the word and I'll draft it."
        : "Here's another bigger one, Sir — say the word and I'll draft it.";
    }
    return first
      ? "I've drafted a reply for your approval, Sir."
      : "Here's another I've drafted, Sir…";
  }
  return first
    ? "There's an action awaiting your approval, Sir."
    : "Here's another action awaiting you, Sir…";
}

/** Infer a card's kind when the source didn't carry it (a 3B `approval_required`
 *  event or a hydrated history row): an email reply is always tool_name
 *  "email_reply"; everything else is a tool. */
export function inferKind(toolName: string): ApprovalKind {
  return toolName === "email_reply" ? "email" : "tool";
}

/** Normalize a backend approval status → the frontend ApprovalStatus. The terminal OUTCOME
 *  states (executed/failed/unconfirmed) map THROUGH, never to "pending" — so a reload renders
 *  a sent/failed/unconfirmed action as a resolved badge, never a live re-approvable card
 *  (re-approving a resolved row 404s at the backend claim-gate; this closes the UX gap). */
export function normalizeApprovalStatus(s?: string): ApprovalStatus {
  switch (s) {
    case "approved":
      return "approved";
    case "rejected":
      return "rejected";
    case "discarded":
    case "expired":
      return "discarded";
    case "executed":
      return "executed";
    case "failed":
      return "failed";
    case "unconfirmed":
      return "unconfirmed";
    default:
      return "pending";
  }
}

/** A card with a decision OR a terminal outcome → render resolved, NO Approve/Reject buttons. */
export function isResolvedStatus(status: ApprovalStatus): boolean {
  return (
    status === "approved" ||
    status === "rejected" ||
    status === "discarded" ||
    status === "skipped" ||
    status === "executed" ||
    status === "failed" ||
    status === "unconfirmed"
  );
}

/** The resolved-state badge (text + colour). executed is kind-aware ("Sent" for an email,
 *  "Done" for any other action); failed → ❌, unconfirmed → ⚠️. */
export function resolvedBadge(status: ApprovalStatus, kind: ApprovalKind): { text: string; cls: string } {
  switch (status) {
    case "approved":
      return { text: "Approved ✓", cls: "text-ok" };
    case "rejected":
      return { text: "Rejected ✗", cls: "text-danger" };
    case "executed":
      return { text: kind === "email" ? "✅ Sent" : "✅ Done", cls: "text-ok" };
    case "failed":
      return { text: "❌ Failed", cls: "text-danger" };
    case "unconfirmed":
      return { text: "⚠️ Unconfirmed", cls: "text-amber" };
    case "skipped":
      return { text: "Skipped — still awaiting", cls: "text-ink-dim" };
    default: // discarded
      return { text: "Discarded — superseded", cls: "text-ink-dim" };
  }
}

/** The card's button + helper copy. A COMPLEX-email heads-up (no draft yet) approves
 *  into a DRAFT, not a send — so it reads "Draft it / Leave it", matching Telegram +
 *  voice. Pure so the runner can test it without rendering the component. */
export function cardButtonLabels(needsDrafting: boolean): {
  approve: string;
  reject: string;
  badge: string;
  helper: string;
} {
  return needsDrafting
    ? { approve: "Draft it", reject: "Leave it", badge: "✎ Draft", helper: "…or say the word and I'll draft it." }
    : { approve: "Approve", reject: "Reject", badge: "⚠ Approve", helper: "…or just tell me what to change." };
}

/**
 * Skip (3D) = grey the pending card to "skipped" — a PURE, DB-INERT transform.
 * It returns new timeline items with only the target pending card flipped; the
 * queue (the DB mirror) is never passed in, so it cannot be touched, and a pure
 * function makes no network call by construction. The skipped card stays on the
 * timeline, so its approval_id is already in the poll's "seen" set — `selectNextCard`
 * skips it and surfaces the next, while the row stays pending and reappears on
 * reload. "Not now", never dismiss/reject.
 */
export function markSkipped(items: StreamItem[], approvalId: string): StreamItem[] {
  return items.map((x) =>
    x.type === "decision" &&
    x.approval.approval_id === approvalId &&
    x.approval.status === "pending"
      ? { ...x, approval: { ...x.approval, status: "skipped" as const } }
      : x,
  );
}
