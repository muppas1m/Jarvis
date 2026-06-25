/**
 * Pure briefing formatters — urgency→chip-level + the header subtitle. No DOM;
 * run with `npm test` (node:test + tsx). The component maps the level to classes.
 */
import assert from "node:assert/strict";
import { test } from "node:test";

import { briefSummary, urgencyLevel } from "./briefingFormat";
import type { Brief } from "./types";

test("urgencyLevel maps known urgencies; null for none/empty/unknown", () => {
  assert.equal(urgencyLevel("immediate"), "danger");
  assert.equal(urgencyLevel("today"), "warn");
  assert.equal(urgencyLevel("this_week"), "info");
  assert.equal(urgencyLevel("none"), null);
  assert.equal(urgencyLevel(""), null);
  assert.equal(urgencyLevel("bogus"), null);
});

test("briefSummary covers error / empty / count", () => {
  const base: Brief = {
    created_at: "", empty: true, total: 0, timezone: "", error: false, days: [],
  };
  assert.equal(briefSummary(base), "nothing new");
  assert.equal(briefSummary({ ...base, error: true }), "couldn't build your digest");
  assert.equal(briefSummary({ ...base, empty: false, total: 3 }), "3 new");
  // error wins over a stale count
  assert.equal(briefSummary({ ...base, error: true, empty: false, total: 5 }), "couldn't build your digest");
});
