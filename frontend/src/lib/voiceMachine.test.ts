/**
 * Headless tests for the voice state machine + barge-in gate (Phase 4.3a).
 * Pure logic, no DOM — run with `npm test` (node:test + tsx). The duplex *feel*
 * (talk over Jarvis, follow-up without "hey jarvis") is the live Chrome test.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BargeInTracker,
  orbStateFor,
  voiceReducer,
  type VoiceEvent,
  type VoicePhase,
} from "./voiceMachine";

const run = (start: VoicePhase, events: VoiceEvent[]): VoicePhase =>
  events.reduce(voiceReducer, start);

test("WAKE is honoured only from idle (cold start)", () => {
  assert.equal(voiceReducer("idle", { type: "WAKE" }), "listening");
  assert.equal(voiceReducer("responding", { type: "WAKE" }), "responding");
  assert.equal(voiceReducer("thinking", { type: "WAKE" }), "thinking");
});

test("a non-empty capture starts a turn; empty/whitespace drops to idle", () => {
  assert.equal(
    voiceReducer("listening", { type: "CAPTURE_RESULT", transcript: "what's on my calendar" }),
    "thinking",
  );
  assert.equal(voiceReducer("listening", { type: "CAPTURE_RESULT", transcript: "   " }), "idle");
  assert.equal(voiceReducer("listening", { type: "CAPTURE_EMPTY" }), "idle");
  assert.equal(
    voiceReducer("continuity", { type: "CAPTURE_RESULT", transcript: "and tomorrow?" }),
    "thinking",
  );
  assert.equal(voiceReducer("continuity", { type: "CAPTURE_EMPTY" }), "idle");
});

test("full hands-free cycle: wake → capture → think → respond → continuity", () => {
  assert.equal(
    run("idle", [
      { type: "WAKE" },
      { type: "CAPTURE_RESULT", transcript: "hello" },
      { type: "TURN_RESPONDING" },
      { type: "TURN_DONE" },
    ]),
    "continuity",
  );
});

test("continuity → next command without re-waking, then loops", () => {
  assert.equal(
    run("continuity", [
      { type: "CAPTURE_RESULT", transcript: "follow up" },
      { type: "TURN_RESPONDING" },
      { type: "TURN_DONE" },
    ]),
    "continuity",
  );
});

test("continuity silence falls back to idle (wake-word)", () => {
  assert.equal(voiceReducer("continuity", { type: "CAPTURE_EMPTY" }), "idle");
});

test("barge-in cuts from responding → listening, and only from responding", () => {
  assert.equal(voiceReducer("responding", { type: "BARGE_IN" }), "listening");
  assert.equal(voiceReducer("thinking", { type: "BARGE_IN" }), "thinking");
  assert.equal(voiceReducer("idle", { type: "BARGE_IN" }), "idle");
  assert.equal(voiceReducer("continuity", { type: "BARGE_IN" }), "continuity");
});

test("turn events outside an active turn are ignored (a typed turn must not hijack)", () => {
  assert.equal(voiceReducer("idle", { type: "TURN_RESPONDING" }), "idle");
  assert.equal(voiceReducer("idle", { type: "TURN_DONE" }), "idle");
  assert.equal(voiceReducer("listening", { type: "TURN_RESPONDING" }), "listening");
});

test("RESET always returns to idle", () => {
  for (const p of ["listening", "thinking", "responding", "continuity"] as VoicePhase[]) {
    assert.equal(voiceReducer(p, { type: "RESET" }), "idle");
  }
});

test("orbStateFor maps phases; idle defers to the turn state (typed turns animate)", () => {
  assert.equal(orbStateFor("listening", "idle"), "listening");
  assert.equal(orbStateFor("continuity", "idle"), "listening");
  assert.equal(orbStateFor("thinking", "idle"), "thinking");
  assert.equal(orbStateFor("responding", "idle"), "responding");
  assert.equal(orbStateFor("idle", "responding"), "responding");
  assert.equal(orbStateFor("idle", "idle"), "idle");
});

test("BargeInTracker fires once after sustained speech (220ms / 80ms = 3 frames)", () => {
  const t = new BargeInTracker(0.6, 220, 80);
  assert.equal(t.push(0.7), false); // 1
  assert.equal(t.push(0.8), false); // 2
  assert.equal(t.push(0.9), true); //  3 → crossing
  assert.equal(t.push(0.9), false); // already fired, no re-fire on the same burst
});

test("BargeInTracker resets on a sub-threshold frame (rejects a lone TTS spike)", () => {
  const t = new BargeInTracker(0.6, 220, 80);
  t.push(0.9); // 1
  assert.equal(t.push(0.2), false); // gap → reset
  assert.equal(t.push(0.9), false); // restart: 1
  assert.equal(t.push(0.9), false); // 2
  assert.equal(t.push(0.9), true); //  3 → crossing
});

test("BargeInTracker.reset() clears the run", () => {
  const t = new BargeInTracker(0.6, 220, 80);
  t.push(0.9);
  t.push(0.9);
  t.reset();
  assert.equal(t.push(0.9), false); // back to 1
});
