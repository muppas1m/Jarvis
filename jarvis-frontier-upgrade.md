# Jarvis — Frontier-Grade Upgrade Plan

> **⚠️ Execution context:** Halted 2026-05-25 after commit `4a327fb` at Turn 19.2 close (mid-Phase-2). This document is the frontier-grade upgrade layer applied over `jarvis-implementation-plan.md` (the historical baseline). Backward lifts (Turn 1 through 19.2) are being drafted first. Forward execution resumes from Turn 19.3 once the backward pass completes and Phase 1.5 lifts ship per the slotting decided at the consolidation step of the backward audit.

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
| `## Phase 1.5 — Retroactive Foundation Lifts` | Per-lift entries surfaced by the Backward Audit Records section above. Consolidated and sub-phase-assigned at the consolidation step. |
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
  - `Slot` — sub-phase (`1.5a` / `1.5b` / `1.5c`) assigned at the consolidation step
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
| Sub-phase by execution slot | `Phase 1.5<letter>` (letter assigned at the consolidation step) | "Phase 1.5a — Pre-Phase-2.5 Lifts" |
| Individual lift | `Phase 1.5<letter>-<N>` | "Phase 1.5a-1 — Registry MCP-Readiness" |
| Inserted lift post-consolidation | `.5` suffix on N | "Phase 1.5a-1.5" |
| Retroactive turn entry | `Turn N` | "Turn 18 — Extractors + Chunker" |

## Table of contents

> Populates as the backward audit progresses (all audit steps of the writing plan). Each step's review-loop convergence adds a row.

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

### Step 3 — Turn 4 — config/Settings + DB engine/models + initial Alembic + LangGraph checkpoints

**Overall rating:** Mid (engineering touches are frontier execution within a Mid foundation; rating lifts to Frontier when the multi-user schema gap below ships) — **Status:** final — sign-off 2026-05-25

**Scope:**
Turn 4 surface in current state. Surface originated at commit `ce39438` (db schema and alembic baseline) + the matching Settings + engine modules at the same commit. Audit captures live state as of HEAD `16dd266` + Step 2 close.

**References:**

| Surface | File / location |
|---|---|
| Pydantic Settings | `backend/app/config.py` (121 lines, ~50 env vars across all phases) |
| Async engine + session | `backend/app/db/engine.py` (54 lines) |
| ORM models | `backend/app/db/models.py` (297 lines, 11 tables + 3 composite indexes) |
| Alembic env | `backend/alembic/env.py` (87 lines, sync mode + injected DB URL) |
| Initial schema migration | `backend/alembic/versions/001_initial_schema.py` (269 lines, 11 tables + HNSW indexes on vector columns) |
| LangGraph checkpoint migration | `backend/alembic/versions/002_langgraph_checkpoints.py` (47 lines, wraps `PostgresSaver.setup()`) |

Base plan: Tasks 1.1-1.5 (lines 1309-1614). Memory notes consulted: `project_phase1_monolithic_migration.md`, `project_async_state_rebind_pattern.md`.

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | EmailLog stores 3-way classification result; classifier code is in Phase 2, not here |
| Flat string output | N/A | No tool surface |
| One-line tool description | N/A | No tools |
| Single-item interface | N/A | No batch-vs-single contract here |
| Module-level instantiation triggering I/O | **Mild** | `settings = Settings()` at config.py:120 reads `.env` from disk at import. Disk-only, no network. Acceptable for settings singleton; comment at line 8-11 acknowledges and documents upgrade path (`get_settings()` + `@lru_cache`) if multi-process ever needed. |
| Logging-via-omission | N/A | No application logging |
| Sync bypass of cost-tracking / observability | N/A | No LLM calls (foundation layer) |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | No prompts |
| Plan-verbatim task order | N/A | Foundation layer |
| Documentation drift from code | None found | `meta` naming gotcha, `init_db` not a migration, Mem0-vs-MemoryEpisode parallel-table relationship, Settings singleton + upgrade-path note — all docstring claims accurate vs live code |
| Verification axis mismatch | N/A | No runtime claims |
| Single-shot prompt | N/A | No prompts |
| Speculative complexity dressed as future-proofing | Possible | Settings declares all-phase env vars from Day 1. Same "all-phases reference" tension as Step 2 `.env.example` — design choice, accepted |

**Comparison target:**
Strong-FastAPI-shop conventions (SQLAlchemy 2.0 async + Alembic + Pydantic Settings + pgvector). FastAPI's own example apps + Anthropic's MCP Python SDK reference are the closest comparable shape. Live state matches strong-shop conventions throughout. Single material divergence from frontier: the multi-user schema gap (F1 below).

**Three-hats tension surfaced:**

- **Architect** wants monolithic migration covering all foreseen domains in one go (avoids fragmented migration chain). Wins on coherence. Loses on bisectability — `001_initial_schema` is 269 lines of schema decisions in one commit. Tension resolved in favor of monolithic; already documented in `project_phase1_monolithic_migration.md`.
- **Engineer** wants Settings as single source of truth with sensible defaults. Wins on completeness. Loses on dev-clarity (lots of empty Phase-4 envs declared from Day 0). Tension resolved in favor of completeness — reference surface with optional defaults.
- **AI-ML engineer** wants `EMBEDDING_DIM=1024` locked at schema level (Vector(1024) hardcoded in migration). Wins on type-safety + index correctness. Loses on swap-flexibility. Tension resolved with Task 2.20 migration script (planned).

All three tensions surfaced — discipline firing.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **Single-user schema — no `user_id` columns on any of 10 user-scoped tables.** UserProfile (single-row implicit master pattern); AuditTrail / LLMUsageLog / MemoryEpisode / PendingApproval / ConversationAnalytics / EmailLog / DocumentChunk / ToolResult / RateLimitEvent all lack user_id. (ToolEmbedding is system-wide; excluded from user-scoping scope.) Confirmed Phase 4 multi-user blocker per Explore agent's earlier finding. | **Proposed Phase 1.5 lift** (see Phase 1.5 section below). Schema-only scope; code-level write-path changes deferred to Phase 4. Sub-phase letter + position TBD at the consolidation step. |
| F2 | **MemoryEpisode parallel-to-Mem0 staleness risk** — table exists, described as "parallel custom-query view." Currently unpopulated (Mem0 SDK manages its own `mem0_memories` table; consolidation logic is a stub deferred to Turn 26.5). | **No Phase 1.5 lift.** Grep confirms ZERO code references to `memory_episodes` / `MemoryEpisode` outside `models.py` itself (table definition + composite index declaration only). No silent-fail risk today — table is dormant until Turn 26.5 consolidation populates it. Defer to Turn 26.5 close-out per existing plan slot (base plan lines 9671-9697). |
| F3 | **Settings declares orphan tunnel vars (`TUNNEL_PUBLIC_URL`, `CLOUDFLARE_TUNNEL_ID`) even after Step 2 reframed `.env.example`.** | **No-action documentation acknowledgment.** Two surfaces with different roles — Settings is maximal envelope; .env.example is dev-facing template. Settings defaults to empty strings if envs missing. Intentional asymmetry. |
| F4 | **`002_langgraph_checkpoints` migration is idempotent + correctly delegates to LangGraph's official `setup()`.** | **No-action positive finding.** Re-running upgrade against an already-set-up DB is a no-op (verified by docstring claim + live `with PostgresSaver.from_conn_string(sync_url) as saver: saver.setup()` pattern). |
| F5 | **Frontier-grade engineering touches observed.** | **No-action positive finding:** (1) `pool_pre_ping=True` + `pool_recycle=3600` in engine.py — anti-stale-connection defense. (2) `compare_type=True` + `compare_server_default=True` in alembic env.py — catches schema drift in autogenerate. (3) HNSW indexes for both vector columns (`document_chunks.embedding`, `memory_episodes.embedding`) — avoids sequential scan at scale. (4) 3 composite indexes for hot read paths. (5) `meta` vs `metadata` naming gotcha documented in module docstring. (6) Module docstring explicitly distinguishes what we own vs what LangGraph/Mem0 own. (7) Settings singleton pattern explicitly documented with upgrade-path note. (8) `init_db()` smoke-test is a `SELECT 1`, not a migration — clean separation. |

**Phase 1.5 lift assignment:** F1 → see Phase 1.5 section below (status `proposed`).

**Cross-references:**
- Base plan: lines 1309-1614 (Tasks 1.1-1.5)
- Memory notes referenced: `project_phase1_monolithic_migration.md`, `project_async_state_rebind_pattern.md`
- Related upcoming lifts expected: Mem0Client `USER_ID = "master"` hardcoded (will surface at Step 5 audit of Turn 6 — Memory layer); both will end up in Phase 1.5b as separate sequential lifts (slot decided at the consolidation step)
- Phase 1.5 lift entry surfaced at this step: F1 (multi-user schema readiness)

### Step 4 — Turn 5 — LiteLLM gateway + cost tracker + Langfuse observability

**Overall rating:** Mid (engineering touches frontier within Mid foundation; rating lifts when cost-attribution gaps close — but those are Phase-4-dashboard-triggered, not Phase 1.5) — **Status:** final — sign-off 2026-05-25

**Scope:**
Turn 5 surface in current state. Surface originated at commit `cdd32ad` (LLM gateway with Langfuse and cost tracking). Substantially extended at Turn 17.7 with `FallbackChatLLM` addition (commit `5d9a88d`). Audit captures live state as of HEAD `16dd266` + Step 3 close.

**References:**

| Surface | File / location |
|---|---|
| Gateway dispatch | `backend/app/llm/gateway.py` (182 lines) — central `complete()` + soft/hard cost-cap + 2-attempt tenacity retry + primary→fallback chain + DB log |
| Cost tracker | `backend/app/llm/cost_tracker.py` (67 lines) — Redis-counter per-UTC-day + atomic INCRBYFLOAT |
| Model registry | `backend/app/llm/models.py` (90 lines) — KNOWN_COSTS map + TASK_ROUTING + `@cache` on get_models() |
| Observability | `backend/app/llm/observability.py` (99 lines) — Langfuse v2 client (defensive against v3+ upgrade) + LangGraph callback handler |
| Provider bootstrap | `backend/app/llm/bootstrap.py` (84 lines) — idempotent provider wiring + Langfuse callback registration |
| FallbackChatLLM (Turn 17.7 addition) | `backend/app/llm/fallback_llm.py` (125 lines) — custom Runnable wrapping primary + fallback with predicate-based retry |

Base plan: Task 1.6 (lines 1616-1955). Memory notes consulted: `project_cost_cap_redis_only.md`, `project_agent_node_bypasses_gateway_fallback.md`, `project_agent_llm_cost_attribution_gap.md`, `project_embedding_cost_attribution_gap.md`, `project_groq_error_message_string_match_dependency.md`.

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | No classifier surface |
| Flat string output | N/A | No tool output |
| One-line tool description | N/A | No tools |
| Single-item interface | Possible | `cost_tracker.record()` per-call. Redis INCRBYFLOAT is atomic so per-call works fine. Acceptable. |
| Module-level instantiation triggering I/O | **No (discipline applied)** | `llm_gateway = LLMGateway()` instantiates Python objects only; Redis connection is lazy. `wire_all()` sets env vars + registers Langfuse callback (zero network I/O). Better than the `responder.py` pattern flagged in `project_module_level_mem0_instantiation_smell.md`. |
| Logging-via-omission | N/A | Both success (DB write) and failure (`llm_call_failed`, `falling_back`) paths logged |
| **Sync bypass of cost-tracking / observability gateways** | **KNOWN GAP (3 surfaces)** | (a) agent_node bypasses LLMGateway (uses ChatLiteLLM directly via `bind_tools()`) — `project_agent_node_bypasses_gateway_fallback.md` + `project_agent_llm_cost_attribution_gap.md`. (b) embedding calls (`litellm.aembedding`) bypass — `project_embedding_cost_attribution_gap.md`. (c) FallbackChatLLM (Turn 17.7) closes the FALLBACK side of (a) but not the cost-tracking side. |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | No prompts |
| Plan-verbatim task order | N/A | Foundation layer |
| Documentation drift from code | None found | Gateway docstring claims about tenacity retry, two observability channels, fallback chain — all verified. Bootstrap idempotency guard verified. Observability fresh-handler-per-call verified. |
| Verification axis mismatch | N/A | No runtime claims |
| Single-shot prompt | N/A | Gateway is dispatch layer; iterative reasoning is agent-loop concern |
| Speculative complexity dressed as future-proofing | Mild | KNOWN_COSTS includes `claude-opus-4-7` + `gpt-5` not currently used. Defensive but harmless. |

**Comparison target:**
LangChain's model wrappers + LangSmith integration is the closest comparable shape. **LiteLLM itself IS frontier-grade**; building cost-cap + DB log + retries + Langfuse on top is the strong-shop pattern. Live state matches; the FallbackChatLLM custom Runnable + the bootstrap module isolation pattern are frontier-execution additions that exceed plan-verbatim.

**Three-hats tension surfaced:**

- **Architect** wants LLMGateway as the SINGLE authoritative LLM surface. Wins on cost-tracking + observability completeness IF everything flows through it. Loses because LangGraph's `bind_tools()` API requires LangChain `BaseChatModel`, forcing agent_node to bypass the gateway. FallbackChatLLM closes the FALLBACK gap but leaves the cost-tracking gap. Tension resolved with documented gaps + memory notes.
- **Engineer** wants 2-attempt tenacity retry inside `_call_llm`. Compounds with primary→fallback: up to 4 LLM attempts per `complete()` call, plus FallbackChatLLM adds another retry tier at agent_node layer. Tension: defense-in-depth vs latency budget. Resolved with current pattern; latency budget acceptable at current scale.
- **AI-ML engineer** wants cross-provider fallback for outage resilience (Groq → OpenAI gpt-4o-mini in current config). Wins on single-provider outage protection. Loses on N-provider chain — hardcoded 3 slots (primary/fast/fallback); can't express "Groq → Anthropic → OpenAI" cascade. Per Explore agent: "extends but not architected for N-provider config." Tension resolved as Mid for current scale.

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **agent_node bypass of gateway — cost-tracking + cost-cap enforcement gap.** agent_node + FallbackChatLLM both invoke ChatLiteLLM directly; spend invisible to `cost_tracker.record()` + `LLMUsageLog`. KNOWN, memory-noted in `project_agent_llm_cost_attribution_gap.md` with three trigger conditions. | **Reaffirm existing deferral. NO Phase 1.5 lift.** Completeness-blocking (Phase 4 dashboard shows undercounted spend), not correctness-blocking (dashboard still functional). Memory note's trigger conditions cover the promotion criteria. |
| F2 | **embedding bypass of gateway — cost-tracking gap.** `litellm.aembedding()` called directly from ingestion + Mem0Client + tool_embedding registry. KNOWN, memory-noted in `project_embedding_cost_attribution_gap.md`. | **Reaffirm existing deferral.** Acceptable at Phase 2 (Ollama bge-m3 = $0). Trigger: paid embedding API OR Phase 4 dashboard cost-by-surface. |
| F3 | **Hardcoded 3-slot fallback chain** (primary / fast / fallback). Cross-provider via env var but no N-provider config. Surfaced by Explore agent. | **NEW memory note saved at this step:** `project_n_provider_fallback_deferral.md`. Trigger: Phase 3+ workflows needing provider cascade (e.g., research agent quality-tier escalation, multi-provider outage protection). Not Phase 1.5 — single-master scale doesn't need N-provider. |
| F4 | **Per-subgraph cost attribution gap.** Phase 3 subgraphs likely have very different cost profiles; current single-pool cost tracker can't surface per-subgraph spend. Tied to subgraph topology lift. | **Amended existing memory note at this step:** added cross-reference section to `project_subgraph_topology_for_phase3_or_4.md`. Not a new note. Not Phase 1.5. |
| F5 | **FallbackChatLLM string-match retry predicate fragility.** Predicate matches on `"tool_use_failed"` substring; Groq error rename would silently break the fallback. Memory-noted in `project_groq_error_message_string_match_dependency.md`. | **Reaffirm existing deferral. Honest framing:** fragility documented; canary signal identified (`agent_llm_fallback` log rate WoW comparison via `grep -c`) but NO active monitoring mechanism in place. Detection awaits manual `graph_invoke_failed` investigation triggered by master noticing "internal error" reports. Fix-when-it-bites trigger awaits. |
| F6 | **Frontier-grade engineering touches observed.** | **No-action positive finding:** (1) bootstrap module separates provider wiring from gateway — idempotent + zero-I/O at module import (discipline applied). (2) TASK_ROUTING decouples task-type from model-id (env-var-swappable). (3) FallbackChatLLM custom Runnable (Turn 17.7) is frontier-grade engineering — predicate-based retry + structured log canary. (4) Cost-cap soft/hard tier (80%/100%) with degrade-to-fast pattern. (5) `@cache` on `get_models()`. (6) UTC-date Redis key for cost counter — TTL handles daily reset for free. (7) Langfuse SDK v2 path defensive against v3+ accidental upgrade. (8) `provider_tag` derived from `model_id` slash convention. (9) Cost-tracker reflects the fallback model when fallback fires — accurate within gateway's known scope. |

**Phase 1.5 lift assignment:** **None** from this step. All KNOWN gaps deferred per existing memory notes; F3 surfaces as new memory note (Phase 3+ trigger, not Phase 1.5); F4 amends existing note (subgraph topology lift unblocks).

**Cross-references:**
- Base plan: lines 1616-1955 (Task 1.6)
- Memory notes referenced: `project_cost_cap_redis_only.md`, `project_agent_node_bypasses_gateway_fallback.md`, `project_agent_llm_cost_attribution_gap.md`, `project_embedding_cost_attribution_gap.md`, `project_groq_error_message_string_match_dependency.md`, `project_module_level_mem0_instantiation_smell.md` (cross-ref for discipline-applied)
- Memory notes saved at this step: `project_n_provider_fallback_deferral.md` (F3)
- Memory notes amended at this step: `project_subgraph_topology_for_phase3_or_4.md` (F4 cross-reference)

### Step 5 — Turn 6 — Memory layer (MemoryManager + Mem0Client + UserProfileManager + SessionManager)

