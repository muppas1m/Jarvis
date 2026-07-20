/** Item #8 — the render contract (γ-1/γ-2/γ-3).
 *
 * The three sitting bugs shared one root: the live timeline had an overwrite-only
 * patch and no append path, and the mint-time approval line never consulted the
 * live row. These pure helpers carry the contract; useJarvis delegates to them so
 * the token, done, AND error paths all inherit the same behavior.
 */
import type { StreamItem } from "./types";

/** γ-1 — append-if-missing: patch the assistant bubble in place when it exists,
 *  APPEND a fresh one when the placeholder was dropped (e.g. by a pure-queue turn's
 *  `approval_required`). Empty content never creates a bubble. */
export function upsertAssistant(items: StreamItem[], aiId: string, content: string): StreamItem[] {
  const exists = items.some((x) => x.type === "message" && x.id === aiId);
  if (exists) {
    return items.map((x) => (x.type === "message" && x.id === aiId ? { ...x, content } : x));
  }
  if (!content) return items;
  return [...items, { type: "message", id: aiId, role: "assistant", content }];
}

/** γ-2 — reconcile the terminal payload with the streamed body, never clobber:
 *  superset terminals win (streamed + floor); a DIVERGENT terminal read-back is
 *  appended as a delta below the streamed text (paragraph-level, deduped). Worst
 *  case is one near-duplicate paragraph — honest over vanished. */
export function reconcileFinal(acc: string, response: string): string {
  const streamed = (acc || "").trim();
  const terminal = (response || "").trim();
  if (!streamed) return terminal;
  if (!terminal || terminal === streamed) return streamed;
  if (terminal.includes(streamed)) return terminal;         // streamed + additions
  if (streamed.includes(terminal)) return streamed;         // terminal is a subset
  const have = streamed;
  const delta = terminal
    .split(/\n{2,}/)
    .map((b) => b.trim())
    .filter((b) => b && !have.includes(b));
  return delta.length ? `${streamed}\n\n${delta.join("\n\n")}` : streamed;
}

/** γ-3 — reconcile mint-time approval text to the LIVE row status at render: a
 *  message bubble linked (via the persisted jarvis tag, exposed by /history) to
 *  cards that are ALL resolved gets a muted live-status note. The persisted words
 *  are never rewritten; the note carries the truth. */
const _RESOLVED = new Set(["approved", "rejected", "discarded", "executed", "failed", "expired"]);

export function annotateResolvedMints(items: StreamItem[]): StreamItem[] {
  const statusById = new Map<string, string>();
  for (const it of items) {
    if (it.type === "decision") statusById.set(it.approval.approval_id, it.approval.status ?? "");
  }
  return items.map((it) => {
    if (it.type !== "message") return it;
    const ids = (it as { approval_ids?: string[] }).approval_ids ?? [];
    if (!ids.length) return it;
    const statuses = ids.map((id) => statusById.get(id) ?? "");
    if (!statuses.every((s) => _RESOLVED.has(s))) return it; // anything pending → still awaiting
    const label = [...new Set(statuses)].join(" / ");
    return { ...it, note: `since ${label}` };
  });
}
