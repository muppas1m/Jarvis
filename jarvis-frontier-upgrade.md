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
| `## Backward Audit Records (Turn 1 → Turn 19.2)` | Per-step audit records from the backward pass. Each entry documents what was audited, smells scanned, comparison target, tensions surfaced, and disposition (Phase 1.5 lift / memory-note deferral / in-place fix / no-action). Records persist even when no Phase 1.5 lift surfaced — traceability of "Step N happened, found X" matters for future-readers reconciling what was reviewed vs what shipped. |
| `## Phase 1.5 — Retroactive Foundation Lifts` | Per-lift entries surfaced by the Backward Audit Records section above. Consolidated and sub-phase-assigned at Step 23. |
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

- **Backward audit records** use the 7-field template:
  - `Scope` — what was audited (turn(s) / surfaces, with current-state acknowledgment if surface has drifted across later turns)
  - `References` — base plan lines + live code paths + memory notes consulted
  - `Smells checklist scan` — table of smells from `feedback_frontier_grade_discipline.md` checked + findings per smell (N/A / no-finding / concrete)
  - `Comparison target` — closest frontier-system anchor (or honest acknowledgment if none cleanly fits)
  - `Three-hats tension surfaced` — concrete tensions across architect / engineer / AI-ML engineer (absence of tension is the failure signal)
  - `Findings + disposition` — table of findings + per-finding disposition (Phase 1.5 lift / memory-note deferral / in-place fix landed at audit-write time / no-action positive finding / documentation acknowledgment)
  - `Overall rating + Status` — four-tier rating (frontier / mid / entry / plan-verbatim) + entry status (`proposed` / `final — sign-off <date>`)

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

## Backward Audit Records (Turn 1 → Turn 19.2)

> Per-step audit records from the backward pass. Each entry documents the audit work itself — smells scanned, comparison target, tensions surfaced, disposition. Cross-references to specific Phase 1.5 lift entries (below) where applicable. Records persist even when no Phase 1.5 lift surfaced.

### Step 2 — Phase 0 prelude — infra bootstrap surface (current state, originated Turns 1-3)

**Overall rating:** Mid-to-Frontier — **Status:** final — sign-off 2026-05-25

**Scope:**
Infra bootstrap surface in its current state. Surface originated in Turns 1-3 (base plan Tasks 0.3-0.10) but has accumulated additions across later turns (celery-worker + celery-beat services added Turn 17; celery-beat env override added Turn 18.5 commit `deae155`; Langfuse v3 stack detail evolved). Audit captures live state as of HEAD `4a327fb` + Step 1 commit `752d98f` + this step's in-place fix.

**References:**

| Surface | File / location |
|---|---|
| Docker orchestration | `docker-compose.yml` (344 lines, 12 services: 5 app + 7 Langfuse v3 stack + minio-init sidecar) |
| Backend container | `backend/Dockerfile` |
| Python deps + tool config | `backend/pyproject.toml` |
| Env template | `.env.example` (113 lines, all-phases coverage) |
| Git exclusions | `.gitignore` |
| Postgres init | `infra/postgres/init.sql` |

Base plan: lines 14-1300 (Pre-Phase 0 + Phase 0 prelude). Memory notes consulted: `project_docker_compose_restart_does_not_reload_env.md`, `feedback_conversation_agreements_land_in_plan.md`, `feedback_frontier_grade_discipline.md`.

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | No classifier surface |
| Flat string output | N/A | No tool output |
| One-line tool description | N/A | No tools |
| Single-item interface | N/A | No callable interfaces |
| Module-level instantiation triggering I/O | N/A | Infra surface |
| Logging-via-omission | N/A | No application logging |
| Sync bypass of cost-tracking / observability | N/A | No LLM calls |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | No prompts |
| Plan-verbatim task order | N/A | Foundation layer |
| **Documentation drift from code** | **YES** | (a) `.env.example` `## Webhook Tunneling` block framed Cloudflare tunnel as "runs as a sidecar service" — implies persistent named-tunnel setup that doesn't exist in `infra/`. Actual operational pattern is ad-hoc `cloudflared tunnel --url …` per session. (b) Plan Task 0.8 says "bring up full infra stack" without detailing the live Langfuse v3 8-service deployment shape — live exceeds plan in a frontier-positive direction; pure documentation drift, no operational consequence. |
| Verification axis mismatch | N/A | No runtime claims |
| Single-shot prompt | N/A | No prompts |
| Speculative complexity dressed as future-proofing | **Possibly** | 8-service Langfuse v3 stack from Day 1 is heavy for single-master scale. Probably justified (frontier observability shape, self-hosted, no cloud cost), but architectural weight worth flagging. Deferred-with-trigger. |

