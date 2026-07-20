/** Item #8 — the render contract (γ-1/γ-2/γ-3), pure and node-testable.
 *  The γ-1/γ-2 cases encode the EXACT live-captured frame sequences. */
import assert from "node:assert/strict";
import { test } from "node:test";

import { annotateResolvedMints, reconcileFinal, upsertAssistant } from "./streamRender";
import type { StreamItem } from "./types";

const bubble = (id: string, content: string): StreamItem =>
  ({ type: "message", id, role: "assistant", content }) as StreamItem;

// ---------------- γ-1: append-if-missing (the missing bubble) ---------------- //
test("upsert patches the existing placeholder in place", () => {
  const items: StreamItem[] = [bubble("ai-1", "partial")];
  const out = upsertAssistant(items, "ai-1", "partial + more");
  assert.equal(out.length, 1);
  assert.equal((out[0] as { content: string }).content, "partial + more");
});

test("γ-1: the live-captured pure-queue turn — placeholder dropped, done APPENDS", () => {
  // captured frames: approval_required @ acc_len=0 dropped the placeholder; the
  // done read-back ("I've queued an email to amy@x.com …") previously mapped over
  // nothing → NO bubble until refresh. The upsert must append it.
  const afterCardDroppedPlaceholder: StreamItem[] = [
    { type: "decision", id: "card-1", approval: { approval_id: "card-1" } } as unknown as StreamItem,
  ];
  const out = upsertAssistant(afterCardDroppedPlaceholder, "ai-1",
    "I've queued an email to amy@x.com about 'RenderProbe' for your approval, Sir — shall I go ahead?");
  assert.equal(out.length, 2);
  const appended = out[1] as { type: string; role: string; content: string };
  assert.equal(appended.type, "message");
  assert.equal(appended.role, "assistant");
  assert.match(appended.content, /queued an email to amy@x\.com/);
});

test("upsert with empty content appends nothing", () => {
  const out = upsertAssistant([], "ai-1", "");
  assert.equal(out.length, 0);
});

// ---------------- γ-2: reconcile, never clobber (the vanishing bubble) ------- //
test("done == streamed → unchanged", () => {
  assert.equal(reconcileFinal("hello world", "hello world"), "hello world");
});

test("done is a superset (floor appended) → the superset wins", () => {
  const acc = "Here's the email read aloud.";
  const fin = "Here's the email read aloud.\n\nShall I go ahead, Sir?";
  assert.equal(reconcileFinal(acc, fin), fin);
});

test("γ-2: divergent terminal read-back APPENDS as a delta — the streamed body survives", () => {
  // pts 14/16: reading aloud streamed the full email; queued_finish reshaped the
  // terminal to the short read-back → the old overwrite VANISHED the streamed text.
  const acc = "Reading it back: Hi Frank, long body of the email as spoken aloud…";
  const fin = "an email to Frank@test.com about 'Plans' — shall I go ahead, Sir?";
  const out = reconcileFinal(acc, fin);
  assert.match(out, /long body of the email/);               // never clobbered
  assert.match(out, /Frank@test\.com/);                      // the terminal delta appended
});

test("empty acc → the terminal text stands alone", () => {
  assert.equal(reconcileFinal("", "the read-back"), "the read-back");
});

test("empty done keeps the streamed body", () => {
  assert.equal(reconcileFinal("streamed", ""), "streamed");
});

test("duplicate paragraphs are not appended twice", () => {
  const acc = "Lead paragraph.\n\nShall I go ahead, Sir?";
  const fin = "Lead paragraph.\n\nShall I go ahead, Sir?";
  assert.equal(reconcileFinal(acc, fin), acc);
});

// ---------------- γ-3: the mint line reconciles to live row status ------------ //
test("γ-3: a mint bubble whose linked card is REJECTED gets a live-status note", () => {
  const items: StreamItem[] = [
    { ...bubble("m1", "I've queued an email for your approval — shall I go ahead?"),
      approval_ids: ["a1"] } as unknown as StreamItem,
    { type: "decision", id: "a1",
      approval: { approval_id: "a1", status: "rejected" } } as unknown as StreamItem,
  ];
  const out = annotateResolvedMints(items);
  const m = out[0] as { content: string; note?: string };
  assert.match(m.content, /shall I go ahead/);               // persisted words untouched
  assert.match(m.note ?? "", /rejected/i);                   // the live truth annotated
});

test("γ-3: a still-pending card gets NO note", () => {
  const items: StreamItem[] = [
    { ...bubble("m1", "queued — shall I go ahead?"), approval_ids: ["a1"] } as unknown as StreamItem,
    { type: "decision", id: "a1",
      approval: { approval_id: "a1", status: "pending" } } as unknown as StreamItem,
  ];
  const out = annotateResolvedMints(items);
  assert.equal((out[0] as { note?: string }).note, undefined);
});

test("γ-3: mixed statuses (one resolved, one pending) → no note (still awaiting)", () => {
  const items: StreamItem[] = [
    { ...bubble("m1", "two queued — shall I go ahead?"), approval_ids: ["a1", "a2"] } as unknown as StreamItem,
    { type: "decision", id: "a1", approval: { approval_id: "a1", status: "rejected" } } as unknown as StreamItem,
    { type: "decision", id: "a2", approval: { approval_id: "a2", status: "pending" } } as unknown as StreamItem,
  ];
  const out = annotateResolvedMints(items);
  assert.equal((out[0] as { note?: string }).note, undefined);
});