**Overall rating:** Mid (engineering touches frontier within Mid foundation; multi-user gap is correctness-blocking for Phase 4 — sibling lift to Step 3 F1) — **Status:** final — sign-off 2026-05-25

**Scope:**
Turn 6 surface in current state. Surface originated at commit `dfc411c` (memory system - mem0, profile, manager, session). Audit captures live state as of HEAD `16dd266` + Step 4 close.

**References:**

| Surface | File / location |
|---|---|
| Memory orchestrator | `backend/app/memory/manager.py` (123 lines) — per-turn build_context + persist_turn + recall + thread_summary + facade methods |
| Mem0 wrapper | `backend/app/memory/mem0_client.py` (145 lines) — **AsyncMemory v2** directly (no thread-pool punt) + `_mem0_config()` helper + `USER_ID="master"` class const |
| UserProfile CRUD | `backend/app/memory/user_profile.py` (102 lines) — single-row design explicitly documented as intentional |
| Session analytics | `backend/app/memory/session.py` (80 lines) — read-only adapter over LangGraph checkpointer |

Base plan: Task 1.7 (lines 1961-2323). Memory notes consulted: `project_mem0_silent_drop_on_rpm.md`, `project_mem0_contamination_test_residue.md`, `project_module_level_mem0_instantiation_smell.md`.

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | No classifier |
| Flat string output | N/A | Returns structured dicts |
| One-line tool description | N/A | No tools |
| Single-item interface | N/A | search() returns batch |
| Module-level instantiation triggering I/O | Indirect, KNOWN | `wire_litellm_providers()` at module top is env-var only (no I/O). The instantiation chain `Mem0Client.__init__` → `AsyncMemory.from_config()` → `OllamaEmbedder._ensure_model_exists()` triggers Ollama HTTP at **caller-side instantiation**, not memory-layer module import. Already memory-noted in `project_module_level_mem0_instantiation_smell.md` (responder.py:4 is the bad caller). |
| Logging-via-omission | N/A | Mem0Client logs init; manager.py has no logging (acceptable for orchestrator) |
| **Sync bypass of cost-tracking / observability gateways** | **THIRD bypass surface found** | Mem0's `provider: "litellm"` extraction LLM config means Mem0 calls LiteLLM directly — bypassing `LLMGateway.complete()`. No cost-cap check, no `LLMUsageLog` write. This is a third bypass surface alongside agent_node (memory-noted) and embedding (memory-noted). Mem0 extraction uses Gemini Flash Lite (paid tier per `project_mem0_extraction_gemini_swap.md`), so unlike embedding it has real (but tiny) untracked cost — ~$0.0005 per `persist_turn()` × ~100 turns/day = ~$0.05/day. |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | No prompts |
| Plan-verbatim task order | N/A | Foundation layer |
| **Documentation drift from code** | **None — FRONTIER discipline observed** | mem0_client.py:7-14 explicitly documents "Mem0 v2 deviations from the implementation plan" — 3 concrete plan-vs-code deviations called out inline. Anti-drift practice. user_profile.py:14-15 explicitly documents single-row design as intentional with "multi-tenant comes later, if ever." Deferred concerns documented AT the code surface. |
| Verification axis mismatch | N/A | No runtime claims |
| Single-shot prompt | N/A | Mem0 extraction is single-shot but that's Mem0-internal |
| Speculative complexity dressed as future-proofing | None | All code earns its keep |

**Comparison target:**
LangChain's `BaseMemory` + LangSmith integration is comparable shape. Mem0 itself is a frontier-grade memory framework. Our wrapping pattern (async-first, config-helper extraction, async memory tier orchestrator) matches strong-shop conventions. The frontier-execution touches (v2-deviation documentation inline, defensive `get_always_on` defaults, Mem0 indexing on profile mutations) exceed plan-verbatim.

**Three-hats tension surfaced:**