**Comparison target:**

No consumer-facing frontier system has openly comparable infra layer (dev/devops shape, not user-facing feature). Closest reference: Anthropic's published agent-cookbook examples + Cursor's open dev infra. Both tend toward minimal infra (env vars + Docker compose). Live state matches that minimal-but-complete shape, with observability over-provisioned (Langfuse v3 full stack) for the Phase-2 scale we're at — that over-provisioning is intentional frontier-shape, accepted.

**Three-hats tension surfaced:**

- **Architect:** observability landed before features need it (Langfuse v3 from Day 0 — concrete win). 8 services add operational complexity (`docker compose up` brings up 12+ containers). Tension resolved in favor of full v3 stack — observability completeness wins over operational simplicity. Revisit trigger: constrained-RAM deployment OR Langfuse v3 itself breaks mid-session.
- **Engineer:** `.env.example` as single authoritative reference (all 113 lines, all phases) wins on completeness, loses on dev-experience clarity (lots of empty Phase-4 envs visible from Day 0). Tension resolved in favor of completeness — reference shape, not active config.
- **AI-ML engineer:** pinning discipline explicit (`langchain 0.3.x` + `langfuse 2.x` pins with rationale documented inline in `pyproject.toml`). Wins on future-debuggability. Loses on cleanup — known tech debt. Tension resolved in favor of pragmatic-now with explicit docs — when LiteLLM upstream catches up to v3+/v4 Langfuse SDK, the pins lift.

All three tensions surfaced — discipline firing as intended.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | Cloudflare tunnel framing drift — `.env.example` describes persistent named-tunnel setup that doesn't exist in `infra/cloudflare/`. Actual pattern: ad-hoc per-session. | **In-place fix landed at audit-write time:** `.env.example` Webhook Tunneling block reframed as "production setup — currently deferred" + vars commented-out as reference. Persistent-tunnel implementation deferred → memory note `project_persistent_tunnel_deferral.md` saved with trigger conditions. |
| F2 | Plan Task 0.8 description vs live Langfuse v3 8-service stack — live exceeds plan in frontier-positive direction. | **No-action documentation acknowledgment.** Per `feedback_conversation_agreements_land_in_plan.md`: base plan is historical baseline; this upgrade doc is authoritative. Mentioned here for traceability; no further work. |
| F3 | Langfuse v3 stack operational weight (8 services for single-master scale). | **Deferred-with-trigger.** Memory note `project_langfuse_stack_weight_deferral.md` saved (triggers: constrained-RAM deployment OR Langfuse-v3-internal failure mid-session OR LiteLLM ships v3+/v4 Langfuse SDK opening lighter alternatives). Justified at current scale — observability completeness is frontier-correct for an agent system. |
| F4 | Frontier-grade infra discipline touches observed. | **No-action positive finding:** (1) `pyproject.toml` pin-rationale comments (langchain/langfuse interaction chain documented inline). (2) `Dockerfile` stub-app editable-install trick (anticipates pip ordering quirk). (3) celery-beat env config carries retrospective comment from Turn 18.5 fix (verification-axis discipline visible). (4) `.gitignore` excludes agent caches (`.claude_local/`, `.aider*`). (5) `infra/postgres/init.sql` includes Alembic-required schema grants (anticipates Task 1.5 migration needs). |

**Phase 1.5 lift assignment:** **None** from this step. F1 was small enough to land in-place at audit-write time. F3 is deferral-with-trigger.

**Cross-references:**
- Base plan header amendment: Step 1 commit `752d98f`
- Memory notes saved at this step: `project_persistent_tunnel_deferral.md` (F1) + `project_langfuse_stack_weight_deferral.md` (F3)
- Pre-existing memory notes referenced: `project_docker_compose_restart_does_not_reload_env.md`, `feedback_conversation_agreements_land_in_plan.md`, `feedback_frontier_grade_discipline.md`

## Phase 1.5 — Retroactive Foundation Lifts (Backward Audit Output)

> Sub-phase letters (`a` / `b` / `c`) and per-lift numbering assigned at Step 23 (consolidation) based on dependencies surfaced across Steps 2-22. Per-lift entries use the Phase 1.5 lift template described above.

_(populated by Steps 2-22; consolidated at Step 23)_

## Retroactive Turn Entries (Turn 18 onward)

> Per-turn entries for turns that applied frontier discipline at design time. Documentation-only — code already committed; entries capture the lens-application reasoning for future readability.

_(populated by Steps 20 and 22)_
