# Jarvis — Frontier-Grade Upgrade Plan

> **⚠️ Execution context:** Halted 2026-05-25 after commit `4a327fb` at Turn 19.2 close (mid-Phase-2). This document is the frontier-grade upgrade layer applied over `jarvis-implementation-plan.md` (the historical baseline). Backward lifts (Turn 1 through 19.2) are being drafted first. Forward execution resumes from Turn 19.3 once the backward pass completes and Phase 1.5 lifts ship per the slotting decided at Step 23 of the backward audit.

## How to use this document

This document is **authoritative for what's actually being executed under the frontier-grade discipline.** `jarvis-implementation-plan.md` is the historical baseline — read it for original spec, read this document for active execution scope.

**When designing or executing a turn (or a Phase 1.5 lift):**

1. `git log --oneline -5` + `git status --short` — establish current state
2. Open this document. Scan the Table of Contents for the relevant turn or lift entry.
3. If an entry exists: read it top-to-bottom.
4. **MANDATORY:** also read the base plan section referenced in the entry's `Baseline` (or `Plan-markdown reference`) quote. Verify the quote against current base-plan state — quote drift IS a finding. Read the surrounding base-plan section for fuller context the quote slice may miss.
5. Cross-reference any memory notes named in the entry.
6. Read live code referenced by the entry.
7. At execution time: propose design at gate, await sign-off, code, verify, commit. Same gate-before-commit discipline as before.
8. Status update: flip the entry's status when it ships (`queued` → `committed <SHA>` for forward turns/lifts; `proposed` → final for audit findings, only after per-step review converges).
9. **Note for audit-time writers:** the same mandatory base-plan cross-read in Step 4 applies when WRITING Phase 1.5 entries during the backward audit, not just at downstream execution time. Re-verify the verbatim quote against current base-plan state at the moment of writing. The plan may have shifted between audit research and entry-write. Quote drift caught at write-time becomes part of the `Discrepancies surfaced` finding.

**Section structure:**

| Section | Purpose |
|---|---|
| `## Phase 1.5 — Retroactive Foundation Lifts` | Backward audit output. Sub-phases (`1.5a` / `1.5b` / `1.5c` — letters assigned at Step 23 consolidation) group lifts by execution slot per surfaced dependencies. |
| `## Retroactive Turn Entries (Turn 18 onward)` | Per-turn entries for turns that applied frontier discipline at design time (currently Turn 18, 19.1+19.2). Documentation-only — no further execution work. |

> Forward sections (Phase 2 remaining turns, Phase 2.5 / 3 / 4 structural shape) are scoped separately as a forward design pass after the backward audit completes. They are not pre-created.

**Entry templates:**

- **Phase 1.5 lift entries** use the 3-section anchor plus surrounding context fields:
  - `Live-code observation` — what actually exists in the codebase right now (file:line cites)
  - `Plan-markdown reference` — what was originally specified, verbatim quote with line cite from `jarvis-implementation-plan.md`. **At audit-write time the quote MUST be re-verified against current base-plan state — not just relied on from earlier reads. Drift caught at write-time becomes part of the `Discrepancies surfaced` finding.**
  - `Discrepancies surfaced` — drift between live code and plan markdown (itself a finding the lift may need to address)
  - `Comparison target` — closest of Claude Projects / ChatGPT Custom GPTs / Cursor / Perplexity (or equivalent frontier system if no consumer-facing analog fits)
  - `Proposed lift` — high-level shape of the fix (not implementation detail)
  - `Verification plan` — how we'll know the lift actually closed the gap
  - `Slot` — sub-phase (`1.5a` / `1.5b` / `1.5c`) assigned at Step 23 consolidation
  - `Cross-references` — memory notes + base plan lines + dependent entries

- **Retroactive turn entries** use the 6-section template:
  - `Baseline` — verbatim quote from base plan with line + commit cite
  - `Comparison target` — closest of Claude Projects / ChatGPT Custom GPTs / Cursor / Perplexity
  - `Lifts applied` — what shipped vs plan-verbatim, by three-hats axis (architect / engineer / AI-ML engineer)
  - `Sub-steps` — if applicable
  - `Deferred with triggers` — what got memory-noted with trigger conditions
  - `Cross-references` — memory notes + base plan lines + dependent entries

**Naming conventions (locked):**

| Level | Pattern | Example |
|---|---|---|
| Umbrella phase | `Phase 1.5` | "Phase 1.5 — Retroactive Foundation Lifts" |
| Sub-phase by execution slot | `Phase 1.5<letter>` (letter assigned at Step 23) | "Phase 1.5a — Pre-Phase-2.5 Lifts" |
| Individual lift | `Phase 1.5<letter>-<N>` | "Phase 1.5a-1 — Registry MCP-Readiness" |
| Inserted lift post-consolidation | `.5` suffix on N | "Phase 1.5a-1.5" |
| Retroactive turn entry | `Turn N` | "Turn 18 — Extractors + Chunker" |

## Table of contents

> Populates as the backward audit progresses (Steps 2-22 of the writing plan). Each step's review-loop convergence adds a row.

| Entry | Status |
|---|---|
| _(empty — fills as audit progresses)_ | — |

## Phase 1.5 — Retroactive Foundation Lifts (Backward Audit Output)

> Sub-phase letters (`a` / `b` / `c`) and per-lift numbering assigned at Step 23 (consolidation) based on dependencies surfaced across Steps 2-22. Per-lift entries use the Phase 1.5 lift template described above.

_(populated by Steps 2-22; consolidated at Step 23)_

## Retroactive Turn Entries (Turn 18 onward)

> Per-turn entries for turns that applied frontier discipline at design time. Documentation-only — code already committed; entries capture the lens-application reasoning for future readability.

_(populated by Steps 20 and 22)_