- **Architect** wants single MemoryManager surface for all memory tiers. Wins on cleanness. Loses on multi-user — `UserProfile` single-row + `Mem0Client.USER_ID="master"` are both single-master assumptions. Tension resolved with two pending Phase 1.5b lifts (Step 3's F1 schema + this step's F1 Mem0 USER_ID).
- **Engineer** wants async-throughout (no thread-pool punts). Wins by adopting Mem0 v2 AsyncMemory directly (deviation from plan-verbatim's `asyncio.to_thread` pattern). Loses on Mem0 cost-tracking gap — Mem0 extraction goes through LiteLLM but bypasses the gateway. Tension: clean async vs cost-tracking completeness. Resolved in favor of clean async; cost gap memory-noted (F4 below extends existing note).
- **AI-ML engineer** wants memory tiers explicitly separated and routed correctly. Wins on clean separation. Bonus pattern: on-demand profile sections indexed into Mem0 with `metadata={"kind": "profile"}` — semantic search surfaces profile sections naturally without separate profile-search code path. **Frontier-clean.**

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **Mem0Client `USER_ID = "master"` hardcoded** at `mem0_client.py:89`. Used in every add/search/get_all as filter scope. Phase 4 multi-user blocker. | **Proposed Phase 1.5 lift entry** (parallel to Step 3's F1 schema-multi-user lift). Wrap approach (parameterize methods with `user_id`), NOT factory approach — see lift entry below for design fork rationale. Sub-phase letter expected `b`; position number assigned at the consolidation step. |
| F2 | **Mem0 v2 deviations explicitly documented in code (anti-drift discipline)** — `mem0_client.py:7-14` lists 3 plan-vs-code deviations inline. | **No-action positive finding + elevated to discipline-note exemplar.** Amended `feedback_frontier_grade_discipline.md` at this step with a new "Worked examples of anti-drift discipline applied in existing code" section cross-referencing this code surface. Makes the discipline note's "Documentation drift from code" smell have a concrete counter-example. |
| F3 | **UserProfileManager single-row design explicitly acknowledges multi-user deferral** — `user_profile.py:14-15` "Multi-tenant comes later, if ever." | **No-action positive finding + elevated to discipline-note exemplar.** Same amendment as F2 — cross-referenced in the new discipline-note section. Deferred concerns documented AT the code surface is the pattern being elevated. |
| F4 | **Mem0 extraction LLM bypasses cost tracker — THIRD bypass surface.** `provider: "litellm"` in Mem0 config bypasses `LLMGateway.complete()`. Cost: ~$0.05/day untracked. | **Amended existing `project_agent_llm_cost_attribution_gap.md`** with a new "Sibling bypass surfaces (architectural pattern)" section listing all three surfaces (agent_node + embedding + Mem0 extraction). Keeps cost-attribution gap landscape unified in one note for Phase 4 dashboard scoping. Not Phase 1.5. |
| F5 | **Mem0 silent drop on RPM** — already memory-noted in `project_mem0_silent_drop_on_rpm.md`. Mitigated by paid-tier Gemini key. | **Reaffirm existing memory note.** |
| F6 | **Mem0 contamination from test residue + debug chatter** — already memory-noted in `project_mem0_contamination_test_residue.md`. Cleaned Turn 17.6. | **Reaffirm existing memory note.** Turn 26.5's consolidation work is where ongoing defense lives. |
| F7 | **Module-level Mem0 instantiation smell** — already memory-noted in `project_module_level_mem0_instantiation_smell.md`. Smell is at caller side (responder.py:4), not memory layer itself. | **Reaffirm existing memory note.** Lift at next email-path touch (Turn 17.8 candidate). |
| F8 | **Frontier-grade engineering touches.** | **No-action positive finding:** (1) AsyncMemory directly (v2 SDK) — better than plan-verbatim. (2) v2 deviations documented inline (anti-drift; elevated via F2). (3) `get_always_on` never returns None (defensive default). (4) `recall()` over-fetches when filtering for accurate top-k. (5) SessionManager isolates LangGraph internals from dashboard callers. (6) Mem0 config extracted to `_mem0_config()` helper. (7) `wire_litellm_providers()` re-called at memory-layer module top — defensive against load-order surprises. (8) `metadata={"kind": "profile", "key": key}` on on-demand profile indexing into Mem0 — clever pattern; semantic search surfaces profile sections naturally without separate profile-search code path. |

**Phase 1.5 lift assignment:** F1 → see Phase 1.5 section below (status `proposed`). Sibling to Step 3's F1; both Phase 1.5b at the consolidation step.

**Cross-references:**
- Base plan: lines 1961-2323 (Task 1.7)
- Memory notes referenced: `project_mem0_silent_drop_on_rpm.md`, `project_mem0_contamination_test_residue.md`, `project_module_level_mem0_instantiation_smell.md`, `project_mem0_extraction_gemini_swap.md`
- Memory notes amended at this step: `project_agent_llm_cost_attribution_gap.md` (F4 — Sibling bypass surfaces section), `feedback_frontier_grade_discipline.md` (F2 + F3 — anti-drift worked-examples section)
- Sibling Phase 1.5b lift: Step 3 F1 (schema multi-user readiness)

### Step 6 — Turn 7 — Prompts (KV-cache friendly) + Safety classifier

**Overall rating:** Mid (consistent with Steps 3-5; no new correctness-blocking gaps; engineering touches frontier within Mid foundation) — **Status:** final — sign-off 2026-05-25

**Scope:**
Turn 7 surface in current state. Surface originated at commit `3565c22` (prompts and safety classifier). Has grown beyond plan-verbatim with Turn 11 polish (No Hallucinated Actions section) + Turn 16.5 anti-fabrication + Turn 17.6's email_history_search safety map addition + Phase 3 search-provider swap (tavily added alongside brave). Audit captures live state as of HEAD `16dd266` + Step 5 close.

**References:**

| Surface | File / location |
|---|---|
| System prompt builder | `backend/app/agent/prompts.py` (159 lines) — stable prefix + tagged-block VOLATILE_TEMPLATE + alphabetical sort for cache stability + top-N caps |
| Safety classifier | `backend/app/agent/safety.py` (114 lines) — 4-level SafetyLevel + TOOL_SAFETY_MAP (20+ entries) + `_args_overrides` with explicit never-downgrade rule |

Base plan: Tasks 1.8 (lines 2325-2447), 1.9 (lines 2449-2514). Memory notes consulted: `project_email_responder_fabricates_content.md`, `project_no_hallucinated_actions.md` (referenced from SAFETY_DOCTRINE), Turn 17.9 close-out plan (base plan lines 9604-9608).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | 4-level SafetyLevel is correct shape for the domain |
| Flat string output | N/A | Structured enum / formatted prompt string |
| One-line tool description | N/A | No tool descriptions here |
| Single-item interface | N/A | `classify` is per-call (correct shape) |
| Module-level instantiation triggering I/O | None | prompts.py pure functions + constants; safety.py class + map (no I/O on import or instantiation) |
| **Logging-via-omission** | **Mild** | `_args_overrides` returns escalated SafetyLevel silently. Reading `audit_trail` alone, can't distinguish default-APPROVE from args-escalated-APPROVE. |
| Sync bypass of cost-tracking / observability | N/A | No LLM calls |
| **Tool-specific guidance in SAFETY_DOCTRINE** | **None — discipline applied** | SAFETY_DOCTRINE is all generic rules. The gmail_read/web_research/firecrawl_crawl mentions are examples (not per-tool guidance). Matches `feedback_tool_specific_guidance_in_descriptions.md`. |
| Plan-verbatim task order | N/A | Foundation layer |
| **Documentation drift from code** | **None — anti-drift baseline** | Both docstrings accurate vs code. Baseline no-drift state (distinct from Step 5's proactive-deviation-documentation exemplars). |
| Verification axis mismatch | N/A | No runtime claims |
| **Single-shot prompt where iterative reasoning would be frontier** | **Plan-noted gap** | SAFETY_DOCTRINE lacks think-before-act reasoning protocol scaffolding. Already Turn 17.9 close-out scope (base plan lines 9604-9608, Task `2.X-closeout-q`). |
| Speculative complexity dressed as future-proofing | None (defensible) | TOOL_SAFETY_MAP forward-declares Phase 3+4 tools. Defensive: explicit entries beat unknown-tool fallback. Registry only binds registered tools, so dead-code entries can't cause incorrect classification — they're stay-ahead-of-the-plan markers. |

**Comparison target:**
Closest references — Claude's tool-use system prompt patterns (tagged blocks for trust boundaries), OpenAI's function-calling safety wrappers (default-deny for unknown tools), Anthropic's published prompt-cache discipline (stable prefix + alphabetical bullet ordering). Live state matches strong-shop conventions; the **No Hallucinated Actions** section is a real frontier addition (load-bearing rule + concrete example + forbidden phrasings list).

**Three-hats tension surfaced:**

- **Architect** wants stable prefix + volatile suffix split for KV-cache. Wins on cost. Loses on prefix-volatility risk — `always_on_lines` alphabetical sort at prompts.py:124 is the architectural defense. Resolved with sort-then-render discipline.
- **Engineer** wants SafetyClassifier deterministic + auditable + impossible-to-downgrade. Wins on `_args_overrides` never-downgrade rule. Loses on observability — no logging when args-override fires. Tension resolved in favor of deterministic-simple; observability gap addressed by F2 disposition.
- **AI-ML engineer** wants SAFETY_DOCTRINE load-bearingly prevent hallucinated actions. Wins on "No Hallucinated Actions" section. Loses on missing think-before-act scaffolding — already Turn 17.9 close-out scope.

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **SAFETY_DOCTRINE reasoning-protocol gap** — no think-before-act scaffolding. | **Reaffirm planned Turn 17.9 close-out** (base plan lines 9604-9608, Task `2.X-closeout-q`). Not Phase 1.5. |
| F2 | **No logging when SafetyClassifier `_args_overrides` escalates.** Reading `audit_trail` alone, can't distinguish default-APPROVE from args-escalated-APPROVE. | **Amended base plan Turn 17.9 close-out scope** with new task `2.X-closeout-q2` (~3 LOC structlog warning on `_args_overrides` escalation). Same safety-layer scope intent as Turn 17.9's other tasks. Keeps related safety-layer work together in one batch commit vs orphan note. |
| F3 | **`always_on_lines` alphabetical sort** for cache stability (prompts.py:124). | **No-action positive finding** — anti-cache-invalidation discipline beyond plan-verbatim. |
| F4 | **Tagged blocks in VOLATILE_TEMPLATE** (`<on_demand>`, `<memories>`, `<context>`). | **No-action positive finding** — trust boundaries at prompt structure level; exceeds plan-verbatim's plain markdown. |
| F5 | **TOOL_SAFETY_MAP forward-declares Phase 3+4 tools.** | **No-action positive finding.** Defensive forward-declaration; explicit entries beat unknown-tool fallback for grep-discoverable intent. Different discipline pattern from anti-drift; NOT elevated to exemplar list. |
| F6 | **"No Hallucinated Actions" SAFETY_DOCTRINE section** — load-bearing rule + concrete example + forbidden phrasings list (Turn 11 polish + Turn 16.5 anti-fabrication baked in). | **No-action positive finding** — Frontier discipline. |
| F7 | **Anti-drift baseline observed** in both prompts.py and safety.py docstrings — accurate, no drift. | **No-action positive finding.** Baseline no-drift (distinct from Step 5's proactive-deviation-documentation exemplars). NOT elevated to discipline-note exemplar list — the exemplar list is for proactive deviation-documentation, not baseline no-drift. |

**Phase 1.5 lift assignment:** **None** from this step. F1 + F2 both land in Turn 17.9 close-out batch (Phase-2-Week-6 work, not Phase 1.5 foundation lift).

**Cross-references:**
- Base plan: lines 2325-2447 (Task 1.8 prompts), lines 2449-2514 (Task 1.9 safety), lines 9604-9608 (Turn 17.9 close-out)
- Base plan amended at this step: Turn 17.9 task list extended with `2.X-closeout-q2` (SafetyClassifier args-override observability)
- Memory notes referenced: `project_email_responder_fabricates_content.md`, `project_no_hallucinated_actions.md`, `feedback_tool_specific_guidance_in_descriptions.md` (discipline confirmed)
- Memory notes amended at this step: none (F2 went to base-plan Turn 17.9 amendment instead of new note)

### Step 7 — Turns 8+9 grouped — Agent core (AgentState + nodes + sanitizer + rate_limits + graph + runner + context)

**Overall rating:** Mid (consistent with Steps 3-6; frontier-execution touches substantial but don't override known correctness-blocking gaps from prior steps + the deeper-lens-pass surfaced 2 new gaps) — **Status:** final — sign-off 2026-05-25

**Scope:**
Agent core surface in current state — the load-bearing layer for every master query. 7 files, 1315 LOC total. Surface originated at Turn 8 (commit `f3acb09` — agent state + sanitizer + rate_limits + graph) + Turn 9 (commit family for nodes + runner + context). Has accumulated substantial additions across later turns: tool_executor single-call-per-invocation discipline (Turn 17.5 resume-safety lift), `_build_chat_model` rebuild to use FallbackChatLLM (Turn 17.7), `_args_overrides` integration (Turn 17.9 close-out scope pending). Audit captures live state as of HEAD `16dd266` + Step 6 close.

**References:**

| Surface | File / location |
|---|---|
| AgentState TypedDict | `backend/app/agent/state.py` (42 lines) — `add_messages` reducer for messages, default replace for other fields, per-turn metadata + final_response |
| 4 graph nodes + 2 routing functions | `backend/app/agent/nodes.py` (525 lines) — memory_load_node + agent_node (FallbackChatLLM-wrapped, bind_tools per turn) + tool_executor_node (single tool call per invocation for resume safety) + persist_node + should_continue + should_continue_tools + `_archive_tool_result` writer + `_log_audit` + module-level `memory = MemoryManager()` + `safety = SafetyClassifier()` singletons |
| Prompt-injection sandbox | `backend/app/agent/sanitizer.py` (77 lines) — `sanitize_tool_result()` returns (sanitized_text, archived_full); tagged blocks `<tool_output trust="untrusted">` + TOOL_RESULT_PREAMBLE + truncation+archive |
| Per-turn rate limiter | `backend/app/agent/rate_limits.py` (145 lines) — `RateLimiter` with `check_and_increment_tool` (Redis HINCRBY per-tool) + `check_turn_rate` (Redis ZSET sliding window per-hour) + `_log_block` writing RateLimitEvent rows + TOOL_SPECIFIC_LIMITS_PER_TURN dict; docstring explicitly disambiguates from `app/security/rate_limiter.py` |
| StateGraph wiring + checkpointer | `backend/app/agent/graph.py` (131 lines) — `init_checkpointer` (idempotent) + `close_checkpointer` + `build_graph()` topology: START → memory_load → agent → [should_continue: tool_executor OR persist] with [should_continue_tools] loop in tool_executor |
| Public entry (run_turn + resume_turn) | `backend/app/agent/runner.py` (357 lines) — `graph()` singleton + `run_turn` + `resume_turn` + `_build_envelope` (TurnEnvelope shape: thread_id / status / response / messages / interrupt / trace_id / usage) + `_existing_message_count` slice boundary + `_aggregate_usage` via `litellm.completion_cost` + `_safe_trace_id` defensive across Langfuse SDK versions |
| Per-turn context facade | `backend/app/agent/context.py` (38 lines) — thin facade `build_turn_context()` over MemoryManager for dashboard/debug callers; module-level `_memory = MemoryManager()` singleton |

Base plan: Task 1.10 subtasks 10.1-10.7 (lines 2536-3271). Memory notes consulted: `project_subgraph_topology_for_phase3_or_4.md`, `project_async_state_rebind_pattern.md`, `project_open_weights_tool_schema_and_conversation_poisoning.md`, `project_agent_node_bypasses_gateway_fallback.md`, `project_agent_llm_cost_attribution_gap.md`, `project_module_level_mem0_instantiation_smell.md`, `project_no_hallucinated_actions.md`.

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | No classifier surface here |
| Flat string output | N/A | Returns structured TurnEnvelope dict |
| One-line tool description | N/A | No tools defined here |
| Single-item interface where batch frontier | **DELIBERATE inversion** | `tool_executor_node` processes ONE tool call per invocation. Per docstring (`nodes.py:17-32`) + `project_open_weights_tool_schema_and_conversation_poisoning.md` context: LangGraph's `interrupt()` doesn't commit partial state, so processing multiple calls in a loop would re-execute earlier ones on resume. Frontier-correct given the constraint. **Not a smell — design discipline.** |
| **Module-level instantiation triggering I/O** | **PROPAGATED smell (2 NEW sites)** | `nodes.py:68` `memory = MemoryManager()` and `context.py:19` `_memory = MemoryManager()` both trigger the Ollama-HTTP chain at instantiation. Same smell pattern as `responder.py:4`. Already memory-noted via `project_module_level_mem0_instantiation_smell.md`. **This step confirms the smell propagates to 3 call sites total** (responder + nodes + context). Existing note amended at this step to enumerate all 3. The lazy-init refactor (Turn 17.8 candidate per existing note) closes all 3 surfaces in one pass. |
| Logging-via-omission | N/A | runner has `turn_complete` log; nodes has tool execution logs; rate_limits writes RateLimitEvent + structlog event |
| **Sync bypass of cost-tracking / observability** | **KNOWN — reaffirmed at the bypass site** | `agent_node._build_chat_model` constructs `ChatLiteLLM` directly via `bind_tools()`, wraps in `FallbackChatLLM`. Already memory-noted as the primary bypass surface in the unified `project_agent_llm_cost_attribution_gap.md` (3 bypass surfaces section). |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | Audited in Step 6 |
| Plan-verbatim task order | N/A | Foundation layer |
| **Documentation drift from code** | **None across ALL 7 files — anti-drift baseline** | nodes.py docstring (topology + resume safety detail) verified accurate against `tool_executor_node` + `should_continue_tools` implementation. graph.py + runner.py + state.py + sanitizer.py + rate_limits.py + context.py docstrings all verified accurate. Baseline no-drift consistent with Steps 5/6. |
| Verification axis mismatch | N/A | No runtime claims at this layer |
| **Single-shot prompt where iterative reasoning would be frontier** | Plan-noted + topology-deferred | SAFETY_DOCTRINE think-before-act is Turn 17.9 close-out scope (`2.X-closeout-q`). Explicit reflection/verification graph nodes are deferred per `project_subgraph_topology_for_phase3_or_4.md`. |
| Speculative complexity dressed as future-proofing | None | `_safe_trace_id` defensive paths against langfuse SDK version drift are justified inline. `_aggregate_usage` best-effort cost via `litellm.completion_cost` is acknowledged as redundant with LLMUsageLog and justified ("the /costs endpoint reconciles from LLMUsageLog rows once the persistence callback has flushed"). |

**Comparison target:**

LangGraph's own example agents + Anthropic's MCP agent examples are the closest comparable frontier shapes for our pattern (single-graph + AsyncPostgresSaver checkpointer + interrupt-based HITL). Live state matches strong-shop LangGraph conventions. The single-call-per-invocation discipline in `tool_executor_node` is frontier-correct given LangGraph's interrupt() semantics. Cursor / Claude Code reflection-node patterns are out of scope for the current single-graph topology (deferred to subgraph topology lift per existing memory note).

**Deeper comparison-target pass per surface (lens-nudge applied — 2-3 frontier anchors each + "what would each ship?"):**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| `state.py` (AgentState) | LangGraph examples; AutoGen multi-agent; Anthropic prompt-cache patterns | No `cache_id` field for prompt-cache key threading (premature — Claude not primary today); no `agent_id` (deferred per subgraph topology note). **Self-dismiss both.** |
| `nodes.py` (4-node topology) | LangGraph examples; Claude Code reflection nodes; AutoGen planner/executor; Cursor agents | No explicit reflection node before tool execution; no verification node after. Both deferred — subgraph topology lift is the architectural unlock; Turn 17.9 prompt-level reasoning protocol is the lighter approach. **Self-dismiss as planned deferrals.** |
| `sanitizer.py` | Anthropic tagged-block patterns (match); Microsoft PromptShield; OpenAI structured output | **C1: No content-classification layer** running untrusted tool results through jailbreak-detection LLM before injection (PromptShield-style). Cost: 1 extra LLM call per tool result. Self-dismiss as premature — defense-in-depth via prompt rules + tagged blocks is the standard-shop approach. **C2: No tool to fetch archived tool_results** from `[archived:<id>]` markers — agent sees the marker but has no way to retrieve full content. **Verified via grep — real gap. Surfaced as F5.** |
| `rate_limits.py` | Sliding window (match); token-bucket; leaky-bucket; GitHub adaptive | Token-bucket / adaptive patterns would add burst tolerance + pre-cap slowdown. Both **self-dismiss as premature** for single-master. |
| `graph.py` | LangGraph patterns (match); supervisor multi-graph; hierarchical agents | Multi-graph subgraph topology already memory-noted as deferred per `project_subgraph_topology_for_phase3_or_4.md`. **No new candidate.** |
| `runner.py` | OpenAI Agents SDK runner; LangChain AgentExecutor; Anthropic Claude SDK | **C3: No `stop_reason` granularity beyond status.** TurnEnvelope's `status` is complete/interrupted/error — doesn't distinguish "natural end" from "tool budget hit" from "rate-limit" from "cost-cap." Frontier observability shape (Claude SDK has `stop_reason: end_turn / max_tokens / tool_use / etc.`). **Surfaced as F6.** |
| `context.py` | Trivial facade | Nothing material |

Deeper lens result: 5 candidates surfaced (state×2, nodes×2, sanitizer×2, rate_limits×2, runner×1). 4 self-dismissed as premature/deferred-already. **2 net-new gaps surfaced (F5 + F6)** that the standard checklist scan would have missed.

**Three-hats tension surfaced:**

- **Architect** wants single linear graph for Phase 2 simplicity. Wins on cleanness. Loses on Phase 3 query-type divergence (already memory-noted with subgraph topology lift as the architectural answer). Tension resolved with deferred lift.
- **Engineer** wants `tool_executor_node` to process exactly ONE tool call per invocation for resume safety. Wins on idempotency (each invocation atomically committed; no double-execution on resume). Loses on latency — N tool calls in an AIMessage = N graph node invocations + N checkpoint writes vs 1-and-done. Tension resolved in favor of correctness; latency cost acceptable at current tool-count-per-turn.
- **AI-ML engineer** wants reflection + verification nodes for multi-tool synthesis quality (more deliberate tool selection + more reliable synthesis). Loses on graph complexity + latency. Tension resolved with prompt-level scaffolding (Turn 17.9 close-out `2.X-closeout-q`) + subgraph topology deferral.

All three tensions surfaced — discipline firing.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **Module-level Mem0 instantiation smell propagates to 3 call sites at this step** — `responder.py:4` (originally memory-noted Turn 18) + `nodes.py:68` (newly identified) + `context.py:19` (newly identified). All trigger the Ollama-HTTP chain at instantiation. | **Amended existing `project_module_level_mem0_instantiation_smell.md`** to enumerate all 3 call sites. Lazy-init refactor closes all 3 surfaces in one pass. MEMORY.md ledger entry updated. |
| F2 | **agent_node bypass + cost-tracking gap** — `_build_chat_model` constructs ChatLiteLLM directly via `bind_tools()`, wrapped in FallbackChatLLM. Already memory-noted in the unified cost-attribution note. | **Reaffirm existing deferral.** No Phase 1.5 lift. |
| F3 | **One tool call per `tool_executor_node` invocation — DELIBERATE for resume safety.** | **No-action positive finding** — frontier-correct given LangGraph interrupt() constraint; documented rationale at nodes.py:17-32 + cross-reference to test_resume_dedup. |
| F4 | **`_build_chat_model` per turn** — instantiates ChatLiteLLM primary + fallback fresh each call. Per docstring "cheap; config objects, not heavy state." | **No-action.** Acceptable given dynamic top-k tool selection makes per-(tool_set_signature) caching complex. |
| F5 | **No tool to fetch archived tool_results.** Verified via grep at audit-write time: `ToolResult` model exists (db/models.py:227); writer side works (nodes.py:374 `_archive_tool_result`); marker injection works (nodes.py:380 `[archived:<archive_id>]`); **agent-callable reader side absent** across all registered tools (builtin_memory.py, calendar_tool.py, email_history.py, gmail_send.py). | **NEW memory note saved at this step:** `project_archived_tool_result_no_fetch_path.md`. Trigger: Phase 3 research agent (Turn 24) ships large web-scrape results, OR master-observable truncation complaint, OR Phase 3 RAG citation work. Fix: ~30-50 LOC add `fetch_archived_result(archive_id)` tool. Not Phase 1.5 — Phase-3-triggered. |
| F6 | **No `stop_reason` granularity in TurnEnvelope.** `status` is `complete | interrupted | error` — doesn't distinguish natural-end / tool-budget-hit / rate-limit / cost-cap. Frontier observability shape (Claude SDK `stop_reason`). | **Amended base plan Turn 17.9 close-out scope** with new task `2.X-closeout-q3` (TurnEnvelope stop_reason granularity, ~5 LOC structured-output change). Same Phase-4-dashboard-observability scope intent as `q` (reasoning protocol) + `q2` (args-override observability). Pattern forming: Turn 17.9 close-out has become the umbrella for "frontier-lens observability gaps for Phase 4 dashboard readiness." Keeps related work in one batch commit vs orphan note. |
| F7 | **Anti-drift baseline observed** in all 7 file docstrings — accurate, no drift. | **No-action positive finding.** Baseline no-drift across the layer; consistent with Steps 5/6. NOT elevated to discipline-note exemplar (the exemplar list is for proactive-deviation-documentation, not baseline no-drift). |
**Phase 1.5 lift assignment:** **None** from this step. F1 amends existing memory note (refactor scope was already documented). F2 reaffirms existing deferral. F5 saved as new Phase-3-triggered memory note. F6 lands in Turn 17.9 close-out batch (Phase-2-Week-6 work, not Phase 1.5 foundation lift).

_Engineering touches at this surface: 9 distinct frontier-execution patterns observed (single-call-per-invocation tool_executor with explicit resume-safety rationale; should_continue_tools walk-back; cheap-slice _existing_message_count; defensive _safe_trace_id; canonical TurnEnvelope shape; best-effort _aggregate_usage; idempotent init_checkpointer; tool_calls_this_turn first-of-turn discriminator; rate_limits.py docstring disambiguation from app/security/rate_limiter.py) — cited inline at the file:line references in the smells scan + deeper-lens pass above. Not enumerated as a numbered finding to keep F-numbers reserved for actionable items (reviewer methodology note 2026-06-01)._

**Reviewer corrections (2026-06-01):** F1 site count revised 3 → 5 after reviewer Steps 7–9 re-grep caught two later-discovered sites — `builtin_memory.py:20` (added at Step 8) and `api/memory.py:20` (added by reviewer pass; api/ surface wasn't audited until Step 10/11). Refactor scope at memory-note time = 5. See `project_module_level_mem0_instantiation_smell.md` for live state.

**Methodology note:** Deeper lens nudge (per Step 6 close instruction — push comparison-target pass deeper with 2-3 frontier anchors per surface + explicit "what would each anchor ship for this surface that we don't have today?") produced 2 net-new candidates (F5 + F6) that the standard checklist scan would have missed. F5 was a real fetch-path gap verified via grep; F6 was a Phase-4-dashboard-observability granularity gap. Self-dismissal rate on deeper-lens candidates was 4-of-5 in this step (premature / already-deferred), which itself is the expected ratio — the deeper pass earns its keep precisely because it surfaces candidates that *might* be premature, then forces explicit dismissal-with-rationale rather than checklist-blind oversight. Proof-of-concept for the lens nudge; same discipline applies for Step 8 onward.

**Cross-references:**
- Base plan: lines 2536-3271 (Task 1.10 subtasks 10.1-10.7)
- Base plan amended at this step: Turn 17.9 task list extended with `2.X-closeout-q3` (TurnEnvelope stop_reason granularity)
- Memory notes saved at this step: `project_archived_tool_result_no_fetch_path.md` (F5)
- Memory notes amended at this step: `project_module_level_mem0_instantiation_smell.md` (F1 — 3 call sites enumeration + name/description/MEMORY.md updates)
- Memory notes referenced (existing, reaffirmed): `project_subgraph_topology_for_phase3_or_4.md`, `project_async_state_rebind_pattern.md`, `project_open_weights_tool_schema_and_conversation_poisoning.md`, `project_agent_node_bypasses_gateway_fallback.md`, `project_agent_llm_cost_attribution_gap.md`, `project_no_hallucinated_actions.md`

### Step 8 — Turn 10 — Tool registry (dynamic embedding-based selection) + builtin_memory tool

**Overall rating:** Mid-to-Frontier (dynamic top-K embedding-based tool selection is a genuine frontier pattern most agent registries lack; MCP-readiness is forward-looking not Phase-2-blocking; lifts cleanly to Frontier when MCP-readiness lift F3 ships) — **Status:** final — sign-off 2026-05-25

**Scope:**
Tool registry + memory_search tool + registration entry-point surface in current state. Surface originated at commit family for Turn 10 (Task 1.11). Has accumulated additions across later turns: Turn 16 added calendar + gmail_send + email_history tool registrations to `__init__.py`; Turn 17.6 sharpened memory_search description with cross-reference discipline (`"Does NOT search email content; use email_history_search"`). Audit captures live state as of HEAD `16dd266` + Step 7 close.

**References:**

| Surface | File / location |
|---|---|
| Tool registry singleton | `backend/app/agent/tools/registry.py` (248 lines) — `ToolRegistry` class + `_ToolEntry` namedtuple + dynamic embedding-based top-K cosine selection over `tool_embeddings` table + `always_loaded` bypass + idempotent `index_all_tools` (skip-if-unchanged) + embedding-model swap detection + `_embed_text` defensive on response shape + module-level `tool_registry` singleton |
| memory_search builtin tool | `backend/app/agent/tools/builtin_memory.py` (61 lines) — `always_loaded=True` Mem0 search wrapper with score-formatted output + "Does NOT search email content; use email_history_search" cross-reference + Phase-1+ docstring (in-place fix landed at audit-write time) |
| Registration entry point | `backend/app/agent/tools/__init__.py` (62 lines) — `register_all_tools()` lifespan-callable + 4 active tool imports (memory + calendar + gmail_send + email_history) + 7 commented Phase 3/4 stubs |

Base plan: Task 1.11 (lines 3322-3577). Memory notes consulted: `project_embedding_cost_attribution_gap.md`, `project_cross_source_recall_pattern.md`, `project_module_level_mem0_instantiation_smell.md` (just-amended Step 7), `feedback_tool_specific_guidance_in_descriptions.md`, `project_trivial_message_over_invocation.md`, `project_agent_llm_cost_attribution_gap.md`.

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | Returns LangChain BaseTool objects |
| **One-line tool description** | **None — discipline applied** | memory_search description (builtin_memory.py:51-58) is multi-line, includes "Does NOT search email content" cross-reference, includes "Use for:" examples. Matches `feedback_tool_specific_guidance_in_descriptions.md` + `project_cross_source_recall_pattern.md` pattern established Turn 17.6. |
| Single-item interface where batch frontier | Mild | `_embed_text` takes single text; `index_all_tools` calls it once per tool (sequential await). Could batch via `litellm.aembedding(input=[multi])`. But: runs once at startup; batching saves seconds; per-tool loop also enables per-tool skip-if-unchanged logic. Acceptable. |
| **Module-level instantiation triggering I/O** | **PROPAGATED smell — 4TH SITE discovered at this step (later revised to 5)** | `builtin_memory.py:20` `_memory = MemoryManager()` triggers the same Ollama-HTTP chain. Step 7 amended the existing note to enumerate 3 sites (responder + nodes + context); **Step 8 finds a 4th (builtin_memory). Site count later revised to 5 after reviewer re-grep on 2026-06-01 caught `api/memory.py:20`.** The lazy-init refactor scope extends to 5 surfaces. Existing note + MEMORY.md ledger entry re-amended at this step (and again on 2026-06-01). Also: `registry.py:40` calls `wire_litellm_providers()` at module top — per Step 4 audit this is "env-var only, no I/O" so fine. |
| Logging-via-omission | N/A | tool_registered + tool_embeddings_indexed + dynamic_tools_selected log events present |
| **Sync bypass of cost-tracking / observability** | **KNOWN — reaffirmed at the bypass site** | `_embed_text` calls `litellm.aembedding` directly. Already memory-noted as one of 3 bypass surfaces in unified `project_agent_llm_cost_attribution_gap.md` + specifically tracked in `project_embedding_cost_attribution_gap.md`. |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | Audited in Step 6 |
| Plan-verbatim task order | N/A | Foundation layer |
| **Documentation drift from code** | **Mild drift — in-place fix landed at audit-write time** | builtin_memory.py:4 docstring said *"The only tool registered in Phase 1."* True at Phase 1; drift now that Phase 2 has added calendar + gmail_send + email_history via `__init__.py:34-41`. Mild — informational, not load-bearing. **Fixed in-place at audit-write time** to *"First tool registered (Phase 1); Phase 2+ tools register alongside via __init__.py."* All other docstrings (registry.py, __init__.py) verified accurate. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | No prompts at this layer |
| Speculative complexity | None | `_embed_text` defensive on response shape (lines 242-244) — justified inline ("LiteLLM versions differ on whether `response.data[0]` is a dict or an object with `.embedding`") |

**Deeper comparison-target pass per surface (lens-nudge applied):**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| `registry.py` | (1) Anthropic MCP (Model Context Protocol); (2) LangChain tool registry (match); (3) OpenAI Assistants API tool registry | **C1: No MCP exportability or MCP server endpoint** — tools are in-process Python objects; not discoverable by external MCP clients (Claude Desktop / Cursor / future multi-agent setups). **Confirms Explore-agent's earlier finding. Real frontier-gap. Surfaced as F3 → split into 2 sequential Phase 1.5a lifts** (descriptors + server endpoint; see lift entries below). **C2: No tool output schema** (all return strings; MCP defines both input and output). Self-dismiss — falls out from F3 descriptor lift naturally. **C3: No per-tool execution timeouts** — slow/hanging tool blocks agent indefinitely. **Surfaced as F5 → memory note `project_per_tool_execution_timeout_gap.md`.** **C4: No query-embedding cache** — same query → same embedding every turn. Self-dismiss — query embedding via Ollama is ~50-100ms; cheap. **C5: No hybrid retrieval for tool selection** — pure cosine on bge-m3. Self-dismiss — overkill for tool-selection scale (~30 tools). |
| `builtin_memory.py` | (1) LangChain memory tools; (2) Mem0 example agent integrations; (3) Claude Projects unified project knowledge | **C6: Cross-source recall pattern coupling** (memory_search vs email_history_search split — Claude Projects has unified knowledge surface). Already memory-noted as `project_cross_source_recall_pattern.md`. **Reaffirm.** **C7: No metadata filter parameter** (Mem0 supports `filters={"kind": ...}`; we don't expose it). Self-dismiss — speculative, no current need. **C8: No score threshold** (top_k=5 returns 5 regardless of relevance score). Mild quality concern; scores ARE in output as `(0.42)` for agent to read; self-dismiss as low-impact. |
| `__init__.py` | Any tool-loader pattern | Nothing material |

Deeper lens result: 8 candidates surfaced. **2 net-new gaps confirmed (F3 MCP-readiness — aligned with user-anticipated Phase 1.5a; F5 per-tool timeouts — net-new from deeper lens).** F6/F7 already-tracked. 5 self-dismissed.

**Comparison target:**

LangChain's tool registry + OpenAI Assistants API tool registry are the closest comparable shapes. **The dynamic embedding-based top-K selection is a genuine frontier touch** — most agent registries are static (all tools always bound). Frontier comparables: Cursor's tool selection per query (also dynamic) + AutoGen's tool dispatching (more static). The MCP gap is forward-looking: Anthropic + Cursor + Claude Desktop + the emerging multi-agent ecosystem are converging on MCP as the cross-process tool protocol.

**Three-hats tension surfaced:**

- **Architect** wants single tool registry as authoritative tool surface. Wins on cleanness + dynamic top-K avoiding LLM tool-list bloat. Loses on MCP-isolation: tools are in-process only, not externally addressable. Tension resolved with Phase 1.5a lift split (F3 descriptors + server, two sequential).
- **Engineer** wants `index_all_tools` to skip re-embedding unchanged descriptions for cheap restarts. Wins on startup latency (~0ms if no descriptions changed vs ~1-2s if all re-embed). Loses on slight code complexity (3 branches: existing+unchanged-skip, existing+changed-rewrite, missing+add). Resolved in favor of skip-discipline; complexity acceptable.
- **AI-ML engineer** wants top-K cosine selection over BGE-M3 embeddings as the dynamic tool router. Wins on scaling to N tools without LLM context bloat. Loses on cold-start (empty registry short-circuit) + on MCP-correctness (embedding-based selection is INTERNAL; MCP clients would want all tools listed). Resolved with empty-rankable short-circuit at registry.py:188-192 + Phase 1.5a lifts above the embedding selector (selector remains internal; descriptors export at MCP layer is additive).

All three tensions surfaced — discipline firing.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **Module-level Mem0 instantiation smell — 4TH call site discovered at this step** (`builtin_memory.py:20` — line was :19 at finding time, shifted to :20 after the in-place F4 docstring fix below). Same pattern as Step 7's 3 sites. | **Amended `project_module_level_mem0_instantiation_smell.md` AGAIN at this step** to enumerate 4 sites (responder + nodes + context + builtin_memory). Name + description + body + MEMORY.md ledger all updated. The lazy-init refactor scope extends to 4 surfaces (~20-30 LOC across the 4 files + shared `get_memory()` accessor). |
| F2 | **`_embed_text` bypasses LLM gateway** (litellm.aembedding direct). Already memory-noted as embedding bypass surface. | **Reaffirm existing deferral.** No Phase 1.5 lift. |
| F3 | **MCP-readiness lift candidate** — tools not exportable as MCP tool descriptors; no MCP server endpoint. Confirms user-expected Phase 1.5a candidate. | **Proposed as TWO sequential Phase 1.5a lifts** (see Phase 1.5 section below): (a) Phase 1.5a-N — Tool descriptor export (~30-50 LOC, no external coupling); (b) Phase 1.5a-N+1 — MCP server endpoint (~100-150 LOC, depends on descriptors lift + Phase-4-auth-shape decision). Split chosen over bundled per `feedback_architectural_units_land_complete.md` "split at stable interface boundaries" rule — MCP descriptor format IS a stable interface (spec-defined by Anthropic). Server endpoint's auth-shape question is Phase-4-coupled; descriptors-only has no such coupling and is useful WITHOUT the server (internal multi-agent handoffs, doc generation, spec compliance testing). |
| F4 | **builtin_memory.py:4 docstring drift** — "The only tool registered in Phase 1" no longer true (Phase 2 added 3 more tools via __init__.py). | **In-place fix landed at audit-write time.** Replaced with "First tool registered (Phase 1); Phase 2+ tools register alongside via __init__.py." Mirror of Step 2's .env.example Cloudflare reframe + Step 5's anti-drift discipline. |
| F5 | **(Deeper lens C3) No per-tool execution timeouts.** `ToolRegistry.execute()` calls `entry.tool.ainvoke(args)` with no `asyncio.wait_for` wrap. Slow/hanging tool blocks agent indefinitely. | **NEW memory note saved at this step:** `project_per_tool_execution_timeout_gap.md`. Trigger: Phase 3+ browser/firecrawl/research tools with real timeout risk OR Phase 4 multi-user fair-scheduling. Fix: ~10-15 LOC core + per-tool TOOL_TIMEOUTS dict. Not Phase 1.5 — Phase-3+-triggered. |
| F6 | **(Deeper lens C2) No tool output schema.** All tools return strings. MCP defines input + output schemas. | **Folded into F3 scope.** Output schemas fall out from the Phase 1.5a-N descriptor export lift naturally — no separate finding. |
| F7 | **(Deeper lens C6) Cross-source recall coupling concern.** | **Reaffirm existing memory note** `project_cross_source_recall_pattern.md`. |
**Phase 1.5 lift assignment:** F3 → see Phase 1.5 section below — **two sequential Phase 1.5a lift entries** (descriptors export + MCP server endpoint). Step 8 marks first surfacing of Phase 1.5a sub-phase.

_Engineering touches at this surface: 9 distinct frontier-execution patterns observed (idempotent index_all_tools with skip-if-unchanged; empty-rankable short-circuit; defensive _embed_text response-shape handling; always_loaded bypass for memory_search; embedding-model swap-detection re-embed; "Does NOT search X; use Y" cross-references per discipline; StructuredTool sync/async uniform dispatch; wire_litellm_providers() defensive re-call; commented Phase 3/4 imports for ImportError-safe fresh builds) — cited inline at the file:line references above. Not enumerated as a numbered finding to keep F-numbers reserved for actionable items (reviewer methodology note 2026-06-01)._

**Reviewer corrections (2026-06-01):** F1 site count revised 4 → 5 after reviewer Steps 7–9 re-grep caught `api/memory.py:20` (api/ surface wasn't audited until Step 10/11). `builtin_memory.py` line citation corrected `:19 → :20` (shifted by Step 8 F4 docstring fix landed in the same step). Refactor scope at memory-note time = 5. See `project_module_level_mem0_instantiation_smell.md` for live state.

**Methodology note:** Deeper lens nudge produced 2 net-new findings (F3 MCP-readiness aligned with user-anticipated Phase 1.5a candidate + F5 per-tool timeouts net-new) — proof-of-concept holding from Step 7. Self-dismissal rate on deeper-lens candidates was 5-of-8 in this step (premature / already-deferred / folded-into-other-finding). Consistent with Step 7's ratio; the deeper pass continues to earn its keep by forcing explicit dismissal-with-rationale rather than checklist-blind oversight.

**Cross-references:**
- Base plan: lines 3322-3577 (Task 1.11)
- In-place fix landed at audit-write time: `backend/app/agent/tools/builtin_memory.py:4` docstring (F4)
- Memory notes saved at this step: `project_per_tool_execution_timeout_gap.md` (F5)
- Memory notes amended at this step: `project_module_level_mem0_instantiation_smell.md` (F1 — 4 call sites enumeration + MEMORY.md ledger refresh)
- Memory notes referenced (existing, reaffirmed): `project_embedding_cost_attribution_gap.md` (F2), `project_cross_source_recall_pattern.md` (F7), `feedback_tool_specific_guidance_in_descriptions.md` (discipline confirmed), `project_agent_llm_cost_attribution_gap.md` (sibling bypass surface)
- Phase 1.5 lift entries surfaced at this step: 2 (Phase 1.5a-N descriptors + Phase 1.5a-N+1 server endpoint)

### Step 9 — Turns 11 + 11a + Turn 13 polish — Channel layer (Channel ABC + NormalizedMessage + Telegram + webhook + chat endpoint)

**Overall rating:** Frontier (first Frontier rating in the backward audit — confirms the pre-existing Frontier rating from `feedback_frontier_grade_discipline.md` for the Channel ABC + NormalizedMessage shape; rating holds after later turns' additions and the operational findings F1-F4 + F7 are hygiene/memory-ledger updates, not architectural gaps) — **Status:** final — sign-off 2026-05-25

**Scope:**
Channel layer in current state. Surface originated across Turns 11 (Task 1.12 — Channel ABC + Telegram concrete channel) + 11a (Task 1.13 — webhook receiver) + 13 polish (NormalizedMessage shape refinement) + Turn 16 polish (Gmail prefix-dispatch + `_resolve_gmail_approval` handler). Audit captures live state as of HEAD `16dd266` + Step 8 close + this step's in-place rename (F1).

**References:**

| Surface | File / location |
|---|---|
| Channel ABC + NormalizedMessage | `backend/app/messaging/channel.py` (94 lines) — 5-method abstract contract (normalize / send_reply / send_alert / send_approval_request / show_typing) + NormalizedMessage dataclass + thread_id_for() helper + PlatformName Literal |
| Channel registry | `backend/app/messaging/channel_registry.py` (renamed from `normalizer.py` at this step — see F1) (42 lines) — `ChannelRegistry` class + `channel_registry` singleton |
| Inbound + resume router | `backend/app/messaging/router.py` (268 lines) — `route_inbound` + `route_approval_decision` (with `gmail:` prefix-dispatch) + `_resolve_gmail_approval` handler (~130 LOC — see F2 decoupling deferral) |
| System-alert dispatcher | `backend/app/messaging/failure_alerter.py` (69 lines) — PRIMARY_ALERT_CHANNEL=telegram + 3 best-effort alert paths |
| Telegram channel impl | `backend/app/messaging/channels/telegram.py` (230 lines) — **lazy singleton via `get_telegram_channel()`** + `_send_with_markdown_fallback` defensive retry + polling-mode Application + CallbackQueryHandler |
| Telegram webhook receiver | `backend/app/api/webhooks/telegram.py` (81 lines) — HMAC constant-time secret + empty-secret deny-all default |
| /api/chat HTTP entry | `backend/app/api/chat.py` (64 lines) — Pydantic validation + `get_current_user` auth + fresh `web:<uuid>` thread minting + TurnEnvelope return |

Base plan: Task 1.12 (lines 3583-3992 — Channel ABC + Telegram) + Task 1.13 (lines 3993-4074 — Webhook) + Task 1.14 (lines 4075-4122 — Chat endpoint). Memory notes consulted: `project_gmail_approval_resume_fails_no_langgraph_thread.md` (re-verified vs live code — STALE, amended at this step), `project_gmail_approval_duplicate_race.md` (separate concern, no change), `project_email_action_capability_gap.md`, `project_module_level_mem0_instantiation_smell.md` (lazy-init contrast — informed F4), `feedback_frontier_grade_discipline.md` (Channel ABC pre-rated Frontier — verified rating holds).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | TurnEnvelope dict |
| One-line tool description | N/A | — |
| Single-item interface where batch frontier | N/A | Channel ABC per-message — correct shape (inbound dispatch is single-message-driven by nature) |
| **Module-level instantiation triggering I/O** | **None — DISCIPLINE APPLIED at every site** | (a) `router.py:32` `session_mgr = SessionManager()` — read-only adapter, no I/O. (b) `channel_registry.py:42` `channel_registry = ChannelRegistry()` — empty dict, no I/O. (c) `channels/telegram.py:220-230` — **LAZY** singleton via `get_telegram_channel()` accessor with explicit anti-import-time-crash comment. **Exemplar opposite of the module-level Mem0 smell — surfaced as F4 → discipline note 3rd worked-example.** |
| Logging-via-omission | N/A | Extensive structured logging at every dispatch path |
| Sync bypass of cost-tracking | N/A | No LLM calls at this layer (channel layer dispatches; agent layer makes LLM calls) |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **2 instances surfaced** | (a) **F1: `messaging/normalizer.py` filename misleading** — file contained `ChannelRegistry`, not message normalization. **Fixed in-place at audit-write time**: renamed to `channel_registry.py` + 6 importers updated (main.py, scheduler/celery_app.py, scheduler/tasks/morning_brief.py, messaging/failure_alerter.py, messaging/router.py, scripts/smoke_telegram_route.py) + module docstring augmented with rename-rationale note. (b) **F3: `project_gmail_approval_resume_fails_no_langgraph_thread.md` memory note is STALE** — described prefix-dispatch fix as "Fix when intolerable" but the fix IS IMPLEMENTED at router.py:118-120 + `_resolve_gmail_approval` handler. **Amended at audit-write time** with "FIXED pre-Step-9-audit" status header + retained historical context for the Phase 3+ generalization pattern. All other docstrings verified accurate. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | chat.py docstring Phase 4 streaming forward-look justified by "same shape" rationale; webhook empty-secret deny-all justified by defense-in-depth |

**Deeper comparison-target pass per surface:**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| `channel.py` (Channel ABC + NormalizedMessage) | (1) LangChain BaseTransport; (2) Anthropic MCP client; (3) OpenAI Assistants thread abstraction | Nothing material — Channel ABC's 5-method contract with explicit `normalize() → None` "ignore" semantic exceeds LangChain shape; MCP is cross-process (different concern); OpenAI thread management is server-side (acceptable difference). |
| `channel_registry.py` (registry — renamed at this step) | Any service-locator pattern | Self-dismiss — no Protocol-typing at registration (ABC enforcement at class-definition time is standard). |
| `router.py` | (1) LangChain RouterChain; (2) FastAPI APIRouter middleware; (3) Slack Bolt / Discord.py dispatch | **C2: `_resolve_gmail_approval` ~130 LOC lives in channel router** — Gmail-domain code in cross-domain coupling shape. **Surfaced as F2 → memory note `project_gmail_handler_decoupling_deferral.md` with trigger condition (2nd channel-origin handler lands).** **C1: No channel middleware** (Slack Bolt has hooks for metrics/Langfuse). Self-dismiss — inline logging works at scale. |
| `failure_alerter.py` | Sentry / Slack / PagerDuty alert dispatch | Multi-channel severity routing is frontier shape; self-dismiss as YAGNI for single-master single-channel scale (PRIMARY_ALERT_CHANNEL forward-look documented). |
| `channels/telegram.py` | (1) python-telegram-bot examples; (2) Slack Bolt ack-within-3s; (3) Discord.py | `_send_with_markdown_fallback` is genuinely frontier — more robust than python-telegram-bot's MarkdownV2 escape helper (handles ANY markup failure, not just escapes). Slack Bolt's 3s ack pattern doesn't apply to Telegram. Self-dismiss all candidates. |
| `webhooks/telegram.py` | FastAPI webhook patterns / Stripe-Twilio HMAC | Hand-rolled HMAC compare matches Stripe/Twilio shape; python-telegram-bot's webhook helper would wrap this but our hand-roll is simpler. No gaps. |
| `chat.py` | (1) OpenAI /v1/chat/completions; (2) Anthropic messages API; (3) LangChain REST | **C5: No streaming endpoint** (SSE/WebSocket) — plan-noted as Phase 4 streaming. Reaffirm deferral. **C-misc: chat.py docstring framing on `/api/costs` accuracy** — surfaced as F7 → deferred to costs.py audit (Step 10/11). |

Deeper lens result: 1 net-new structural finding (F2 cross-domain coupling — checklist doesn't have explicit "cross-domain coupling" smell). Other findings (F1 / F3 / F4 / F7) surfaced via documentation/anti-drift review. 4 deeper-lens candidates self-dismissed (premature / Phase-4-deferred / handled).

**Comparison target:**

Channel ABC + NormalizedMessage is comparable to LangChain's transport abstractions but with explicit `normalize() → None` "ignore this message" semantic that LangChain doesn't formalize. **The 5-method contract is genuinely Frontier shape** — every operation a messaging platform needs distilled into 5 abstract methods + 1 static helper. Adding WhatsApp / Discord / iMessage is genuinely one-class. The defensive engineering — lazy singleton, MarkdownV1 retry fallback, best-effort failure_alerter, HMAC constant-time secret check, empty-secret deny-all — exceeds plan-verbatim across the board.

**Three-hats tension surfaced:**

- **Architect** wants channel-agnostic agent layer with ABC enforcement. Wins on add-a-channel-is-one-class. Loses on `_resolve_gmail_approval` cross-coupling (Gmail-domain code in channel router). Tension resolved with prefix-dispatch pattern (shipped) + F2 surfaces the residual coupling for trigger-gated decoupling lift.
- **Engineer** wants defensive degradation at every external touchpoint — Telegram parse errors don't drop replies, failed alerts don't crash agent, missing webhook secret denies rather than allows. Tension: defense costs LOC. Resolved with explicit comments justifying each.
- **AI-ML engineer** wants TurnEnvelope as canonical shape across HTTP + messaging transports — single rendering contract. Wins on no-factoring-drift. Loses on streaming (TurnEnvelope is one-shot; SSE would need a different shape). Tension resolved with Phase 4 streaming as additive (same shape incrementally, not replacement).

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **`messaging/normalizer.py` filename misleading** — file contained `ChannelRegistry`, not message normalization (NormalizedMessage lives in `channel.py`). Discoverability concern. | **In-place rename landed at audit-write time** — `mv normalizer.py channel_registry.py` + 6 importers updated (main.py, scheduler/celery_app.py, scheduler/tasks/morning_brief.py, messaging/failure_alerter.py, messaging/router.py, scripts/smoke_telegram_route.py) + module docstring augmented with rename-rationale note. Mirror of Step 2's `.env.example` Cloudflare reframe + Step 8's F4 docstring fix. |
| F2 | **`_resolve_gmail_approval` ~130 LOC Gmail-domain code in channel router** (router.py:135-269). Cross-domain coupling concern. | **NEW memory note saved at this step:** `project_gmail_handler_decoupling_deferral.md`. Trigger: 2nd channel-origin approval handler lands (calendar invite confirmations, booking handler, web-form approvals). Fix shape (~30-45 min when triggered): extract handler to `app.email.gmail_approval_handler.resolve()` + `CHANNEL_ORIGIN_HANDLERS` dispatch dict in router. Not Phase 1.5 — Phase-3-triggered. |
| F3 | **Memory note `project_gmail_approval_resume_fails_no_langgraph_thread.md` is STALE** — described prefix-dispatch fix as "Fix when intolerable" but the fix IS IMPLEMENTED at router.py:118-120. | **Amended memory note at audit-write time** — added "STATUS UPDATE (Step 9 audit, 2026-05-25): FIXED" header citing live router.py:118-120 + `_resolve_gmail_approval` handler. Retained original problem statement as historical context. MEMORY.md ledger entry updated to "Gmail approval resume-fail noise — FIXED". |
| F4 | **Telegram channel's lazy singleton pattern** — `_telegram_channel: TelegramChannel \| None = None` + `get_telegram_channel()` accessor with explicit anti-import-time-crash rationale (channels/telegram.py:220-230). Exemplar opposite of the module-level Mem0 smell. | **Amended `feedback_frontier_grade_discipline.md`** at this step with NEW worked-examples section ("Worked examples of lazy-init discipline applied in existing code") — separate from the anti-drift section (those are 2 anti-drift examples; lazy-init is a different discipline at a different surface). Section explicitly distinguishes the two patterns to avoid blur. Sibling-smell note cross-reference (`project_module_level_mem0_instantiation_smell.md`) cited for the both-surfaces pair. |
| F5 | **Anti-drift baseline observed in all 7 file docstrings — accurate, with one count miscount caught by reviewer.** Channel ABC docstring at `channel.py:46` originally said "implement the four async methods" — actual count is 5 (normalize, send_reply, send_alert, send_approval_request, show_typing). Caught by reviewer Steps 7–9 re-pass on 2026-06-01 (my Step 9 audit reproduced the same miscount in "4-method contract" framing at the Scope + Comparison-target sections, since fixed). Other docstring claims (route_approval_decision cross-reference to memory note; telegram.py lazy-factory explanation; chat.py TurnEnvelope description; failure_alerter best-effort framing) all verified accurate. | **In-place fix landed on 2026-06-01** — `channel.py:46` docstring updated to "five async methods" + method names enumerated. Step 9 entry's Scope + Comparison-target wording updated in the same pass. Mild anti-drift finding; no Phase 1.5 lift. |
| F6 | **chat.py docstring framing on `/api/costs` accuracy** — claims AUTHORITATIVE source for cost data when in fact LLMUsageLog (which /api/costs reads) misses 3 bypass surfaces per `project_agent_llm_cost_attribution_gap.md`. | **Deferred to costs.py audit (Step 10 or 11).** Right home for the cost-gap caveat is the `/api/costs` endpoint docstring itself, not chat.py. Cross-reference forward to whichever step audits api/costs.py to surface the caveat there. |

**Phase 1.5 lift assignment:** **None** from this step. F1 landed in-place. F2 deferred-with-trigger as memory note. F3 amended existing note. F4 amended discipline note. The channel layer's pre-existing Frontier rating + no correctness-blocking gaps means no foundation-lift surfacing at this step.

_Engineering touches at this surface: 10 distinct frontier-execution patterns observed (lazy TelegramChannel factory with anti-import-time-crash rationale; `_send_with_markdown_fallback` parse-failure retry; Channel ABC's 5-method contract with explicit `normalize() → None` ignore semantic; `thread_id_for()` static helper centralizing canonical format; `route_approval_decision` prefix-dispatch for channel-origin vs LangGraph-thread approvals; `failure_alerter` best-effort error swallow; webhook secret HMAC constant-time compare via `hmac.compare_digest`; empty `TELEGRAM_WEBHOOK_SECRET` deny-all default; polling vs webhook entry-mode mutex with symmetric pipeline; TurnEnvelope shape shared with `/api/approvals/{id}/decide` for no-factoring-drift) — cited inline at the file:line references above. Not enumerated as a numbered finding to keep F-numbers reserved for actionable items (reviewer methodology note 2026-06-01)._

**Methodology note:** Deeper lens nudge produced 1 net-new structural finding (F2 cross-domain coupling — the checklist doesn't have an explicit "cross-domain coupling" smell; deeper-pass surface-by-surface review of router.py caught it). Other findings (F1 / F3 / F4 / F6) surfaced via documentation/anti-drift review. 4 deeper-lens candidates self-dismissed (premature / Phase-4-deferred / handled). The deeper pass's yield is necessarily lower at Frontier-rated surfaces (less to surface) but still non-zero — F2 caught structural concern the standard checklist would miss.

**Cross-references:**
- Base plan: Task 1.12 (lines 3583-3992) + Task 1.13 (lines 3993-4074) + Task 1.14 (lines 4075-4122)
- In-place rename landed at audit-write time: `backend/app/messaging/normalizer.py` → `backend/app/messaging/channel_registry.py` + 6 importers updated (F1)
- Memory notes saved at this step: `project_gmail_handler_decoupling_deferral.md` (F2)
- Memory notes amended at this step: `project_gmail_approval_resume_fails_no_langgraph_thread.md` (F3 — STATUS UPDATE: FIXED + MEMORY.md ledger refresh), `feedback_frontier_grade_discipline.md` (F4 — new "Worked examples of lazy-init discipline" section as 3rd exemplar with explicit distinction-from-anti-drift framing)
- Forward cross-reference: Step 10 or 11 (api/costs.py audit) — surface F6 cost-attribution caveat at the right docstring home
- Memory notes referenced (existing, reaffirmed): `project_gmail_approval_duplicate_race.md` (separate concern, no change), `project_email_action_capability_gap.md`, `project_module_level_mem0_instantiation_smell.md` (informed F4 lazy-init exemplar contrast)

### Step 10 — Turn 14 — Phase 1 test suite close-out

**Overall rating:** Mid-to-Frontier (2 genuine end-to-end integration tests + 2 real-services component tests + 11 frontier-execution touches push above Mid; absence of coverage measurement + eval framework + integration backbone + channel/email coverage at this layer holds it below Frontier; lifts to Frontier when Turn 20.5 ships its scope including the new `2.X-closeout-y` coverage measurement task) — **Status:** final — sign-off 2026-06-01

**Scope:**
Phase 1 test suite in current state. Surface originated at Turn 14 (Task 1.19) and accumulated additions across later turns: `test_resume_dedup.py` added at Turn 17.5 (resume safety, explicitly framed as "the single most important test in Phase 1"); `test_fallback_llm.py` added at Turn 17.7 (FallbackChatLLM predicate-coverage). Audit captures live state as of HEAD `16dd266` + Step 9 close + this step's base-plan amendments (F2 guarded motivation update + F3 new `closeout-y` task).

**References:**

| File | LOC | Originating turn | Coverage axis | Quality shape |
|---|---|---|---|---|
| `test_cost_cap_enforcement.py` | 175 | Turn 5 (LLM gateway) | Cost cap soft/hard tier; CostCapExceededError raise path | **Real-services integration** (real Redis + real LLMGateway construction); snapshot+restore counter-isolation fixture |
| `test_error_envelope.py` | 110 | Turn 11 (TurnEnvelope contract) | Envelope shape on graph error path | **Unit-shape** (mock at `graph().ainvoke` level) |
| `test_fallback_llm.py` | 136 | Turn 17.7 (FallbackChatLLM, post-Turn-14 add) | 5 retry-predicate scenarios (success / rate-limit / tool_use_failed / other-bad-request / auth-error) | **Unit-shape** (AsyncMock at Runnable.ainvoke); narrow predicate coverage with negative cases |
| `test_memory_recall_integration.py` | 159 | Turn 6 (Memory layer) | Mem0 add/recall + thread_id post-filter + cross-thread isolation | **Genuine end-to-end integration** (real Mem0 + real Postgres/pgvector); `infer=False` bypasses Gemini extraction for determinism |
| `test_prompt_cache_stability.py` | 165 | Turn 7 (Prompts) | STABLE PREFIX byte-identity + alphabetical sort + inverse sanity check | **Unit-shape** (pure prompts.py functions) |
| `test_rate_limits.py` | 155 | Turn 8 (Rate limits) | Per-tool tighter caps + per-turn isolation + sliding-window pruning | **Real-services component** (real Redis); monkeypatch for cap-override speed |
| `test_resume_dedup.py` | 290 | Turn 17.5 (resume safety, post-Turn-14 add) | Run → interrupt → resume cycle + exactly-once defense + PendingApproval row state machine + approval_id contract + final state ToolMessage validation | **Genuine end-to-end integration** (real graph + real AsyncPostgresSaver + real Redis + real Postgres-backed PendingApproval queries); LLM faked via `FakeMessagesListChatModel`; tools mocked via `tool_registry.execute` patch; approval send no-op'd |
| `test_safety_classifier.py` | 222 | Turn 7 (Safety) | All TOOL_SAFETY_MAP entries + unknown-tool fail-safe + Telegram-master override + never-downgrade + malformed-args robustness | **Unit** (pure classifier, no I/O); exhaustive parametrize + adversarial coverage |
| `test_sanitizer.py` | 95 | Turn 8 (Sanitizer) | Wrapper tags + preamble + truncation + non-string coercion + adversarial prompt-injection content stays inside tags | **Unit** (pure function); adversarial-input coverage |
| `test_tool_selector_structural.py` | 111 | Turn 10 (Tool registry) | Always-loaded set non-empty + selector returns only always-loaded when no rankables + no dups + empty query handling | **Structural smoke** (explicit Phase-1-limitation docstring); touches real registry |

10 test files, 1618 LOC. No `backend/tests/integration/` subdirectory exists yet (deferred to Turn 20.5 `closeout-v`/`w`). Base plan: Task 1.19 (lines 4412-5067) + Turn 20.5 motivation (line 9653, amended at this step) + Turn 20.5 task list (extended at this step with `closeout-y`). Memory notes consulted: `project_async_state_rebind_pattern.md` (informed `test_resume_dedup` event-loop rebind fixture), `project_mem0_silent_drop_on_rpm.md` (informed `test_memory_recall_integration` `infer=False` choice), `project_mem0_extraction_gemini_swap.md` (cross-reference in memory_recall docstring), `feedback_conversation_agreements_land_in_plan.md` (informs F1 no-action disposition).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | — |
| One-line tool description | N/A | — |
| Single-item interface where batch frontier | N/A | Tests are per-scenario by design |
| **Module-level instantiation triggering I/O** | **None — discipline applied** | No test file constructs `MemoryManager()` / `RateLimiter()` / etc. at module scope. All construction lives in pytest fixtures (per-test scope). Better than the Phase 1 `app/` layer where the module-level Mem0 smell propagates across 5 sites. `test_prompt_cache_stability.py` has `_ALWAYS_ON` dict at module level (data only, no I/O — fine). `test_tool_selector_structural.py` calls `register_all_tools()` via autouse fixture (per-test, idempotent — fine). |
| Logging-via-omission | N/A | Tests don't log; assertions communicate state |
| Sync bypass of cost-tracking | N/A | — |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **2 instances surfaced (both actionable)** | (a) **F1: Base plan Task 1.19 specified 9 test files (conftest.py + 8 named test_*.py); live state has 10 differently-named files** — 4 plan-named files dropped or renamed, 6 additional files shipped beyond plan. **Additionally: channel layer + email classifier have zero coverage at this layer** — their only home is Turn 20.5 `closeout-v`/`w`. (b) **F2: Base plan Turn 20.5 motivation framing at line 9653 was STALE** — said "only one... is a genuine integration test" but live state has two. **Amended at audit-write time** with guarded phrasing that preserves the still-true "no full Telegram→agent→tool→reply e2e" sentence. All 10 test file docstrings verified accurate. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | All defensive patterns justified inline (event-loop rebind fixture cross-references `project_async_state_rebind_pattern.md`; snapshot+restore counter-isolation justified by test-poisoning risk; `FakeMessagesListChatModel` choice justified by needing canned LLM responses driving a real graph) |

**Deeper comparison-target pass:**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| Test suite as whole | (1) pytest + pytest-asyncio (match); (2) LangChain test suite patterns; (3) OpenAI Agents SDK tests; (4) eval frameworks (DeepEval, RAGAS, custom golden-query harnesses) | **C1: `backend/tests/integration/` subdirectory absent** — plan-noted Turn 20.5 (`closeout-v` + `w`). Reaffirm deferral. **C2: eval framework with golden queries** — plan-noted Turn 20.5 (`closeout-t` + `u`). Reaffirm deferral. **C3: no coverage measurement (coverage.py + CI gate)** — 1618 LOC of tests with no coverage signal; easy for new code to ship without tests and never get flagged. **Surfaced as F3 → new Turn 20.5 task `closeout-y` (folded into 20.5's test-infra scope per reviewer disposition; sibling to `closeout-x` which is eval-score regression tracking, NOT line-coverage).** **C4: snapshot/approval testing for LLM outputs** — self-dismiss as speculative. **C5: property-based testing (Hypothesis)** — self-dismiss as YAGNI for current surface. **C6: mutation testing (mutmut)** — self-dismiss as overkill. **C7: pytest-xdist parallelization** — self-dismiss as Phase 4 polish. |

Deeper lens result: 7 candidates surfaced. **1 net-new gap (F3 — folded into Turn 20.5 as `closeout-y`).** 2 already plan-noted (C1, C2). 4 self-dismissed.

**Comparison target:**

Standard-shop pytest + pytest-asyncio with real-services fixtures matches LangChain's test patterns + most agent-framework test suites. **`test_resume_dedup.py` (290 LOC, real graph + checkpointer + Redis + Postgres-backed PendingApproval queries) exceeds typical agent-framework coverage** — most agent libraries don't ship such comprehensive resume-from-interrupt tests. Eval framework + integration backbone + line-coverage measurement are forward-looking gaps owned by Turn 20.5.

**Three-hats tension surfaced:**

- **Architect** wants test isolation across the whole suite. Wins on UUID-suffixed thread_id pattern (no cross-test leakage) + per-test fixture pattern (no conftest.py module-level coupling). Loses on test runtime — real-services tests are slow. Tension resolved with per-test isolation + acceptance of slowness.
- **Engineer** wants tests that verify behavior, not just code shape. Wins on real-services tests (4 of 10 use real Redis/Postgres/Mem0; 2 of those are genuine end-to-end). Loses on `test_error_envelope` + `test_fallback_llm` being pure mocks (verify contract, not behavior). Tension acceptable: contract tests at component boundaries + integration tests for critical paths.
- **AI-ML engineer** wants tests that verify LLM-driven behavior. Wins on `test_resume_dedup`'s `FakeMessagesListChatModel` pattern (canned LLM responses driving real graph). Loses on no eval framework / golden query suite / LLM-judged quality regression tracking. Tension resolved with Turn 20.5 deferral (`closeout-t` + `u`).

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **Base plan Task 1.19 test file naming drift + concrete coverage gaps that 20.5 owns.** Plan specified `conftest.py` + 8 named `test_*.py`; live state has 10 differently-named files. 4 plan-named files dropped or renamed (conftest.py absent — per-test fixtures used instead, modern pytest pattern; test_agent_graph.py absent — test_resume_dedup.py covers the most critical graph contract end-to-end; test_dynamic_tool_loading.py renamed test_tool_selector_structural.py; test_channel_normalizer.py absent — channel layer not unit-tested at this layer; test_approval_flow.py absent — test_resume_dedup.py covers the end-to-end approval flow; test_email_classifier.py absent — Phase 2 work, not Phase 1 scope). 6 additional files shipped beyond plan (test_cost_cap_enforcement, test_error_envelope, test_fallback_llm, test_memory_recall_integration, test_prompt_cache_stability, test_resume_dedup). **Concrete coverage gaps remain**: channel layer (Step 9 surface — Channel ABC + router + Telegram impl + webhook + chat endpoint) has ZERO tests at this layer; email classifier (Phase 2 work) has ZERO tests at this layer. Their only home is Turn 20.5 `closeout-v` (Telegram → agent → tool → reply e2e covers channel layer end-to-end) and `closeout-w` (cross-source recall exercises email_history_search end-to-end, which implicitly tests the email classifier path). | **No-action documentation acknowledgment for the naming drift** (per `feedback_conversation_agreements_land_in_plan.md` — base plan is historical baseline; dropped files like conftest.py are intentional design choices). **Forward note: Turn 20.5 is load-bearing for COVERAGE, not just eval + integration** — slipping 20.5 doesn't just lose the deferral discipline's measurement instrument (per Turn 20.5 structural-role framing), it also leaves the channel + email-classifier surfaces structurally untested. Captured in base-plan Turn 20.5 motivation amendment (F2). |
| F2 | **Base plan Turn 20.5 motivation framing at line 9653 was STALE** — said *"only one of which (`test_memory_recall_integration`) is a genuine integration test"* — but live state has TWO genuine integration tests. `test_resume_dedup.py:99-291` is real graph + real AsyncPostgresSaver + real Redis + real Postgres-backed PendingApproval queries, explicitly framed as "The single most important test in Phase 1." It exercises the interrupt-resume path with the LLM faked (`FakeMessagesListChatModel`) and tools mocked (`tool_registry.execute` patched) + approval-send no-op'd. The plan note's "only one" framing undercounts and was likely written before Turn 17.5 shipped `test_resume_dedup`. **Guard against overshoot:** the still-true sentence — there is NO full Telegram → agent → tool → reply e2e test — must stay; `closeout-v`/`w` are what would land that coverage. | **Amended base plan line 9653 at audit-write time** with guarded phrasing per reviewer disposition: "TWO are genuine integration tests (`test_memory_recall_integration` + `test_resume_dedup`); `test_resume_dedup` exercises the real graph + checkpointer + DB/Redis on the interrupt-resume path with the LLM faked and tools mocked. ... Still no full Telegram → agent → tool → reply end-to-end test — that's `closeout-v` (email flow ...) and `closeout-w` (cross-source recall ...). Channel layer + email classifier have zero coverage at this layer; their only home is `closeout-v`/`closeout-w`, which makes this turn load-bearing for coverage, not just eval." Doesn't change Turn 20.5 scope; corrects the undercount AND adds the F1 coverage-load-bearing framing inline at the motivation paragraph (one amendment covers both). |
| F3 | **(Deeper lens C3) No line-coverage measurement.** 1618 LOC of tests with no coverage signal — easy for new code to ship without tests and never get flagged. Frontier shape: `coverage.py` + (eventually) CI gate at e.g. 70% line coverage baseline. Distinct from `closeout-x` (which is eval-score regression tracking on the golden suite — LLM-judged quality scores, not application line coverage). | **Folded into Turn 20.5 as new `2.X-closeout-y` task at audit-write time** per reviewer disposition ("test-infra owned by 20.5; don't park-lot it as a standalone Phase-4 memory note"). Scope: add coverage.py config to pyproject.toml, generate local HTML report, commit baseline number; CI gate deferred to Phase 4 pipeline. Explicit "distinct from `closeout-x`" framing in the task body to prevent confusion (closeout-x = behavioral-quality regression; closeout-y = line coverage). No standalone memory note; no MEMORY.md ledger change at this step. |

**Phase 1.5 lift assignment:** **None** from this step. F1 no-action ack. F2 + F3 land as base-plan amendments to Turn 20.5 block.

_Engineering touches at this surface: 11 distinct frontier-execution patterns observed (snapshot+restore Redis counter-isolation fixture in test_cost_cap_enforcement; `_add_no_infer` helper bypassing Mem0 extraction LLM for deterministic test writes in test_memory_recall_integration; cleanup fixture with best-effort failure swallowing + orphan-identifiable thread_id; inverse-sanity test in test_prompt_cache_stability proving the main test doesn't pass for wrong reason; checkpointer/event-loop rebind fixture in test_resume_dedup cross-referencing project_async_state_rebind_pattern.md; `reset_runner_graph` fixture forcing rebuild so patches take effect; comprehensive end-to-end resume_dedup test with multi-leg state validation (status / interrupt payload / approval_id contract / PendingApproval row state machine / counter dedup / final state ToolMessages); exhaustive parametrize coverage in test_safety_classifier + adversarial malformed-args tests; adversarial prompt-injection content test in test_sanitizer verifying it stays inside `<tool_output>` tags; honest "structural" naming + Phase-1-limitation docstring in test_tool_selector_structural; narrow predicate-coverage in test_fallback_llm with negative-case tests (other_bad_request + auth_error must NOT trigger fallback)) — cited inline at the file:line references in the References table above._

**Methodology note:** Deeper lens nudge produced 1 net-new gap (F3 coverage measurement, folded into Turn 20.5 as `closeout-y` per reviewer disposition rather than spawning a standalone Phase-4 memory note — "test-infra owned by 20.5; don't park-lot it"). 2 already plan-noted (integration backbone via `closeout-v`/`w` + eval framework via `closeout-t`/`u`). 4 self-dismissed (snapshot / Hypothesis / mutmut / xdist as premature). Codified count-discipline + as-of-step framing applied from outset; F-numbers reserved for actionable items (per reviewer's silence-worthy protocol: positive findings like "anti-drift baseline verified across all 10 docstrings" + "test_resume_dedup fixture cross-references project_async_state_rebind_pattern.md" were silenced rather than promoted to F-rows — a verified-accurate docstring scan + an at-the-right-surface cross-reference observation don't earn F-numbers).

**Cross-references:**
- Base plan: Task 1.19 (lines 4412-5067) — Phase 1 test suite specification
- Base plan amended at this step: (1) Turn 20.5 motivation line 9653 — F2 guarded amendment (1→2 integration tests + still-true "no full e2e" sentence preserved + coverage-load-bearing framing per F1); (2) Turn 20.5 task list extended with `2.X-closeout-y` — F3 line-coverage measurement (coverage.py + baseline; CI gate deferred to Phase 4)
- Memory notes saved at this step: **none** (F3 folded into 20.5 instead of standalone note)
- Memory notes amended at this step: **none**
- MEMORY.md ledger: **no change** (no new or renamed notes)
- Forward cross-reference: Turn 20.5 execution owns the channel + email-classifier coverage gap (closeout-v/w) + the line-coverage baseline (closeout-y); when 20.5 ships, the Step 10 rating lifts to Frontier
- Memory notes referenced (existing, reaffirmed): `project_async_state_rebind_pattern.md` (informed test_resume_dedup rebind fixture — Phase 1 test fixture solution to the pattern), `project_mem0_silent_drop_on_rpm.md` (informed test_memory_recall_integration `infer=False` choice), `project_mem0_extraction_gemini_swap.md` (cross-reference in memory_recall docstring), `feedback_conversation_agreements_land_in_plan.md` (informs F1 no-action disposition)

### Step 11 — Turn 12 — API + auth layer (closes Phase 1 audit)

**Overall rating:** Frontier (Phase 1 closes with two Frontier-rated surfaces — Step 9 channel layer + Step 11 API/auth — bookending the Mid / Mid-to-Frontier surfaces of Steps 3-7, 8, 10; defensive engineering across 12 distinct touches exceeds typical FastAPI agent-backend shape; F1 closes the Step 9 F6 forward cross-reference; F2 forward-pickup signal lands at base plan Task 4.18 to prevent Phase 4 create-second/overwrite) — **Status:** final — sign-off 2026-06-01

**Scope:**
API + auth layer in current state. Last unaudited Phase 1 surface (Step 9 grouped Turns 11 + 11a + 13 and skipped Turn 12). chat.py + webhooks/telegram.py were already audited at Step 9 — cross-referenced here, NOT re-audited. The remainder: approvals + costs + gmail-webhook + health + memory + router + auth dependency + main.py lifespan. Audit captures live state as of HEAD `16dd266` + Step 10 close + this step's in-place fix (F1 costs.py caveat) + base plan amendment (F2 Task 4.18 forward note).

**Step-numbering re-derivation (reviewer directive 2026-06-01):**
Phase 1 turns audited across Steps 3-11 (Turns 4-14 inclusive). **Phase 1 audit closes at Step 11.** Only the next-step boundary is settled: Phase 2 audit starts at Step 12 = Turn 15. Subsequent step numbering (Phase 2 grouping, consolidation step, gate step) re-derived as the audit progresses; not pre-locked.

**References:**

| File | LOC | Originating turn / scope | Audited as |
|---|---|---|---|
| `backend/app/api/approvals.py` | 192 | Task 1.15 (Main API Router + Approvals + Health) | `resolve_approval` helper (idempotent — duplicate Approve returns existing thread_id without re-write) + `GET /pending` (filters `expires_at > now`) + `POST /{id}/decide` (returns TurnEnvelope shape); mounted under protected tier |
| `backend/app/api/costs.py` | 104 (+11 caveat lines added at this step) | Phase 2 cost dashboard (base plan line 6665), mounted at this layer | `GET /api/costs` — today_utc + last_7d windows; aggregates LLMUsageLog by model + task_type; **F1 caveat added at this step** closes Step 9 F6 forward cross-reference |
| `backend/app/api/health.py` | 110 | Task 1.15 scope | Public liveness; 4 dep checks (db / checkpointer / redis / langfuse); explicit "no operational detail leakage" discipline |
| `backend/app/api/memory.py` | 55 | Task 1.7 cross-reference (base plan line 1218) | `GET /search` + `GET /profile`; **5th Mem0 module-level instantiation site at line 20** — reaffirm only per reviewer (already in 5-site note) |
| `backend/app/api/router.py` | 55 | Task 1.15 aggregator | Two-tier: public (health + webhooks) + protected (chat + approvals + memory + costs via `protected_router` with router-level `Depends(get_current_user)`); `/api/_auth/whoami` smoke endpoint |
| `backend/app/api/webhooks/gmail.py` | 110 | Phase 2 Gmail integration (Turn 16/17), mounted at this layer | OIDC Bearer JWT auth (currently STUBBED — `verify_gmail_webhook` returns True; Phase 4 Task 4.16 owns the real impl, documented inline); ACK policy with `_is_retry_worthy` conservative whitelist |
| `backend/app/security/auth.py` | 125 | Live: Phase 1; **base plan formally specs at Phase 4 Task 4.18** (F2 plan-vs-code drift) | Dual-path X-API-Key (HMAC constant-time) + Bearer HS256 JWT; UserContext dataclass; empty-secret deny-all default; "API key first; mismatched key doesn't fall through to JWT — suspicious" guard; explicit Phase 4 JWE migration notes (two viable swap paths) |
| `backend/app/security/webhook_verify.py` | 41 | Phase 2 stub | Single `verify_gmail_webhook` stub returning True with worst-case-attacker analysis + 6-step real-implementation checklist for Phase 4 Task 4.16 |
| `backend/app/main.py` | 275 | Task 1.18 (Docker Compose Full Stack) + lifespan wiring | Ordered lifespan (DB → profile guard → checkpointer → tools → channels) with documented rationale; `_startup_model_ping` Groq-deprecation surveillance (Groq `gemma2-9b-it` decommission past-incident); `_ensure_master_profile_or_exit` fail-fast first-run guard; CORS allowlist locked to TUNNEL_PUBLIC_URL with safety-footgun rationale; polling-vs-webhook hard mutex |

Cross-referenced (audited at Step 9, NOT re-audited): `backend/app/api/chat.py` (Task 1.14), `backend/app/api/webhooks/telegram.py` (Task 1.13 telegram half).

Base plan: Task 1.13 lines 3993-4074 (gmail half), Task 1.15 lines 4123-4294 (Main API Router + Approvals + Health), Task 1.7 cross-ref line 1218 (memory.py), Phase 2 cost dashboard line 6665 (costs.py), Task 4.18 lines 8904-8933 (auth.py formal spec — amended at this step with forward note per F2). Memory notes consulted: `project_agent_llm_cost_attribution_gap.md` (informed F1 caveat content + closes Step 9 F6 forward cross-reference), `project_cost_cap_redis_only.md` (re-verified — cap and /api/costs read different sources, failure-mode-divergent, baseline accurate), `project_oauth_scope_minimization_production_hardening.md` (revocation-handling promoted out of "production hardening" bucket post 2026-05-20→24 incident — not Step 11 actionable; auth.py itself doesn't carry revocation alerting yet, separate Phase 2.5/3 concern), `project_module_level_mem0_instantiation_smell.md` (5th site reaffirm), `project_gmail_approval_duplicate_race.md` + `project_gmail_handler_decoupling_deferral.md` (gmail-webhook → approval-path landscape; both noted, no new finding at this layer), `feedback_conversation_agreements_land_in_plan.md` (informs F2 plan-amendment decision).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | Pydantic models on all endpoint responses |
| One-line tool description | N/A | — |
| Single-item interface where batch frontier | N/A | HTTP endpoints per-request |
| **Module-level instantiation triggering I/O** | **1 known site (5th Mem0)** | `api/memory.py:20` `_memory = MemoryManager()` — already in the 5-site note (`project_module_level_mem0_instantiation_smell.md`); reaffirm only, no new finding. All other module-level constructions are zero-I/O: `app = create_app()` (FastAPI app, lifespan deferred); router instantiations (pure dict construction); `protected_router = APIRouter(dependencies=[Depends(get_current_user)])` (Depends is a marker, not a call); `CurrentUser = Depends(get_current_user)` at auth.py:125 (marker). Channel layer's lazy-init exemplar (Step 9 F4) is the right shape; api/memory.py is the outlier — refactor scope captured in the 5-site note. |
| Logging-via-omission | Mild | `auth.py:_verify_api_key` returns False silently on mismatched API key (line 65). API key brute-force attempts invisible until they succeed. Mild observability gap; per-API rate-limiting at `app/security/rate_limiter.py` (Phase 4 Task 4.17 per the disambiguation docstring in `agent/rate_limits.py:19` — file doesn't exist yet) is the planned mitigation. Reaffirm plan-noted deferral; not Step 11 actionable. All other endpoints log every interesting branch. |
| Sync bypass of cost-tracking | N/A | No LLM calls at this layer (gmail.py webhook hands off to email pipeline) |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | Foundation layer |
| **Documentation drift from code** | **2 actionable instances** | (a) **F1: `costs.py:1-16` docstring accurate but INCOMPLETE** — silently propagates the gap surfaced at Step 9 F6: LLMUsageLog itself misses 3 bypass surfaces per `project_agent_llm_cost_attribution_gap.md`. **Fixed in-place at audit-write time** with 11-line caveat block added after "no dedup logic" paragraph; closes Step 9 F6 forward cross-reference. (b) **F2: `auth.py` plan-vs-code drift** — shipped Phase 1 with richer dual-path shape (X-API-Key + JWT + UserContext + Phase 4 JWE notes inline); base plan formally specs at Task 4.18 with single-path JWT-only shape. Following Task 4.18 verbatim in Phase 4 would create-second or overwrite the richer file. **Fixed at audit-write time with a forward note at Task 4.18** — reviewer rejected no-action ack ("forward signal can't live in the audit entry alone — the Phase 4 executor won't be reading the Step 11 entry"). Mirrors the Step 6/7/8/10 base-plan-amendment pattern. All other docstrings verified accurate. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | All defensive patterns earn their keep (`_startup_model_ping` Groq decommission rationale; `_ensure_master_profile_or_exit` first-conversation hallucination risk; CORS allowlist safety-footgun rationale; polling-vs-webhook mutex double-delivery risk; auth.py Phase 4 JWE notes Auth.js v5 default-shape mismatch) |

**Deeper comparison-target pass:**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| API layer as whole | (1) FastAPI examples (match); (2) Anthropic/OpenAI public-API patterns; (3) Cursor backend APIs; (4) Slack/Discord webhook patterns | **C1: No API versioning** (`/api/v1/...`). Self-dismiss as YAGNI Phase 1. **C2: No per-API rate limiting / brute-force protection** — `app/security/rate_limiter.py` planned at Phase 4 Task 4.17 per disambiguation docstring; file doesn't exist yet. Reaffirm plan-noted deferral. **C3: No request correlation ID middleware** for distributed tracing — Langfuse traces by thread_id; HTTP requests untraced. Phase 4 polish. Self-dismiss. **C4: No pagination on `/approvals/pending`** — single-master Phase 1 fine; Phase 4 multi-user concern. Self-dismiss. **C5: No webhook replay protection** — Telegram secret_token constant; Gmail JWT iat/exp provides partial. Theoretical at single-master scale. Self-dismiss. **C6: `gmail.py` webhook uses STUBBED `verify_gmail_webhook`** — fully documented in webhook_verify.py + Phase 4 Task 4.16 home. Reaffirm plan-noted deferral. **C7: `auth.py` logs failed JWT verify but not failed X-API-Key** — surfaced in smells row Logging-via-omission; mitigation via Phase 4 Task 4.17 rate_limiter. Reaffirm. |

Deeper lens result: 7 candidates surfaced. **0 net-new findings** — all 7 are either plan-noted deferrals (C2, C6) or premature/Phase-4-polish (C1, C3, C4, C5, C7). The standard smells scan caught the 2 actionable findings (F1 cost-caveat + F2 auth.py drift).

**Comparison target:**

FastAPI's own example patterns + Anthropic/OpenAI public-API shape are the closest comparables. **The API layer's defensive engineering exceeds typical FastAPI agent-backend shape** — `_startup_model_ping` (deprecation surveillance with concrete past-incident rationale), `_ensure_master_profile_or_exit` (fail-fast first-run guard), explicit polling-vs-webhook mutex, CORS allowlist with "safety footgun" rationale, gmail webhook ACK policy with non-retry-worthy default, dual-path auth with Phase 4 JWE migration documented inline, public-on-purpose `/health` with explicit operational-detail-leakage discipline, two-tier router pattern with `dependencies=[Depends(get_current_user)]` at router level rather than per-endpoint, `/api/_auth/whoami` smoke endpoint that verifies both auth paths cleanly. The Channel layer (Step 9) + API layer (Step 11) bookend Phase 1 with two Frontier-rated surfaces.

**Three-hats tension surfaced:**

- **Architect** wants clean public/protected separation. Wins on `protected_router = APIRouter(dependencies=[Depends(get_current_user)])` pattern. Loses on memory.py + costs.py mounted under protected even though they're read-only — for Phase 4 multi-user, read-only doesn't mean public (cross-user data leakage). Resolved correctly: even read-only endpoints require auth.
- **Engineer** wants defensive degradation at every external touchpoint. Wins on gmail webhook ACK 200 default for non-retry-worthy failures (don't burn LLM quota on retries), health endpoint never raises, lifespan model-ping never blocks startup, profile-guard SystemExit before serving traffic. Loses on observability — silent successes don't telegraph; grep logs to know what worked. Acceptable at single-master scale.
- **AI-ML engineer** wants the cost dashboard surface to be honest. Loses pre-Step-11 — `/api/costs` reported LLMUsageLog spend, which omits agent_node + embedding + Mem0-extraction bypass surfaces. **Resolved by F1 docstring caveat in-place fix at this step**; structural fix (Option C hybrid helper in cost-attribution gap note) waits for Phase 4 dashboard work.

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **costs.py docstring missing cost-attribution-gap caveat** — deferred from Step 9 F6. Live `costs.py:1-16` said "Source: LLMUsageLog rows" + "no dedup logic because each callback fires per-completion" — accurate but incomplete. LLMUsageLog itself misses 3 gateway-bypass surfaces (agent_node via FallbackChatLLM, embedding via litellm.aembedding, Mem0 extraction via litellm provider) per `project_agent_llm_cost_attribution_gap.md`. Reader inferring from the docstring would think `/api/costs` is authoritative for all LLM spend; in fact it's authoritative for what the GATEWAY tracked — a strict subset. | **In-place docstring fix landed at audit-write time** — 11-line caveat block added to `backend/app/api/costs.py` after the "no dedup logic" paragraph, naming the three bypass surfaces explicitly, cross-referencing `project_agent_llm_cost_attribution_gap.md`, and pointing forward to Phase 4 dashboard cost-visibility work (Option C hybrid helper). Closes Step 9 F6 forward cross-reference. |
| F2 | **`auth.py` plan-vs-code drift — Phase 1 implementation living in a Phase-4-spec'd home.** Live `backend/app/security/auth.py` (125 LOC) shipped at Phase 1 with dual-path (X-API-Key HMAC + Bearer JWT HS256 + UserContext dataclass + Phase 4 JWE migration notes); base plan formally specs auth.py at Task 4.18 (lines 8904-8933) with single-path JWT-only shape. Reviewer rejected my proposed no-action ack: "the forward signal can't live in the audit entry alone — the Phase 4 executor won't be reading the Step 11 entry. Land a one-line note AT Task 4.18: 'auth.py already shipped at Phase 1 (dual-path X-API-Key + HS256 JWT, UserContext, Phase 4 JWE notes inline) — re-scope to EXTEND, not create; see Step 11 audit.' Same lesson as F1: a forward signal has to live where the future reader looks." | **Base plan amended at audit-write time** with a forward note inserted between Task 4.18's header and its "Create `backend/app/security/auth.py`:" instruction. Note flags that auth.py already exists with richer shape + re-scopes the task from "create from scratch" to "extend for Auth.js dashboard integration" + cross-references this Step 11 entry. Mirrors the Step 6/7/8/10 base-plan-amendment pattern. The original spec below the note is preserved as a contract reference for what the dashboard's session-token validation must accept. |

_Engineering touches at this surface: 12 distinct frontier-execution patterns observed (lifespan `_startup_model_ping` Groq-deprecation surveillance with concrete past-incident rationale; `_ensure_master_profile_or_exit` fail-fast first-run guard with hallucination-risk justification; ordered lifespan with documented rationale (DB → profile guard → checkpointer → tools → channels); polling-vs-webhook hard mutex with `delete_webhook` before polling start; CORS `_allowed_cors_origins` locked to TUNNEL_PUBLIC_URL with explicit "wide-open + allow_credentials=True is a safety footgun" rationale; two-tier router pattern with `dependencies=[Depends(get_current_user)]` attached at router level rather than per-endpoint; `/api/_auth/whoami` smoke endpoint returning `{user_id, auth_method}` — verifies both auth paths cleanly; dual-path auth with API-key-first precedence + "mismatched X-API-Key doesn't fall through to JWT — suspicious" guard; auth.py empty-secret deny-all default for both API_SECRET_KEY and AUTH_SECRET; auth.py Phase 4 JWE migration documented inline with two viable swap paths; approvals.py idempotent `resolve_approval` (duplicate Approve click returns existing thread_id without re-writing resolution metadata); gmail webhook `_is_retry_worthy` conservative whitelist with non-retry-worthy default (`return 2xx so Pub/Sub stops retrying` for permanent errors, `503` only for transient infra)) — cited inline at the file:line references in the inventory above._

**Methodology note:** Deeper lens nudge produced 0 net-new findings — all 7 candidates self-dismissed or plan-noted (per-API rate-limiting at Phase 4 Task 4.17; gmail webhook real verifier at Phase 4 Task 4.16; the rest premature/YAGNI). The 2 actionable findings (F1 + F2) came from the smells-scan documentation-drift row. Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset: api/memory.py:20 5th Mem0 site as reaffirm-only in smells row (not promoted to F-row per silence protocol); gmail webhook stub + per-API rate-limiter + correlation-ID + pagination + replay-protection all reaffirmed in deeper-lens pass without F-rows; engineering-touches roll-up presented as compressed italic from the start. F2 disposition revised per reviewer pushback from no-action ack (audit-entry-only) → base-plan amendment at Task 4.18 (where future reader looks). Lesson: forward signals must land where the future executor reads, not only in the audit entry.

**Phase 1 audit closes at Step 11.** Steps 3-11 entries accumulating uncommitted; per-phase commit cadence: Pre-Phase-0 (Steps 1-2, committed) → **Phase 1 (Steps 3-11, awaiting authorization)** → Phase 2 audit (starts Step 12 = Turn 15). Subsequent step numbering re-derived as audit progresses.

**Cross-references:**
- Base plan: Task 1.13 (lines 3993-4074 — gmail webhook half) + Task 1.15 (lines 4123-4294 — Main API Router + Approvals + Health) + Task 1.7 cross-ref (line 1218 — memory.py) + Phase 2 cost dashboard (line 6665 — costs.py)
- Base plan amended at this step: Task 4.18 forward note inserted between header (line 8904) and "Create `backend/app/security/auth.py`:" instruction (now line 8908) — F2 disposition per reviewer
- In-place fix landed at audit-write time: `backend/app/api/costs.py:1-16` docstring extended with 11-line cost-attribution-gap caveat (F1)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: **none**
- MEMORY.md ledger: **no change**
- Backward cross-reference: closes Step 9 F6 forward cross-reference ("costs.py audit at Step 10 or 11 — surface F6 cost-attribution caveat at the right docstring home")
- Forward cross-reference: Phase 4 Task 4.18 executor reads the forward note before following the spec; Phase 4 Task 4.17 owns `app/security/rate_limiter.py` (closes the `_verify_api_key` silent-failure observability gap surfaced in smells row)
- Memory notes referenced (existing, reaffirmed): `project_agent_llm_cost_attribution_gap.md` (informed F1 caveat content), `project_cost_cap_redis_only.md` (re-verified — both readers correctly source-of-truth-separated), `project_oauth_scope_minimization_production_hardening.md` (revocation-handling promoted to Phase 2.5/3 scope post 2026-05-20→24 incident — not Step 11 actionable, separate concern), `project_module_level_mem0_instantiation_smell.md` (5th site reaffirm), `project_gmail_approval_duplicate_race.md` + `project_gmail_handler_decoupling_deferral.md` (gmail webhook→approval landscape; no new finding), `feedback_conversation_agreements_land_in_plan.md` (informs F2 plan-amendment decision)

## Phase 1.5 — Retroactive Foundation Lifts (Backward Audit Output)

> Sub-phase letters (`a` / `b` / `c`) and per-lift numbering assigned at the consolidation step (terminal step of the backward audit) based on dependencies surfaced across all audit steps. Per-lift entries use the Phase 1.5 lift template described above.

### Phase 1.5a-N (slot TBD) — Tool registry MCP descriptor export

**Status:** proposed — surfaced at Step 8 (Turn 10 audit, 2026-05-25). Sub-phase letter expected `a` (descriptor export has no Phase-4-coupling; ships independently of multi-user). Position number assigned at the consolidation step. **First of two sequential Phase 1.5a lifts** split from F3 (the second is Phase 1.5a-N+1 — MCP server endpoint, below).

**Live-code observation:**
- `backend/app/agent/tools/registry.py:248` defines `tool_registry` singleton holding in-process Python tool objects via `_entries: dict[str, _ToolEntry]`.
- `_ToolEntry` (registry.py:45-58) holds name + tool (LangChain StructuredTool) + always_loaded flag + description.
- `register()` method (registry.py:70-101) accepts Pydantic `args_schema` and constructs `StructuredTool.from_function(...)`. Pydantic args_schema gives us JSON Schema via `.model_json_schema()` but isn't exposed externally.
- `ToolEmbedding` table (db/models.py) carries description + embedding + always_loaded flag, but no MCP-compatible descriptor export.
- No `export_mcp_descriptors()` method or equivalent. Tools cannot be enumerated in MCP format by anything outside the registry's own internals.

**Plan-markdown reference** (verbatim quote from base plan, re-verified against current base-plan state at audit-write time 2026-05-25):

Quote from base plan Task 1.11 (lines 3322-3326):

> #### Task 1.11 — Tool Registry (with dynamic embedding-based selection)
>
> > **Two key changes from a vanilla registry:**
> > 1. **LangChain BaseTool format** — LangGraph's `bind_tools()` needs LangChain `Tool` or `StructuredTool` objects, not OpenAI-format dicts. We use `StructuredTool` so Pydantic args schemas drive validation.
> > 2. **Dynamic top-k selection** — every registered tool gets its description embedded once (BGE-M3) and stored in `tool_embeddings`. At each turn, we cosine-search and inject only the top-k relevant tools. Always-loaded tools (memory_search, web_search) bypass the ranking.

The base plan's tool registry is in-process only — MCP-readiness is not mentioned anywhere in Task 1.11 or downstream. **No code-vs-plan drift exists — the plan IS the gap.** MCP is an emerging Anthropic standard (post-plan-authoring); the lift fills a plan-vs-frontier gap.

**Discrepancies surfaced:**
- None between live code and plan markdown — live code matches plan-verbatim in-process tool registry design.
- The actual discrepancy is **plan-vs-frontier**: MCP (Model Context Protocol) emerged as the cross-process tool standard adopted by Anthropic + Cursor + Claude Desktop + an expanding ecosystem. Plan-verbatim doesn't address MCP because the standard didn't exist at plan-authoring time.

**Comparison target:**

Anthropic MCP spec — tool definition shape: `{name, description, inputSchema, outputSchema?}` with JSON Schema-defined input + optional output schemas. Claude Desktop's MCP server tool catalog format; Cursor's MCP integration. All three converge on the same descriptor format.

**Proposed lift:**

Add `tool_registry.export_mcp_descriptors() -> list[dict]` method returning MCP-format tool definitions:

```python
def export_mcp_descriptors(self) -> list[dict[str, Any]]:
    """Export all registered tools as MCP-format tool descriptors.

    Returned shape per descriptor (Anthropic MCP spec):
        {
            "name": str,
            "description": str,
            "inputSchema": dict (JSON Schema from Pydantic args_schema),
        }
    """
    out = []
    for entry in self._entries.values():
        descriptor: dict[str, Any] = {
            "name": entry.name,
            "description": entry.description,
        }
        # StructuredTool's args_schema exposes JSON Schema via Pydantic
        if entry.tool.args_schema is not None:
            descriptor["inputSchema"] = entry.tool.args_schema.model_json_schema()
        out.append(descriptor)
    return out
```

~30-50 LOC including the method, a small dedicated test (`backend/tests/test_tool_registry_mcp_export.py`), and any helper utilities for schema normalization. Useful WITHOUT the server (Phase 1.5a-N+1):
- Phase 3 internal multi-agent handoffs (one Jarvis subgraph exports its tools to another)
- Auto-generated tool documentation (dashboard or README artifact)
- MCP-spec compliance validation (CI assert: every registered tool's descriptor passes MCP schema check)
- Test harness fixtures (mock external MCP clients consuming descriptors)

**Scope exclusions (explicit boundary against scope creep):**
- MCP server endpoint (FastAPI route + discovery metadata + auth model) → **separate Phase 1.5a-N+1 lift below**
- Per-user tool isolation (which tools each MCP client can see) → **Phase 4 multi-user work**
- Tool output schema definition + enforcement → **Phase 3+ work when tool surface evolves beyond strings**; outputSchema field can stay absent in descriptors for now
- MCP capability negotiation (server version, supported MCP spec version) → **part of Phase 1.5a-N+1**

**Verification plan:**
- Unit test: `tool_registry.export_mcp_descriptors()` returns one descriptor per registered tool with `name`, `description`, and `inputSchema` fields populated.
- Schema validation: each descriptor's `inputSchema` is valid JSON Schema (round-trip through `jsonschema` validator).
- MCP spec compliance: descriptors match Anthropic's published MCP tool descriptor shape (named-field check; not full protocol).
- Backward compatibility: existing `tool_registry.execute()`, `select_relevant_tools()`, `all_names()` paths unchanged and continue to work.

**Slot:** `Phase 1.5a-N` (sub-phase letter `a` — no Phase-4-coupling; position number assigned at the consolidation step). Blocks Phase 1.5a-N+1 (MCP server endpoint depends on descriptors). Does NOT block any Phase 2 or Phase 3 work.

**Cross-references:**
- Surfaced at audit step: Step 8 (Turn 10 audit) — see Backward Audit Records section above (F3 split rationale)
- Sibling Phase 1.5a lift: Phase 1.5a-N+1 (MCP server endpoint — sequential dependency)
- Base plan reference: Task 1.11 (lines 3322-3577) — tool registry definition
- Split rationale memory note: `feedback_architectural_units_land_complete.md` — "split at stable interface boundaries"

### Phase 1.5a-N+1 (slot TBD) — Tool registry MCP server endpoint

**Status:** proposed — surfaced at Step 8 (Turn 10 audit, 2026-05-25). Sub-phase letter expected `a` (sibling to N descriptor lift). Position number assigned at the consolidation step. **Second of two sequential Phase 1.5a lifts** split from F3 (depends on Phase 1.5a-N descriptors lift).

**Live-code observation:**
- No MCP server endpoint anywhere in the FastAPI app (verified by grep on `app.api`).
- No discovery metadata for external MCP clients (server name, capabilities, MCP spec version).
- No auth model for external MCP clients (existing auth is FastAPI-side for the dashboard UI; Phase 4 work).
- FastAPI app has `/api/*` routes for dashboard + webhook; no `/mcp/*` routes.

**Plan-markdown reference** (verbatim quote from base plan, re-verified against current base-plan state at audit-write time 2026-05-25):

Same Task 1.11 (lines 3322-3326) quote applies — base plan's tool registry is in-process only; MCP server endpoint is plan-vs-frontier gap, not plan-vs-code drift. Phase 4 auth section (Tasks 4.18 / 4.18b — backend auth + Auth.js v5 integration) is the relevant downstream coupling for this lift's auth model.

**Discrepancies surfaced:**
- None between live code and plan markdown.
- Plan-vs-frontier gap (same shape as Phase 1.5a-N).
- **Phase-4-coupling discrepancy:** the lift's auth model decision is tied to Phase 4 multi-user shape. Landing single-master auth at Phase 1.5a-N+1 risks migration when Phase 4 multi-user lands. Trigger-gated execution accommodates this.

**Comparison target:**

Anthropic's reference MCP server implementations (Python + TypeScript SDKs); Claude Desktop's MCP server pattern (stdio + HTTP transports); Cursor's MCP integration (HTTP-based, OAuth-flow for client auth).

**Proposed lift:**

Two routes + discovery metadata, depending on Phase 1.5a-N descriptors:

```python
# backend/app/api/mcp.py (new file)
from fastapi import APIRouter, HTTPException, Depends
from app.agent.tools.registry import tool_registry

router = APIRouter(prefix="/mcp/v1", tags=["mcp"])


@router.get("/tools/list")
async def list_tools(_auth=Depends(mcp_auth)) -> dict:
    """MCP tools/list endpoint — returns all registered tools as MCP descriptors."""
    return {"tools": tool_registry.export_mcp_descriptors()}


@router.post("/tools/call")
async def call_tool(payload: dict, _auth=Depends(mcp_auth)) -> dict:
    """MCP tools/call endpoint — invoke a tool by name with provided args."""
    name = payload.get("name")
    args = payload.get("arguments", {})
    if not name:
        raise HTTPException(status_code=400, detail="tool name required")
    try:
        result = await tool_registry.execute(name, args)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"content": [{"type": "text", "text": result}]}


@router.get("/")
async def server_metadata() -> dict:
    """MCP discovery metadata — server name, capabilities, MCP spec version."""
    return {
        "name": "jarvis",
        "version": "0.1.0",
        "mcp_version": "2025-03-26",
        "capabilities": {"tools": {}},
    }
```

~100-150 LOC including routes + auth dependency + tests + small integration smoke test.

**Auth model — DEFERRED to lift execution time:**

Auth shape decision depends on Phase 4 multi-user state at execution time. Three candidate shapes documented for execution-time decision:

| Shape | Single-master fit | Multi-user fit | Complexity |
|---|---|---|---|
| Localhost-only (bind to 127.0.0.1) | ✓ — master runs Claude Desktop on same host | ✗ — doesn't scale beyond local | Lowest |
| Static bearer token (env var) | ✓ — share token between Jarvis + Claude Desktop | Partial — single shared token across all clients | Low |
| Per-user OAuth credentials | Overkill | ✓ — proper multi-user isolation | High; depends on Phase 4 auth |

Execution-time decision: pick the shape that matches Phase 4 multi-user state at the moment this lift lands. If Phase 4 hasn't shipped, ship static bearer token; document migration path to per-user OAuth.

**Scope exclusions (explicit boundary against scope creep):**
- Per-tool authorization (which tools each MCP client can call) → **Phase 4 multi-user work**
- MCP transport variations (stdio, WebSocket) → **HTTP-only for this lift**
- MCP `prompts` and `resources` endpoints (beyond `tools`) → **future Phase 3+ lift if real need surfaces**
- MCP server discovery via DNS/mDNS → **infrastructure concern; not in scope**

**Verification plan:**
- External MCP client (test stub OR Claude Desktop) can discover Jarvis tools via `GET /mcp/v1/tools/list`.
- External MCP client can invoke `memory_search` via `POST /mcp/v1/tools/call` with `{"name": "memory_search", "arguments": {"query": "..."}}` and receive a valid response.
- Auth model holds — request without credentials returns 401.
- Discovery metadata `GET /mcp/v1/` matches Anthropic MCP spec.
- Backward compatibility: existing `/api/*` routes unchanged.

**Slot:** `Phase 1.5a-N+1` (sub-phase letter `a` — sibling to N; position number assigned at the consolidation step). **Depends on:** Phase 1.5a-N (Tool descriptor export). **Trigger condition for execution:** real MCP-client use case crystallizes (master wants Jarvis tools accessible from Claude Desktop OR Cursor) OR Phase 3 multi-agent decides on cross-process tool handoffs. **Phase 4 coupling:** auth shape decision pulls in Phase 4 multi-user state; execute after Phase 4 auth has shipped, OR ship static bearer token with documented migration path.

**Cross-references:**
- Surfaced at audit step: Step 8 (Turn 10 audit) — see Backward Audit Records section above (F3 split rationale)
- Sibling Phase 1.5a lift: Phase 1.5a-N (Tool descriptor export — sequential prerequisite)
- Base plan reference: Task 1.11 (lines 3322-3577) — tool registry definition; Phase 4 Tasks 4.18 / 4.18b — backend auth + Auth.js v5 (coupling for auth shape decision)
- Split rationale memory note: `feedback_architectural_units_land_complete.md` — "split at stable interface boundaries"
- Memory notes referenced: none yet — execution-time auth-shape decision will surface relevant notes

### Phase 1.5b-N (slot TBD) — Schema multi-user readiness (add user_id columns + backfill)

**Status:** proposed — surfaced at Step 3 (Turn 4 audit, 2026-05-25). Sub-phase letter expected `b` (pre-Phase-4 lifts, per Explore agent dependency analysis). Position number assigned at the consolidation step.

**Live-code observation:**
- `backend/app/db/models.py:51-297` defines 11 ORM tables; `001_initial_schema.py` migration creates them.
- `UserProfile` (models.py:51-74) uses implicit single-row pattern: `id` PK + `name` + `always_on` + `on_demand` JSONB columns. No row-per-user shape; the table IS the master user table, designed as single-master.
- **The following 9 tables lack a `user_id` column** linking writes to a specific user: `AuditTrail` (models.py:161), `LLMUsageLog` (models.py:180), `MemoryEpisode` (models.py:100), `PendingApproval` (models.py:120), `ConversationAnalytics` (models.py:80), `EmailLog` (models.py:142), `DocumentChunk` (models.py:200), `ToolResult` (models.py:227), `RateLimitEvent` (models.py:270).
- `ToolEmbedding` (models.py:246) is system-wide — tool embeddings are per-tool, not per-user. **Excluded from migration scope.**

**Plan-markdown reference** (verbatim quote from base plan, re-verified against current base-plan state at audit-write time 2026-05-25):

Quote from base plan Task 1.4 (lines 1342-1369) — load-bearing snippet for the single-master schema framing; full model continues with `always_on` / `on_demand` JSONB columns + `updated_at` not quoted here:

> ```python
> class UserProfile(Base):
>     """Tier 5 — Master's preferences. Split into always-on (small, in every prompt)
>     and on-demand (loaded only when relevant via Mem0)."""
>     __tablename__ = "user_profiles"
>
>     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
>     name = Column(String(255), nullable=False)
>     # [truncated — full model: always_on JSONB, on_demand JSONB, updated_at; see base plan lines 1342-1369]
> ```

The base plan's schema design is single-master throughout. Phase 4 multi-user (Tasks 4.13+ — non-master intent routing + Auth.js v5 integration) is documented in the plan but does not touch schema. **No code-vs-plan drift exists — the plan IS the gap.** This lift fills a gap the base plan never addressed.

**Discrepancies surfaced:**
- None between live code and plan markdown — live code matches plan-verbatim schema design.
- The actual discrepancy is **plan-vs-frontier**: schema design assumes Phase 4 multi-user can be retrofitted via code, but it cannot — schema-level `user_id` is a hard requirement for any multi-user query, write, or row-level security pattern.

**Comparison target:**
Any production SaaS backend supporting multi-tenancy at the row level (Django apps with `belongs_to user`, Rails apps with `acts_as_tenant`, Supabase Row Level Security patterns). Standard frontier shape: every user-scoped table has a `user_id` foreign key + queries default-scoped to current user. Current state is single-user-only; lift brings the schema to standard multi-tenant shape (code-level enforcement deferred to Phase 4 per scope split below).

**Proposed lift (schema-only):**

New Alembic migration (numbered `003` or appropriate sequential prefix at execution time, after verifying base plan's `003_email_tables` numbering hasn't already shipped — verify with `\dt` against the running DB before migration creation):

1. Resolve / generate master_user_id: read `user_profiles.id` of the existing master row, or generate one if no row exists.
2. For each of the 9 user-scoped tables:
   - `op.add_column(<table>, sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))`
   - `op.execute(f"UPDATE {table} SET user_id = '{master_uuid}'")` — backfill all rows
   - `op.alter_column(<table>, "user_id", nullable=False)` — promote to NOT NULL once backfilled
   - `op.create_index(f"ix_{table}_user_id", table, ["user_id"])`
3. ORM model updates: add `user_id = Column(UUID(as_uuid=True), nullable=False)` to each of the 9 model classes.
4. `UserProfile` unchanged — its row-per-user expansion is Phase 4 work, not Phase 1.5b.
5. `ToolEmbedding` unchanged — system-wide, no user scoping needed.
6. FK constraints (`user_id` → `user_profiles.id`) **deferred** — added when Phase 4 lifts UserProfile to row-per-user.
7. Downgrade: drop indexes + drop columns.

**Downstream impact on plan-numbered migrations — verify at lift-execution time:**

This lift adds a new Alembic migration with sequential prefix. Several plan-numbered migrations downstream may need renumbering (or are no-ops) depending on execution order. **Verify against the live `alembic/versions/` directory + running DB (`\dt`) before creating the migration file.** Current state:

| Plan reference | Promised number | Live state | If this lift lands first |
|---|---|---|---|
| Task 2.12 (`003_email_tables`) | `003_` | **No-op** per `project_phase1_monolithic_migration.md` (email_logs already in `001_initial_schema`) | No conflict — Task 2.12 produces no migration anyway |
| Task 2.16b (`004_documents`) | `004_` | **No-op** per `project_phase1_monolithic_migration.md` (document_chunks already in `001_initial_schema`) | No conflict — Task 2.16b produces no migration anyway |
| Turn 17.8 close-out (`004_email_logs_meta`) | `004_` (per plan slot) | Not yet executed; **real** migration (adds `meta` JSONB column) | **CONFLICT** — must renumber to `004_` (if this lift takes `003`) or whatever sequential prefix is next available at Turn 17.8 execution time |
| Turn 17.9 close-out (`005_audit_trail_latency`) | `005_` (per plan slot) | Not yet executed; **real** migration (adds `latency_ms` column) | **CONFLICT** — same shape; renumber sequentially |
| Phase 3 Task 3.10 (`005_browser_audit`) | `005_` | Not yet executed; **real** migration (adds browser_actions table) | **CONFLICT** — same shape; renumber sequentially |
| Phase 4 Task 4.11b (`006_messaging_tables`) | `006_` | Not yet executed; **real** migration (adds whatsapp_window_state) | **CONFLICT** — same shape; renumber sequentially |

When executing this lift, **first verify** what migrations have actually shipped (`ls backend/alembic/versions/`), pick the next sequential prefix for THIS lift's migration, and **update the affected plan slots' migration numbering** (in `jarvis-implementation-plan.md` + relevant close-out turn entries in this upgrade doc) to reflect the new sequence. Don't rely on plan-stated numbers at execution time — they're intent claims, not guarantees.

**Scope exclusions (explicit boundary against scope creep):**
- Code-level write-path changes (passing `user_id` through writers) → **Phase 4 implementation work, not Phase 1.5b**
- FK constraints `user_id` → `user_profiles.id` → **Phase 4 (after UserProfile becomes row-per-user)**
- Query-default-scoping to current user → **Phase 4**
- Auth.js v5 session integration providing real user_id → **Phase 4 (Tasks 4.18 / 4.18b)**
- Mem0Client `USER_ID = "master"` hardcoded refactor → **separate Phase 1.5b lift** (will surface at Step 5 audit of Turn 6 — Memory layer; same sub-phase, different surface, different testing pattern)

This lift is **schema-only**: gets `user_id` columns in place + backfilled so Phase 4 implementation has a foundation to write against without further migrations during feature work.

**Verification plan:**
- Migration runs against test DB with seeded multi-row data; backfill UPDATE sets all rows to master_uuid; alter_column-to-NOT-NULL succeeds.
- Schema inspection (`\d+ <table>`) shows `user_id UUID NOT NULL` with index after migration, for all 9 tables.
- Migration downgrade restores pre-migration schema cleanly (idempotent up/down round-trip).
- Existing app code paths (Phase 1-2 functionality) continue to work — writers must SET user_id to master_uuid (lift includes minimal writer-side change: throwaway `user_id=master_uuid` default on all inserts; removed when Phase 4 wires real user_id from session).
- Re-run existing Phase 1 test suite — all tests pass against the new schema.

**Slot:** `Phase 1.5b-N` (sub-phase letter + position number assigned at the consolidation step). Blocks Phase 4 (specifically Tasks 4.13+ non-master intent routing + 4.18 Auth.js integration + 4.18b Auth.js v5 frontend).

**Cross-references:**
- Surfaced at audit step: Step 3 (Turn 4 audit) — see Backward Audit Records section above
- Sibling Phase 1.5b lift: Mem0Client USER_ID multi-user readiness (Step 5 audit — see lift entry below)
- Base plan reference: Task 1.4 (lines 1342-1367) — UserProfile model definition
- Memory notes: `project_phase1_monolithic_migration.md` (monolithic migration context — this lift adds a new migration on top of the monolithic baseline)
- Blocks: Phase 4 Tasks 4.13 (non-master intent routing), 4.14 (auto-responder), 4.18 (backend auth), 4.18b (frontend Auth.js v5)

### Phase 1.5b-N (slot TBD) — Mem0Client USER_ID multi-user readiness (wrap approach)

**Status:** proposed — surfaced at Step 5 (Turn 6 audit, 2026-05-25). Sub-phase letter expected `b` (pre-Phase-4, sibling to Step 3's F1 schema lift). Position number assigned at the consolidation step.

**Live-code observation:**
- `backend/app/memory/mem0_client.py:89` declares `USER_ID = "master"` as a class-level constant.
- Used at:
  - `mem0_client.py:112` — `add()` passes `user_id=self.USER_ID` to `self.client.add(...)`
  - `mem0_client.py:126` — `search()` passes `filters={"user_id": self.USER_ID}`
  - `mem0_client.py:140` — `get_all()` passes `filters={"user_id": self.USER_ID}`
- All three method signatures (`add`, `search`, `get_all`) take their effective user scope from the class constant; no caller can override.
- `MemoryManager` (manager.py) facade methods (`build_context`, `persist_turn`, `recall`, `thread_summary`) likewise have no user_id parameter — they implicitly target the master via Mem0Client's class const.

**Plan-markdown reference** (verbatim quote from base plan, re-verified against current base-plan state at audit-write time 2026-05-25):

Quote from base plan Task 1.7 (lines 2103-2135) — load-bearing snippet for the single-master Mem0Client framing; full class continues with add/search/get_all/delete methods all using `self.user_id`:

> ```python
> class Mem0Client:
>     """Wraps Mem0 in self-hosted mode — all data stays in your pgvector."""
>
>     def __init__(self):
>         # [truncated — config builder; see base plan lines 2105-2132]
>         self.client = Memory.from_config(config)
>         self.user_id = "master"  # Single-user system
>     # [truncated — add/search/get_all/delete methods all pass user_id=self.user_id; see base plan lines 2136-2180]
> ```

The base plan's Mem0Client design is single-master throughout. Phase 4 multi-user (Tasks 4.13+) does not touch the Mem0 layer. **No code-vs-plan drift exists — the plan IS the gap.** Same shape as Step 3's F1. (Minor evolution: plan said instance attribute `self.user_id`; live code uses class constant `USER_ID`. Functionally equivalent.)

**Discrepancies surfaced:**
- None between live code and plan markdown — live code matches plan-verbatim single-master pattern.
- The actual discrepancy is **plan-vs-frontier**: same as Step 3's F1 schema lift.

**Comparison target:**
Any multi-tenant memory framework. Mem0 IS already designed for multi-user — its `user_id` parameter on add/search/get_all is first-class API. The lift just uncovers existing multi-tenancy support that the wrapper hardcoded away. LangChain's `BaseMemory` similarly supports per-user scope. Current state is the only "single-user" thing about Mem0 in our stack; the framework supports multi-user natively.

**Proposed lift (code-only — wrap approach):**

Add `user_id` parameter to each Mem0Client method, defaulting to a module-level constant for backward compatibility during the transition:

```python
# mem0_client.py
DEFAULT_USER_ID = "master"   # transition default; Phase 4 wiring removes the default

class Mem0Client:
    async def add(
        self,
        content: str,
        user_id: str = DEFAULT_USER_ID,        # <-- NEW
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        ...
        return await self.client.add(
            messages=[{"role": "user", "content": content}],
            user_id=user_id,                   # <-- was self.USER_ID
            metadata=meta,
        )

    async def search(self, query: str, top_k: int = 10, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        results = await self.client.search(
            query=query,
            top_k=top_k,
            filters={"user_id": user_id},      # <-- was self.USER_ID
        )
        ...

    async def get_all(self, user_id: str = DEFAULT_USER_ID) -> list[dict[str, Any]]:
        results = await self.client.get_all(filters={"user_id": user_id})
        ...
```

MemoryManager facade methods get the same `user_id` parameter pass-through:

```python
# manager.py
async def build_context(self, user_message: str, user_id: str = DEFAULT_USER_ID) -> dict[str, Any]:
    ...
    relevant = await self.mem0.search(query=user_message, top_k=10, user_id=user_id)
    ...
```

**Design fork considered: factory approach (rejected with rationale):**

Alternative: lift to per-user `Mem0Client` instances via a factory function (`get_mem0_client(user_id) -> Mem0Client` with LRU caching for instance reuse).

| | Wrap approach (chosen) | Factory approach (rejected) |
|---|---|---|
| LOC | ~20 | ~100 |
| Shape | Additive, parameterized | Restructured, lifecycle-managed |
| Symmetry with Step 3 F1 (schema lift) | Strong — both additive/parameterized | Weak — restructure pattern |
| Mem0 isolation benefit | N (multi-tenancy already in Mem0 via user_id filter; per-instance creates N connections to SAME backend) | None real (same as wrap) |
| Per-user config differences (e.g., different embedder per user) | Not supported (acceptable — no current need) | Speculatively supported |
| Lifecycle complexity (LRU cache, eviction, connection pool) | None | Real |

**Verdict:** wrap approach. Factory adds real complexity for marginal benefit; if per-user config differences ever surface as a real need, factory can layer on top of the wrapped methods later as a separate lift. Symmetric with Step 3's schema F1 (parameterize, don't restructure).

**Scope exclusions (explicit boundary against scope creep):**
- Code-level write-path wiring (`run_turn(user_message, thread_id, ..., user_id=request.user_id)` flowing through to `MemoryManager.build_context(user_id=...)`) → **Phase 4 implementation work, not Phase 1.5b**
- Auth.js v5 session integration providing real user_id → **Phase 4 (Tasks 4.18 / 4.18b)**
- Per-user Mem0Client instance factory → **explicitly rejected** (see Design fork above; factory can be a separate future lift if real need surfaces)
- Per-user config differences (different embedder/extraction-LLM per user) → **future polish lift if/when real need surfaces**
- Schema-level `user_id` columns on `memory_episodes` table → **separate concern, scoped under Step 3 F1 schema lift**

**Verification plan:**
- Mem0Client method signature inspection — `add` / `search` / `get_all` all have `user_id: str = DEFAULT_USER_ID` parameter
- MemoryManager facade methods (`build_context`, `recall`, `thread_summary`) likewise have `user_id` pass-through
- Existing Phase 1-2 code paths continue to work without modification (default value handles transition)
- New test: `await mem0.add("fact A", user_id="user_a")` + `await mem0.add("fact B", user_id="user_b")` then `await mem0.search("fact", user_id="user_a")` returns only fact A (verifies user_id propagates as filter scope; verifies isolation between users)
- Existing Phase 1 test suite passes unchanged

**Slot:** `Phase 1.5b-N` (sub-phase letter + position number assigned at the consolidation step). Sibling lift to Step 3's F1 (schema multi-user). Both Phase 1.5b; ordering decided at the consolidation step (likely schema first, then code-level Mem0 wrap; but the consolidation step confirms).

**Cross-references:**
- Surfaced at audit step: Step 5 (Turn 6 audit) — see Backward Audit Records section above
- Sibling Phase 1.5b lift: Step 3 F1 (schema multi-user readiness)
- Base plan reference: Task 1.7 (lines 2103-2135) — Mem0Client class definition
- Memory notes referenced: `project_module_level_mem0_instantiation_smell.md` (related caller-side smell — separate concern, not in scope here)
- Blocks: Phase 4 Tasks 4.13 (non-master intent routing), 4.14 (auto-responder), 4.18 (backend auth), 4.18b (frontend Auth.js v5)

_(populated by all audit steps; consolidated at the consolidation step)_

## Retroactive Turn Entries (Turn 18 onward)

> Per-turn entries for turns that applied frontier discipline at design time. Documentation-only — code already committed; entries capture the lens-application reasoning for future readability.

_(populated by Steps 20 and 22)_
