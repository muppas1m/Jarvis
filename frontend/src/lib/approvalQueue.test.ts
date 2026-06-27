/**
 * Headless tests for the unified approval queue (3C) — the dedup-by-approval_id
 * contract that lets a 3B in-stream card and a 3A queue poll present exactly once.
 * Pure logic, no DOM — run with `npm test` (node:test + tsx).
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  cardButtonLabels,
  cardToApproval,
  inferKind,
  leadInFor,
  markSkipped,
  selectNextCard,
  type UnifiedApprovalCard,
} from "./approvalQueue";
import type { StreamItem } from "./types";

test("cardButtonLabels — a heads-up reads Draft it / Leave it, else Approve / Reject", () => {
  const headsUp = cardButtonLabels(true);
  assert.equal(headsUp.approve, "Draft it");
  assert.equal(headsUp.reject, "Leave it");
  assert.match(headsUp.badge, /Draft/);
  assert.match(headsUp.helper, /draft it/i);

  const simple = cardButtonLabels(false);
  assert.equal(simple.approve, "Approve");
  assert.equal(simple.reject, "Reject");
  assert.match(simple.badge, /Approve/);
});

test("leadInFor — a needs_drafting email card reads as a heads-up, not 'I've drafted'", () => {
  const headsUp: UnifiedApprovalCard = { ...card("e1", "email"), needs_drafting: true };
  assert.match(leadInFor(headsUp, true), /say the word and I'll draft it/i);
  const simple: UnifiedApprovalCard = { ...card("e2", "email"), needs_drafting: false };
  assert.match(leadInFor(simple, true), /drafted a reply/i);
});

function card(id: string, kind: "email" | "tool" = "tool"): UnifiedApprovalCard {
  return {
    approval_id: id,
    kind,
    thread_id: kind === "email" ? `email:gmail:${id}` : "web:master",
    tool_name: kind === "email" ? "email_reply" : "calendar_create",
    tool_args: {},
    description: `card ${id}`,
    status: "pending",
    created_at: "2026-06-25T00:00:00Z",
  };
}

// queue is oldest-first: A (oldest) → B → C (newest)
const QUEUE = [card("A"), card("B"), card("C")];

test("empty seen → returns the oldest (head of the queue)", () => {
  const next = selectNextCard(QUEUE, new Set());
  assert.equal(next?.approval_id, "A");
});

test("DEDUP: a card already on the timeline is never re-surfaced", () => {
  // C is the newest — surfaced in-stream by 3B (present-in-moment) → it's "seen".
  // A later poll returns the whole queue [A,B,C] but must NOT re-surface C.
  const next = selectNextCard(QUEUE, new Set(["C"]));
  assert.equal(next?.approval_id, "A"); // the oldest unseen, NOT C
  assert.notEqual(next?.approval_id, "C");
});

test("DEDUP holds regardless of card status (resolved cards stay suppressed)", () => {
  // A resolved earlier (still on the timeline), C is in-stream pending. Poll skips
  // both by id and surfaces B.
  const next = selectNextCard(QUEUE, new Set(["A", "C"]));
  assert.equal(next?.approval_id, "B");
});

test("every queued card already seen → null (nothing new to surface)", () => {
  assert.equal(selectNextCard(QUEUE, new Set(["A", "B", "C"])), null);
});

test("ordering: with the head seen, the NEXT oldest surfaces", () => {
  assert.equal(selectNextCard(QUEUE, new Set(["A"]))?.approval_id, "B");
});

test("cardToApproval carries kind + pending status, drops queue-only fields", () => {
  const a = cardToApproval(card("X", "email"));
  assert.equal(a.approval_id, "X");
  assert.equal(a.kind, "email");
  assert.equal(a.status, "pending");
  assert.equal(a.tool_name, "email_reply");
});

test("leadInFor reads sensibly per kind (tool ≠ 'drafted a reply')", () => {
  assert.match(leadInFor(card("A", "email"), true), /drafted a reply/);
  assert.match(leadInFor(card("A", "tool"), true), /action awaiting/);
  assert.doesNotMatch(leadInFor(card("A", "tool"), true), /reply/);
});

test("inferKind: email_reply → email, anything else → tool", () => {
  assert.equal(inferKind("email_reply"), "email");
  assert.equal(inferKind("calendar_create"), "tool");
  assert.equal(inferKind("email_send"), "tool"); // a TOOL (agent-direct), not an inbound reply
});

// --- skip/next (3D) — the DB-inert deferral ---------------------------------
function decisionItem(id: string, status: "pending" | "skipped" = "pending"): StreamItem {
  return {
    type: "decision",
    id,
    approval: { approval_id: id, tool_name: "calendar_create", tool_args: {}, status },
  };
}

test("markSkipped is DB-INERT: greys ONLY the target card, removes nothing, no network", () => {
  const items: StreamItem[] = [decisionItem("A"), decisionItem("B")];
  const out = markSkipped(items, "A");
  // a PURE transform (no fetch reference exists) → zero network calls by construction
  const a = out.find((x) => x.type === "decision" && x.approval.approval_id === "A");
  const b = out.find((x) => x.type === "decision" && x.approval.approval_id === "B");
  assert.equal(a?.type === "decision" && a.approval.status, "skipped"); // deferred, not removed
  assert.equal(b?.type === "decision" && b.approval.status, "pending"); // others untouched
  assert.equal(out.length, 2); // nothing dropped
  // the original is not mutated (no in-place side effects)
  assert.equal(items[0].type === "decision" && items[0].approval.status, "pending");
});

test("skip ADVANCES: the skipped id is 'seen' → selectNextCard surfaces the next; the row stays in /queue", () => {
  const queue = [card("A"), card("B")]; // mirrors GET /approvals/queue (the DB)
  // master skips A → it's greyed on the timeline, so its id joins "seen".
  const seen = new Set(["A"]);
  const next = selectNextCard(queue, seen);
  assert.equal(next?.approval_id, "B"); // advanced to the next, one-at-a-time
  // DB-inert: A is STILL in the queue (skip touched no backend) → reappears on reload
  assert.ok(queue.some((c) => c.approval_id === "A"));
  assert.equal(queue.length, 2);
});

test("skip never resolves: a skipped card is not approved/rejected, just deferred", () => {
  const out = markSkipped([decisionItem("A")], "A");
  const a = out[0];
  assert.ok(a.type === "decision" && a.approval.status === "skipped");
  assert.notEqual(a.type === "decision" && a.approval.status, "approved");
  assert.notEqual(a.type === "decision" && a.approval.status, "rejected");
});

// --- #2: terminal outcome states reload as resolved badges, never live cards ---------------
import {
  isResolvedStatus,
  normalizeApprovalStatus,
  resolvedBadge,
} from "./approvalQueue";

test("normalizeApprovalStatus — terminal outcome states map THROUGH, never to pending", () => {
  // THE reload bug: executed/failed/unconfirmed previously dropped to "pending" → a sent/failed
  // action came back as a live Approve/Reject card.
  assert.equal(normalizeApprovalStatus("executed"), "executed");
  assert.equal(normalizeApprovalStatus("failed"), "failed");
  assert.equal(normalizeApprovalStatus("unconfirmed"), "unconfirmed");
  // decision states unchanged; expiry → discarded; unknown → pending
  assert.equal(normalizeApprovalStatus("approved"), "approved");
  assert.equal(normalizeApprovalStatus("expired"), "discarded");
  assert.equal(normalizeApprovalStatus(undefined), "pending");
});

test("isResolvedStatus — terminal states are resolved (no Approve/Reject buttons)", () => {
  for (const s of ["executed", "failed", "unconfirmed", "approved", "rejected", "discarded", "skipped"] as const) {
    assert.equal(isResolvedStatus(s), true, `${s} must be resolved`);
  }
  assert.equal(isResolvedStatus("pending"), false);
  assert.equal(isResolvedStatus("resolving"), false);
});

test("resolvedBadge — a failed send reads ❌ Failed; executed is kind-aware; uncertain is ⚠️", () => {
  // The master's reload self-test: a failed send shows ❌ (and, via isResolvedStatus, no buttons).
  assert.deepEqual(resolvedBadge("failed", "email"), { text: "❌ Failed", cls: "text-danger" });
  assert.equal(resolvedBadge("executed", "email").text, "✅ Sent"); // email → Sent
  assert.equal(resolvedBadge("executed", "tool").text, "✅ Done"); //  tool  → Done
  assert.equal(resolvedBadge("unconfirmed", "email").text, "⚠️ Unconfirmed");
});
