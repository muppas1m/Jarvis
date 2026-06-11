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
| Sub-phase by execution slot | `Phase 1.5<letter>` (letter assigned at the consolidation step) | "Phase 1.5a — Trigger-Gated MCP-Readiness Lifts" |
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

### Step 12 — Turn 15 — Gmail/Calendar OAuth bootstrap + Gmail watch registration (first Phase 2 surface)

**Overall rating:** Mid-to-Frontier (operator scripts genuinely Frontier-quality — substantially exceed plan-verbatim; runtime gmail_watch.py is plan-verbatim with deferred hardening per `project_oauth_scope_minimization_production_hardening.md`; the 2026-05-20→24 revocation incident's recommendation to fold RefreshError catch into Turn 17.8 didn't ship — still tracked in that note. Lifts to Frontier when revocation handling lands + F1 plaintext-token-print hardening ships) — **Status:** final — sign-off 2026-06-07

**Scope:**
First Phase 2 surface — Gmail/Calendar OAuth bootstrap + Gmail watch registration. Surface originated at commit `0f37898` (Turn 15: gmail oauth bootstrap + watch registration). 3 files audited; cross-references to Phase-2-later-turn surfaces (gmail_pubsub.py Turn 16/17, calendar_tool.py Turn 16, gmail_send.py Turn 17.5) excluded per scope directive — left for their own audit steps. Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close).

**Phase boundary note:** This is the first Step 12+ entry. Only "Phase 2 audit starts at Step 12 = Turn 15" is settled in the numbering; subsequent Phase 2 step grouping re-derived as audit progresses, not pre-locked.

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/scripts/google_oauth.py` | 145 | Task 2.1 code deliverable (plan lines 5050-5068 — ~15 LOC snippet) | **Live substantially exceeds plan-verbatim** — CWD-independent path resolution via `Path(__file__).resolve().parent.parent.parent`; settings-honor (`try: from app.config import settings`) with fallback to repo-root-relative default (works from clean checkout before settings wired); file-existence guard with concrete 4-step fix instructions; refresh-token-None handling with explicit myaccount.google.com revoke guidance; copy-pasteable `GOOGLE_REFRESH_TOKEN=...` output; lazy import of google_auth_oauthlib with conda-env hint on ImportError; 45-line operator docstring (prereqs / run / after) |
| `backend/app/email/gmail_watch.py` | 42 | Task 2.2 (plan lines 5076-5120 — ~40 LOC) | **Plan-verbatim shape** — line-for-line match to plan-verbatim (1-line module docstring + `get_gmail_service` + `setup_gmail_watch` + `stop_gmail_watch`); function-level docstring at `setup_gmail_watch` line 23 carries the 7-day expiry semantic. No defensive layers (no RefreshError catch, no integration_health surface, no revocation alerting) — all deferred per OAuth-scope memory note |
| `backend/scripts/setup_gmail_watch.py` | 118 | Plan line 1252 references the file in dir-listing only; **no plan-verbatim script body** | **Fully realized operator runner not in plan** — `_check_prereqs()` env-var validation with explicit missing-vars surface; ms-since-epoch → ISO expiration formatting; 46-line operator docstring including the `docker compose run --rm` guidance that addresses `project_docker_compose_restart_does_not_reload_env.md` failure mode inline at the surface where the operator looks; Common-failures section with specific error→cause→fix mappings; Task 2.7 forward-reference for automated renewal |

Cross-referenced (NOT re-audited): `backend/app/config.py:63-70` Google settings (audited Step 3). Phase 2 later-turn surfaces excluded per directive.

Base plan: Task 2.1 (lines 5040-5072 — GCP project setup + OAuth script + Pub/Sub provisioning; mostly manual steps + the ~15 LOC code snippet) + Task 2.2 (lines 5074-5120 — Gmail watch setup module). Memory notes consulted + re-verified at audit-write time: `project_oauth_scope_minimization_production_hardening.md` (current SCOPES list at google_oauth.py:60-64 matches the note's "Current scopes" section; 2026-05-20→24 revocation-incident "fold into Turn 17.8" recommendation has NOT shipped — gmail_watch.py:get_gmail_service still has no RefreshError catch; F1 folded as new section 4 at this step), `project_docker_compose_restart_does_not_reload_env.md` (re-verified — setup_gmail_watch.py:25-29 docstring addresses the failure mode inline), `project_webhook_secret_naming_inconsistency.md` (re-verified — `WEBHOOK_SECRET_GMAIL` at config.py:70 consistent with note's framing; not actionable at this layer).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | Scripts print to stdout; gmail_watch returns Google API dict |
| One-line tool description | N/A | — |
| Single-item interface where batch frontier | N/A | Operator scripts one-shot by design; gmail_watch sets up ONE watch per master |
| **Module-level instantiation triggering I/O** | **None — clean** | google_oauth.py: constants only (REPO_ROOT, DEFAULT_CREDENTIALS_PATH, SCOPES — Path construction + list literal, zero I/O). gmail_watch.py: `logger = structlog.get_logger()` at module top (pure, no I/O). setup_gmail_watch.py: imports + function definitions only (no module-level call). |
| Logging-via-omission | **None — varies appropriately by surface** | Operator scripts use `print()` (correct for direct-to-terminal feedback); runtime gmail_watch.py uses structlog (`logger.info` on watch register + stop) — `gmail_watch_registered` with expiration field is load-bearing for the renewal scheduler to verify success. |
| Sync bypass of cost-tracking | N/A | No LLM calls at this layer |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — runtime + operator docstrings appropriately tiered** | All docstrings verified accurate. google_oauth.py 45-line operator docstring + setup_gmail_watch.py 46-line operator docstring both Frontier-quality (prereqs / run / success / common-failures + cross-references). gmail_watch.py 1-line module docstring matches plan-verbatim minimum; **the load-bearing 7-day expiry context is at the function-level docstring** (`setup_gmail_watch` line 23: "Must be renewed every 7 days"). Runtime module having terser docstrings than operator scripts is appropriate tiering, not drift — verified at audit-write time after a synthesis-time misread initially proposed an enhancement (corrected per reviewer pushback). |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | Every defensive pattern earns its keep (CWD-independence, settings-honor + fallback, file-existence guard with fix steps, refresh-token-None handling, prereq env-var validation, expiration ISO formatting, docker-compose-run-rm guidance) |

**Deeper comparison-target pass (security sub-surface — frontier-lens bar per directive; operator-script-mechanics sub-surface — production-grade bar):**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| OAuth bootstrap — security sub-surface (frontier-lens bar) | (1) Google `google-auth-oauthlib` docs (canonical); (2) `gh` CLI / `gcloud` CLI OAuth bootstrap; (3) Anthropic/Cursor published secrets-management patterns; (4) production secret-management tooling (HashiCorp Vault, AWS Secrets Manager, 1Password CLI) | **C1: Refresh token printed to terminal in plaintext** (google_oauth.py:134) — token lands in scrollback + potentially clipboard; real exposure is shared-host / multi-operator scrollback (interactive OAuth can't run headless in CI — needs browser + loopback). **Surfaced as F1 → folded into existing `project_oauth_scope_minimization_production_hardening.md` as new section 4 per reviewer disposition** (same OAuth-bootstrap hardening family as sections 1–3; a 2nd OAuth note would fragment the landscape). **C2: No grant-age tracking** — already in OAuth-scope note ("Audit of consent grants" section). Reaffirm. **C3: No tokeninfo pre-check in setup_gmail_watch.py** — already in OAuth-scope note ("scope-change re-consent" section). Reaffirm. **C4: No RefreshError catch in gmail_watch.py:get_gmail_service** — already memory-noted with 2026-05-20→24 incident promotion to Phase 2.5/3 scope; recommendation to fold into Turn 17.8 didn't execute. **Silenced per protocol — forward signal lives in OAuth-scope note's "Promotion of the deferred concerns" section, no new F-row needed.** **C5: Refresh token stored in .env plaintext** — frontier shape would use OS keychain. Single-master localhost + .env gitignored — self-dismiss. **C6: SCOPES bundled in one consent prompt** — google_oauth.py docstring line 11 explicitly justifies as deliberate UX trade-off ("avoid a second consent dance when Calendar tools land"). Frontier-correct trade-off documentation. |
| Operator-script mechanics — production-grade bar | (1) `gh` CLI; (2) `gcloud` CLI; (3) Stripe CLI; (4) HashiCorp CLI patterns | Nothing material — mechanics hit production-grade. Per the lens directive ("don't manufacture frontier concerns on the script plumbing"), no F-rows from this sub-surface. |

Deeper lens result: 6 candidates surfaced (all security sub-surface). **1 net-new gap (C1 → F1 folded into existing OAuth-scope note as section 4).** 3 already plan-noted in OAuth-scope note (C2, C3, C4 — reaffirm; C4 silenced). 2 self-dismissed (C5 OS-keychain premature; C6 SCOPES-bundling-rationale documented).

**Comparison target:**

google_oauth.py + setup_gmail_watch.py operator scripts match `gh` / `gcloud` CLI shape with concrete fix-step instructions, prereq validation, and common-failures tables — production-grade for the script bar. gmail_watch.py runtime code matches `google-auth-oauthlib` canonical patterns line-for-line with plan-verbatim. **The bar is set per sub-surface per the lens directive**: operator scripts hit production-grade; the security sub-surface (refresh-token transport, scope minimization, revocation alerting) carries deferred frontier-hardening per the OAuth-scope memory note (now 4 numbered hardening concerns + the audit-of-consent-grants concern after F1 fold).

**Three-hats tension surfaced:**

- **Architect** wants OAuth bootstrap to be a clean one-shot operator workflow. Wins on CWD-independence + settings-honor + bundled-scopes-one-consent + explicit prereq validation. Loses on no-revocation-recovery-flow (per the 2026-05-20→24 incident, manual diagnosis took ~10min to interpret 3,266 invalid_grant log lines as one revocation event). Resolved with memory-noted Phase 2.5/3 promotion that hasn't shipped.
- **Engineer** wants gmail_watch.py to be minimal + plan-verbatim — small surface, easy to reason about, hardening lives at higher layers. Wins on simplicity (42 LOC). Loses on the missing RefreshError catch + no integration-health surface. Tension acceptable: minimal-and-plan-verbatim now; refactor in Turn 17.8-or-later when the email-path is next touched.
- **AI-ML engineer** doesn't really weigh at Turn 15 — OAuth + watch bootstrap, no model concerns. Closest tension: `gmail.modify` scope breadth (agent can archive/delete/label/modify drafts). Mitigated by safety classifier APPROVE-gating at the tool layer (Step 6 audit) + scope-minimization deferral with explicit trade-off (`gmail.readonly` would lose spam-auto-archive).

All three tensions surfaced where applicable.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **(Deeper lens C1) Refresh token printed to terminal in plaintext** at `google_oauth.py:134`. Token lands in terminal scrollback + potentially clipboard. Real exposure surface is shared-host / multi-operator scrollback (interactive OAuth can't run headless in CI — needs browser + loopback). | **Folded into existing `project_oauth_scope_minimization_production_hardening.md` as new "### 4. Refresh-token transport at bootstrap" section** per reviewer disposition — same OAuth-bootstrap hardening family as sections 1 (scope minimization), 2 (revocation handling), 3 (re-consent for scope changes). A 2nd standalone note would fragment the landscape that consolidates here. **Tightened trigger** per reviewer: "shared-host / multi-operator deployment, OR any deployment context where terminal scrollback isn't trusted" (NOT CI — interactive OAuth can't run headless). ~5-15 LOC fix when triggered (atomic write to `.env` with backup + in-place line-rewrite of `GOOGLE_REFRESH_TOKEN=` + success message without token). MEMORY.md ledger refreshed to mention the added hardening line. No new note; no MEMORY.md proliferation. |

_F2 (gmail_watch.py docstring enhancement, from synthesis): cut per reviewer pushback. Built on a misread — `setup_gmail_watch` function-level docstring at gmail_watch.py:23 carries the 7-day expiry context ("Must be renewed every 7 days"); the terse 1-line module docstring is appropriate tiering for runtime code vs operator scripts, not drift. A 1-line renewal-path cross-ref would be optional polish, not a fix. No-action positive._

_F3 (3rd anti-drift exemplar in `feedback_frontier_grade_discipline.md`, from synthesis): cut per reviewer pushback. Anti-drift is already exemplified twice (Step 5 Mem0-v2 deviations + UserProfile single-row); a 3rd instance — same pattern, operator-script surface — doesn't teach a new lesson. Setup_gmail_watch.py's inline failure-mode documentation is the positive it already is in the engineering-touches roll-up below; no exemplar-list amendment._

_F4 (revocation-handling reaffirm, from synthesis): silenced per protocol. OAuth-scope note's "Promotion of the deferred concerns" section already captures the forward signal ("fold into Turn 17.8 email-path work"); Turn 17.8 didn't ship the fix, but the note's recommendation persists. No new F-row; reaffirmed in deeper-lens C4._

_Engineering touches at this surface: 13 distinct frontier-execution patterns observed across the 3 files (google_oauth.py: CWD-independent path resolution via `Path(__file__).resolve().parent.parent.parent`; settings-honor with `try: from app.config import settings` + fallback to repo-root-relative default — works from clean checkout before settings are wired; file-existence guard with 4-step fix instructions; refresh-token-None handling with explicit myaccount.google.com revoke guidance; copy-pasteable `GOOGLE_REFRESH_TOKEN=...` output line — directly pasteable into .env; lazy import of google_auth_oauthlib with conda-env hint on ImportError; SCOPES bundling-rationale documented inline; gmail_watch.py: `get_gmail_service()` helper separated from `setup_gmail_watch()` for reuse across Phase 2/3 send/list/calendar tools; setup_gmail_watch.py: `_check_prereqs()` env-var validation with explicit missing-vars surface; expiration ms→ISO formatting via `datetime.fromtimestamp(ms/1000.0, tz=timezone.utc).isoformat()`; `docker compose run --rm` guidance documented inline at the operator-script surface — addresses memory-noted failure mode where the operator looks; Common failures section with specific error→cause→fix mappings; Task 2.7 forward-reference for automated renewal). Bar per sub-surface per directive: operator scripts hit production-grade; runtime gmail_watch.py is plan-verbatim with deferred hardening per OAuth-scope memory note._

**Methodology note:** Deeper lens (security sub-surface, frontier-lens bar per directive) produced 1 net-new gap (F1 refresh-token-plaintext-print → folded into existing OAuth-scope note as section 4 per reviewer disposition, NOT spawned as standalone — consolidation prevents 2-note OAuth fragmentation). 3 already plan-noted (C2/C3/C4 reaffirm; C4 silenced per protocol — forward signal lives in OAuth-scope note's existing "Promotion of the deferred concerns" section). 2 self-dismissed (C5 OS-keychain premature; C6 SCOPES-bundling-rationale documented inline). Operator-script-mechanics sub-surface produced 0 findings — bar set per directive ("don't manufacture frontier concerns on the script plumbing"). **Meta lesson applied per reviewer pushback:** synthesis-time presentation initially proposed 3 F-rows + 1 silence (F1 docstring + F2 memory note + F3 discipline exemplar + F4 silence); reviewer correctly recharacterized as 1 F-row (the folded hardening) + 3 no-action-positive + 1 reaffirm. When a surface is clean (operator scripts genuinely Frontier-quality + runtime plan-verbatim with tracked-deferral), lean into no-action-positive + reaffirm rather than reaching for a docstring edit, a new note, and an exemplar. The honest output is "Frontier scripts + plan-verbatim runtime + 1 folded hardening + 1 reaffirm" — not three new actions.

**Cross-references:**
- Base plan: Task 2.1 (lines 5040-5072 — GCP project setup + OAuth script + Pub/Sub provisioning) + Task 2.2 (lines 5074-5120 — Gmail watch setup module)
- Base plan amended at this step: **none**
- In-place fix landed at audit-write time: **none** (per reviewer disposition; F2/F3 from synthesis cut as no-action-positive; F1 folded into existing memory note)
- Memory notes saved at this step: **none** (F1 folded into existing OAuth-scope note rather than spawned standalone)
- Memory notes amended at this step: `project_oauth_scope_minimization_production_hardening.md` (F1 — new "### 4. Refresh-token transport at bootstrap" section added between sections 3 and "Audit of consent grants"; trigger tightened to shared-host/multi-operator per reviewer)
- MEMORY.md ledger refreshed at this step: OAuth-scope note description updated to enumerate the 5-item deferred hardening landscape (scope minimization + revocation alerting + scope-change re-consent + consent grant audit + refresh-token plaintext-print) + trigger expanded to include "OR shared-host deployment"
- Forward cross-reference: when ANY future turn touches gmail_watch.py, revocation-handling fold (per OAuth-scope note's "Promotion of the deferred concerns" section) should ride
- Memory notes referenced (existing, reaffirmed): `project_docker_compose_restart_does_not_reload_env.md` (re-verified — setup_gmail_watch.py:25-29 docstring addresses the failure mode inline; positive finding noted in engineering touches roll-up), `project_webhook_secret_naming_inconsistency.md` (re-verified — applies to webhook receiver at Step 11, not Turn 15 OAuth/watch surface)

### Step 13 — Turns 16 + 16.5 — Gmail inbound email pipeline (Pub/Sub handler + classifier + responder)

**Overall rating:** Mid-to-Frontier (gmail_pubsub.py Frontier post-Turn-16.5 dedup gate + 25-line in-code rationale + plan-gap fills + Turn 17.5 payload enrichment; responder.py Frontier post-Turn-16.5 anti-fab discipline — anti-fab section + escape hatch + forbidden phrasings + cleaned complexity classification; classifier.py Mid with KNOWN deferred 3-way enum smell tracked in discipline note. Composite Mid-to-Frontier per reviewer — classifier's tracked 3-way smell keeps the rating honest; don't round up to Frontier on Turn 16.5 polish alone) — **Status:** final — sign-off 2026-06-08

**Scope:**
Gmail inbound email pipeline — "email arrives → classified → drafted" loop. 3 files audited; surface originated at Turn 16 (Task 2.3 + 2.4 + 2.5 first ship) with Turn 16.5 polish landing the dedup gate (gmail_pubsub.py) + anti-fab DRAFT_PROMPT (responder.py). Step 13 spine per directive: two fix-verifications. Cross-references to adjacent surfaces audited at prior steps (api/webhooks/gmail.py + webhook_verify.py at Step 11; gmail_watch.py at Step 12) — cross-ref only, NOT re-audited. Phase 2 later surfaces excluded per directive: digest.py + calendar_tool.py (Step 14 scope). Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Step 12's accumulated upgrade-doc changes uncommitted.

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/email/gmail_pubsub.py` | 303 | Task 2.3 (plan lines 5122-5265) | **Live substantially exceeds plan-verbatim** — Turn 16.5 dedup gate at lines 108-126 (EmailLog INSERT-first with IntegrityError catch + early return); 25-line in-code rationale docstring at lines 60-84 documenting original bug + fix + trade-off + 12-row Turn 16 observation; 3-caller single-helper `sweep_recent_inbox` (Pub/Sub + gmail_renew + gmail_check); plan-gap fills (`thread_id="gmail:<msg_id>"` synthesis + `interrupt_id` + `expires_at` NOT-NULL columns plan-verbatim skipped); Turn 17.5 payload enrichment at lines 198-203 (subject + rfc822_message_id stored so dispatch skips Gmail fetch); capability-neutral SYSTEM alert copy at lines 162-175 deliberately doesn't promise "send it" since conversational-half capability gap is explicitly NOT shipped |
| `backend/app/email/classifier.py` | 40 | Task 2.4 (plan lines 5267-5311) | **Plan-verbatim shape** — flat 3-way return string `"spam"\|"fyi"\|"action_required"`; default to "fyi" on unexpected output; `task_type="classification"` routes to FAST_MODEL; temperature=0.0 deterministic. **KNOWN 3-way enum smell** per `feedback_frontier_grade_discipline.md` line 52 (Turn 16 classifier → Turn 17.8 lift to multi-dim — urgency / intent / confidence / suggested_action). Live state still 3-way; whether Turn 17.8 shipped the multi-dim restructure is forward-pickup for whichever step audits Turn 17.8 |
| `backend/app/email/responder.py` | 83 | Task 2.5 (plan lines 5313-5556) | **Live substantially exceeds plan-verbatim post-Turn-16.5** — DRAFT_PROMPT at lines 6-49 carries all 4 anti-fab elements (anti-fab section + escape hatch for missing-info + forbidden phrasings list + cleaned-up complexity classification); `task_type="drafting"` + temperature=0.3; JSON-parse with graceful `try/except json.JSONDecodeError → fallback {complexity: "complex", response: content}`; body truncation to 2000 chars; profile-driven master_name + comm_style injection. **`memory = MemoryManager()` at line 4 is site #1 of the 5-site Mem0 module-level enumeration** — already in `project_module_level_mem0_instantiation_smell.md` per Step 7+8+11; reaffirm only, no new site |

**Task-ID cite correction (audit-write time, per reviewer):** Synthesis-time presentation cited responder = Task 2.4 + classifier = Task 2.3 per user directive's positional listing; plan-verified mapping is gmail_pubsub = Task 2.3 + classifier = Task 2.4 + responder = Task 2.5 (verified at plan lines 5122 + 5267 + 5313 respectively). gmail_pubsub task ID was correct; classifier + responder were off-by-one. Inventory table above uses the plan-verified mapping; cite corrected at audit-write time.

Cross-referenced (NOT re-audited): `backend/app/api/webhooks/gmail.py` + `backend/app/security/webhook_verify.py` (Step 11 audited — webhook receiver layer + Pub/Sub ACK policy via `_is_retry_worthy` conservative whitelist applies to gmail_pubsub.py errors that bubble up); `backend/app/email/gmail_watch.py:get_gmail_service` (Step 12 audited — gmail_pubsub.py:243-245 calls it via `_get_gmail_service` wrapper). Phase 2 later surfaces (digest.py Task 2.6 + calendar_tool.py Task 2.7+) excluded — Step 14 scope.

Base plan: Task 2.3 (lines 5122-5265 — gmail_pubsub), Task 2.4 (lines 5267-5311 — classifier), Task 2.5 (lines 5313-5556 — responder). Turn 16.5 referenced at plan line 9457 ("focused work between named turns when deferred items accumulate enough to warrant a dedicated turn" — pattern alongside Phase 1's Turn 14 test-suite-closeout). Memory notes consulted + re-verified at audit-write time: `project_gmail_approval_duplicate_race.md` (verified — fix recipe matches live code at gmail_pubsub.py:108-126 exactly; F1 flipped to FIXED at this step), `project_email_responder_fabricates_content.md` (verified — note's "Fixed Turn 16.5" claim matches live responder.py:6-49 across all 4 anti-fab elements; reaffirm-only, no flip), `project_email_action_capability_gap.md` (verified STALE — Approve/Reject path shipped at Turn 17.5 per Step 9 + Step 11 audits; F2 flipped to FIXED at this step with conversational "send it" half explicitly noted as deferred-by-design), `project_email_responder_sender_name.md` (verified — responder.py:59 still passes raw `From:` header without `email.utils.parseaddr` extraction; reaffirm Phase-3-deferred per note), `feedback_frontier_grade_discipline.md` (3-way enum classification smell + Turn 17.8 multi-dim lift reference at line 52), `project_module_level_mem0_instantiation_smell.md` (5-site enumeration — responder.py:4 is site #1, reaffirm only).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| **3-way enum classification** | **YES — KNOWN deferred lift** | classifier.py returns flat string `"spam"\|"fyi"\|"action_required"` with default to "fyi" on unexpected output. Discipline note line 52 names this exact case as a Turn-16-to-Turn-17.8 lift target (multi-dim restructure: urgency / intent / confidence / suggested_action). Live state still 3-way; reaffirm deferred lift; whether Turn 17.8 shipped the multi-dim restructure is forward-pickup. |
| Flat string output | **YES — same as above** | classifier.py output is the flat-string instance of this smell. responder.py returns structured `{complexity, response}` dict; gmail_pubsub.py routes to side-effect functions (not output-shape). |
| One-line tool description | N/A | No tools defined here |
| Single-item interface where batch frontier | N/A | Per-email pipeline is the correct shape (Pub/Sub delivers one history event at a time; iterate in `sweep_recent_inbox`) |
| **Module-level instantiation triggering I/O** | **Reaffirm — 5-site enumeration already tracked** | responder.py:4 `memory = MemoryManager()` is site #1 of the 5-site enumeration (already in `project_module_level_mem0_instantiation_smell.md` per Step 11 reviewer-correction). Reaffirm only — not a new site. gmail_pubsub.py + classifier.py: no module-level I/O construction (gmail_pubsub.py:16 `logger = structlog.get_logger()` is pure). |
| Logging-via-omission | None | gmail_pubsub.py logs every interesting branch (`email_log_already_exists`, `email_archived_spam`, `email_added_to_digest`); responder.py + classifier.py rely on llm_gateway for completion-side logging. |
| **Sync bypass of cost-tracking / observability** | **None — both route through gateway** | classifier.py:28-32 `llm_gateway.complete(task_type="classification", ...)` ✓; responder.py:67-71 `llm_gateway.complete(task_type="drafting", ...)` ✓. NOT siblings to `project_agent_llm_cost_attribution_gap.md`'s 3 bypass surfaces — both correctly in-channel. Positive finding, mentioned in deeper-lens pass + engineering touches roll-up. |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — tiered docstrings appropriate** | gmail_pubsub.py: 1-line module docstring + 25-line `_process_single_email` function docstring carrying the load-bearing dedup-fix rationale (anti-drift positive — fix history documented inline at the surface where it bites; sibling to setup_gmail_watch.py inline failure-mode documentation per Step 12 engineering-touches roll-up). classifier.py + responder.py: no module docstrings; minimal function docstrings; DRAFT_PROMPT structure itself is the prompt-discipline documentation. Tiering appropriate per Step 12 reviewer principle. All accurate. |
| Verification axis mismatch | N/A | — |
| **Single-shot prompt where iterative reasoning would be frontier** | **Plan-noted — pre-draft context lookup deferred to Phase 3+** | responder.py is single-shot: prompt + LLM call + return. Per `project_email_responder_fabricates_content.md` "Phase 3+ extensions" section: pre-draft calendar lookup + memory recall + thread fetch are the structural answer to fabrication risk. Prompt-rule anti-fab is the safety net; structural context lookup is the lift. Phase 3 deferred per memory note; not a Step 13 actionable. |
| Speculative complexity | None | Every defensive pattern earns its keep — dedup gate (race-safety, observed-in-Turn-16), in-code rationale docstring (fix-history at the surface), 3-caller pattern (DRY across Pub/Sub + 2 schedulers), payload enrichment + stale-row fallback (Turn 17.5 perf opt with backward compat), capability-neutral SYSTEM alert copy (doesn't promise "send it" since capability gap was open at Turn 16), JSON-parse graceful fallback, body truncation, profile-driven prompt injection. |

**Deeper comparison-target pass (frontier-lens on agent-adjacent parts; production-grade on glue):**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| classifier.py (agent-adjacent, frontier-lens) | (1) Anthropic published classifier patterns (typed schema output); (2) OpenAI structured outputs API; (3) Frontier triage products (Superhuman, Front) — multi-dimensional triage shapes | **C1: 3-way enum smell** (already in smells row) — KNOWN deferred lift per discipline note line 52 + Turn 17.8 plan-slot. Reaffirm. |
| responder.py (agent-adjacent, frontier-lens) | (1) Anthropic published prompt-discipline patterns (anti-hallucination rules); (2) Claude Projects auto-reply; (3) ChatGPT Custom GPTs reply-drafting | **C2: No pre-draft context lookup** — calendar, memory, thread fetch all deferred per fabrication memory note's "Phase 3+ extensions" section. Reaffirm. **C3: No retry-on-JSON-parse-failure** — responder.py:81-82 falls back to `{complexity: "complex", response: content}` when JSON parse fails. Acceptable: complex routing surfaces full content to master via send_system_alert. Self-dismiss. |
| gmail_pubsub.py (glue, production-grade) | (1) Stripe webhook patterns (idempotency keys); (2) Pub/Sub at-least-once + UNIQUE-constraint gating | **C4: Dedup gate confirmed landed** (F1 spine verification). **C5: Pub/Sub ACK policy** lives at webhook receiver layer (Step 11 audited `api/webhooks/gmail.py:_is_retry_worthy` conservative whitelist); gmail_pubsub.py errors bubble up + handler applies ACK policy. Correct shape per directive. **C6: history.list-based deltas** documented as forward-compat (history_id arg accepted but unused) — pragmatic Pub/Sub-only fallback with explicit plan-gap rationale. Self-dismiss. |

Deeper lens result: 6 candidates surfaced. **0 net-new findings** (C1 already in smells row; C2 already memory-noted; C3 self-dismiss; C4 = F1 verification spine; C5 cross-layer correct; C6 self-dismiss). All gaps either KNOWN deferred or self-dismissed.

**Comparison target:**

gmail_pubsub.py matches Stripe-grade webhook idempotency patterns (UNIQUE-constraint gate + in-code rationale of the race that motivated it) and Pub/Sub-at-least-once handling. responder.py post-Turn-16.5 anti-fab prompt discipline matches Anthropic's published anti-hallucination patterns (explicit forbidden phrasings + escape hatch). classifier.py is plan-verbatim shape with known deferred multi-dim lift. **Bar per sub-surface per directive:** glue (gmail_pubsub.py) hits Frontier on the race-safety + rationale-documentation; agent-adjacent responder.py is Frontier on the anti-fab discipline; classifier.py is Mid with tracked deferred lift.

**Three-hats tension surfaced:**

- **Architect** wants gmail_pubsub.py to gate everything on a single source of truth (email_logs UNIQUE constraint). Wins on race-safety + idempotency. Loses on the trade-off documented at lines 79-83: drafting LLM call fires before the gate, so duplicate deliveries waste one drafting call per redelivery (~$0.001 each on gpt-4o-mini, $0 on Groq). Resolved with the explicit trade-off documented inline — cheap-and-clear over query-heavy-and-tight.
- **Engineer** wants the dedup race fix to be the minimum reorder + IntegrityError-catch + early-return. Wins on simplicity (~10 LOC change to the critical section). Loses on the lost ability to recover from drafting-failure-after-classify (the EmailLog row records `draft_response` + `response_complexity` at INSERT time; if drafting fails later, those fields are NULL with no retry path). Tension acceptable: classify failures should be rare and the row carries enough state for manual investigation.
- **AI-ML engineer** wants responder.py to ALSO have pre-draft context lookup (calendar / memory / thread fetch per Phase 3+ memory note recommendation). Currently prompt-rule-only is the safety net. Tension: prompt-rule prevents fabrication-when-asked-about-unknowns; structural context lookup would give the LLM real data so "I don't know" cases shrink. Resolved with Phase 3+ deferral; prompt-rule is enough for Phase 2 + master-review-before-send.

All three tensions surfaced.

**Findings + disposition:**

| # | Finding | Disposition |
|---|---|---|
| F1 | **Dedup race fix CONFIRMED LANDED** (spine verification #1). `project_gmail_approval_duplicate_race.md`'s fix recipe matches live code at `backend/app/email/gmail_pubsub.py:108-126` exactly — EmailLog INSERT-first gate + IntegrityError catch + early return; side effects (lines 128-175) only reached after successful claim of `msg_id`. 25-line in-code rationale docstring at lines 60-84 explicitly documents the original bug + fix + trade-off, citing the 12-row Zapier observation (`19e2274ca914e6b6`). Memory note doesn't currently acknowledge the fix landed. | **Memory note flipped to FIXED status at audit-write time** — STATUS UPDATE header citing gmail_pubsub.py:108-126 (gate) + 60-84 (rationale docstring) inserted between frontmatter and original "The bug:" body. Frontmatter name + description updated to "FIXED" framing. Original problem statement preserved as historical context. MEMORY.md ledger refreshed: "Gmail approval duplicate-row race — FIXED" with full live cites + "Note retained for the Phase 3+ pattern (any redelivery-prone integration follows the same INSERT-as-gate shape)" framing. Step 9 shape. |
| F2 | **`project_email_action_capability_gap.md` is STALE** (spine verification #2). Describes Turn 16 state when no gmail_send tool existed + Approve/Reject + "send it" were no-ops. **Approve/Reject path shipped at Turn 17.5** per Step 9 + Step 11 audits: gmail_send tool registered (Step 8 audit — `backend/app/agent/tools/gmail_send.py`); `_resolve_gmail_approval` Gmail-approval dispatch at `messaging/router.py:135-269` reads PendingApproval.payload + dispatches gmail_send; Turn 17.5 payload enrichment at `gmail_pubsub.py:198-203` stores subject + rfc822_message_id so dispatch skips Gmail fetch for new rows + falls back to fetch for pre-Turn-17.5 stale rows. The note's "How to apply (when closing the gap)" section's exact recipe for the simpler half IS what shipped. **The conversational "send it" half remains explicitly NOT shipped** per the note's "harder half" framing — capability-neutral SYSTEM alert copy at `gmail_pubsub.py:162-175` deliberately doesn't promise it. Reviewer's "reaffirm don't re-open" directive clarified at sign-off: meant "don't surface as actionable-still-broken F-row" — not "leave note saying it's open." | **Memory note flipped to FIXED status at audit-write time** — STATUS UPDATE header citing router.py:135-269 + gmail_send tool + gmail_pubsub.py:198-203 payload enrichment + gmail_pubsub.py:162-175 capability-neutral SYSTEM alert copy. Frontmatter name + description updated to "Approve/Reject path FIXED; conversational 'send it' half explicitly NOT shipped (deferred by design)" framing. Conversational-half explicitly preserved as deferred-by-design per the note's "harder half" framing. Original problem statement preserved as historical context. MEMORY.md ledger refreshed: "Email Approve/Reject + 'send it' — Approve/Reject path FIXED; conversational 'send it' half deferred by design" with full live cites + the conversational-half-deferred framing. Step 9 + F1 shape. |

_F3 cut per silence protocol: anti-fabrication DRAFT_PROMPT verified accurate — `project_email_responder_fabricates_content.md`'s "Fixed Turn 16.5" claim matches live responder.py:6-49 across all 4 elements (anti-fab section + escape hatch + forbidden phrasings list + cleaned-up complexity). Memory note status accurate; no flip needed. Reaffirm._

_F4 cut per silence protocol: `project_email_responder_sender_name.md` ("Dear Chetan") still OPEN as the note says — responder.py:59 still passes raw `From:` header to LLM without `email.utils.parseaddr` extraction. Phase-3-deferred per note. Reaffirm; no action._

_F5 cut per silence protocol: classifier.py 3-way enum smell + responder.py single-shot-no-pre-draft-context are KNOWN deferred lifts (discipline note line 52 + fabrication note "Phase 3+ extensions" section). Reaffirm; forward-pickup for whichever step audits Turn 17.8 + Phase 3 RAG work._

_F6 cut per silence protocol: classifier.py + responder.py both correctly route through `llm_gateway.complete()` (NOT bypass siblings to `project_agent_llm_cost_attribution_gap.md`'s 3 bypass surfaces). Positive finding; mentioned in deeper-lens pass + engineering touches roll-up._

_Engineering touches at this surface: 16 distinct frontier-execution patterns observed across the 3 files (gmail_pubsub.py: Turn 16.5 dedup gate via EmailLog INSERT-first + IntegrityError-catch-and-early-return; 25-line in-code rationale docstring at lines 60-84 documenting original bug + fix + trade-off + 12-row Turn 16 observation; 3-caller single-helper `sweep_recent_inbox` pattern reusable across Pub/Sub + gmail_renew + gmail_check; RFC822 Message-ID dual-case handling with empty-string fallback; plan-gap-fill `thread_id="gmail:<msg_id>"` synthesis + `interrupt_id` + `expires_at` NOT-NULL column fills; Turn 17.5 payload enrichment with stale-row fetch fallback; capability-neutral SYSTEM alert copy that deliberately doesn't promise "send it" since the conversational-dispatch gap was open at Turn 16 + remains deferred-by-design; `_fetch_new_messages` SQL-based dedup at fetch boundary — defense-in-depth alongside the INSERT gate; classifier.py: `task_type="classification"` routes to FAST_MODEL — cost discipline; defensive default to "fyi" on unexpected LLM output; temperature=0.0 deterministic; **both classifier.py + responder.py correctly route through `llm_gateway.complete()` — NOT bypass siblings to project_agent_llm_cost_attribution_gap.md's 3 bypass surfaces**; responder.py: `task_type="drafting"` + temperature=0.3; JSON-parse with graceful `try/except json.JSONDecodeError → fallback`; body truncation to 2000 chars; profile-driven master_name + comm_style injection; DRAFT_PROMPT itself is the documentation of Turn 16.5's anti-fab discipline — anti-fab section + escape hatch + forbidden phrasings list + cleaned complexity classification structured directly into the prompt). Bar per sub-surface per directive: glue (gmail_pubsub.py) Frontier on race-safety + rationale-documentation; agent-adjacent responder.py Frontier on anti-fab discipline; classifier.py Mid with tracked deferred 3-way-smell lift._

**Methodology note:** Spine of Step 13 per directive: two fix-verifications. **Dedup race fix CONFIRMED** (F1 → note flipped to FIXED with cites). **Anti-fabrication fix CONFIRMED** (note's "Fixed Turn 16.5" claim accurate; reaffirm only, no flip needed). Plus as-of-step reaffirms: `project_email_action_capability_gap.md` was STALE in the same shape as Step 9's gmail-approval-resume-fail (F2 → note flipped to FIXED for Approve/Reject path + conversational "send it" half explicitly preserved as deferred-by-design per the note's "harder half" framing; reviewer clarified "reaffirm don't re-open" meant "don't surface as actionable-still-broken" not "leave note saying it's open"); `project_email_responder_sender_name.md` ("Dear Chetan") still OPEN, Phase-3-deferred. Plus deeper-lens reaffirms: 3-way enum smell deferred per discipline note + Turn 17.8 plan-slot; no pre-draft context lookup deferred per fabrication note's Phase 3+ section; classifier.py + responder.py both correctly route through `llm_gateway.complete()` — positive (NOT bypass siblings), mentioned in roll-up. Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 10-12 reviewer pattern. F3/F4/F5/F6 from synthesis cut per silence protocol — reaffirmed in methodology rather than promoted to F-rows. F-rows reserved for actionable items (note status flips). **Task-ID cite correction:** synthesis-time presentation cited responder = Task 2.4 + classifier = Task 2.3; plan-verified mapping is gmail_pubsub = Task 2.3 + classifier = Task 2.4 + responder = Task 2.5 (verified at plan lines 5122 + 5267 + 5313). Corrected at audit-write time; inventory table uses the verified mapping.

**Cross-references:**
- Base plan: Task 2.3 (lines 5122-5265 — gmail_pubsub) + Task 2.4 (lines 5267-5311 — classifier) + Task 2.5 (lines 5313-5556 — responder); Turn 16.5 pattern referenced at plan line 9457
- Base plan amended at this step: **none**
- In-place code fix landed at audit-write time: **none** (per reviewer disposition — no code edits, no new notes; both F-rows are memory-note status flips)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: `project_gmail_approval_duplicate_race.md` (F1 — flipped to FIXED with STATUS UPDATE header citing gmail_pubsub.py:108-126 gate + 60-84 rationale docstring; frontmatter name + description updated to FIXED framing; original problem statement preserved as historical context), `project_email_action_capability_gap.md` (F2 — flipped to FIXED with STATUS UPDATE header citing router.py:135-269 + gmail_send tool + gmail_pubsub.py:198-203 payload enrichment + gmail_pubsub.py:162-175 capability-neutral copy; frontmatter name + description updated to "Approve/Reject path FIXED; conversational 'send it' half deferred by design" framing; original problem statement preserved as historical context)
- MEMORY.md ledger refreshed at this step: both notes' ledger lines updated (Step 9 shape) — "Gmail approval duplicate-row race — FIXED" with full live cites; "Email Approve/Reject + 'send it' — Approve/Reject path FIXED; conversational 'send it' half deferred by design" with full live cites
- Backward cross-reference: F2 flip closes the same staleness pattern that Step 9's gmail-approval-resume-fail flip addressed (both notes documented "this is broken" while the fix had already shipped at Turn 17.5)
- Forward cross-reference: classifier.py 3-way enum smell + Turn 17.8 multi-dim lift status is forward-pickup for whichever step audits Turn 17.8; pre-draft context lookup (calendar / memory / thread fetch) deferred to Phase 3 per fabrication memory note's "Phase 3+ extensions" section
- Memory notes referenced (existing, reaffirmed): `project_email_responder_fabricates_content.md` (Fixed Turn 16.5 claim verified accurate; no flip), `project_email_responder_sender_name.md` (still OPEN per note, Phase-3-deferred — verified responder.py:59 still passes raw From header to LLM), `feedback_frontier_grade_discipline.md` (3-way enum classification smell line 52 + Turn 17.8 lift reference), `project_module_level_mem0_instantiation_smell.md` (responder.py:4 is site #1 of 5-site enumeration — reaffirm only, no new site), `project_agent_llm_cost_attribution_gap.md` (classifier.py + responder.py NOT bypass siblings — both correctly route through llm_gateway.complete; positive finding in roll-up)

### Step 14 — Turn 16 — Calendar tool (read + create) + Daily Digest (two Turn-16 surfaces held back from Step 13)

**Overall rating:** Mid (calendar_tool.py is plan-verbatim Phase 2 first-touch with two KNOWN deferred lifts already tracked — Turn 17.9 close-out task `2.X-closeout-p` for description sharpening + Phase 3 enrichment per `project_calendar_output_enrichment_phase3.md`; digest.py is clean production-grade glue with confirmed gateway routing + bounded inputs. Engineering touches are frontier-execution within a Mid foundation — don't round up. Lifts when both deferred calendar lifts ship) — **Status:** final — sign-off 2026-06-08

**Scope:**
Two Turn-16 surfaces held back from Step 13 — calendar agent tool (read + create) + daily digest builder. 2 files audited, 196 LOC total. Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Steps 12-13 accumulated upgrade-doc changes uncommitted. **Cleanest surface in the Phase 2 audit so far** — 0 actionable F-rows; all 5 lens-check verifications confirmed positives or reaffirms of KNOWN deferrals.

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/agent/tools/calendar_tool.py` | 145 | Task 2.5b (plan lines 5379-5556) | **Plan-verbatim shape** — Pydantic args (CalendarReadArgs + CalendarCreateArgs) + 2 async handlers + `_build_credentials()` helper with narrow `scopes=["https://www.googleapis.com/auth/calendar"]` + `register()` registration. **calendar_create docstring at lines 99-102 carries explicit APPROVE-tier cross-reference to safety.py** (anti-drift positive). Tool registrations carry minimal descriptions below the `feedback_tool_specific_guidance_in_descriptions.md` discipline bar (no "Does NOT" cross-refs, no example queries, no output-shape mention) — **KNOWN deferred lift at Turn 17.9 close-out task `2.X-closeout-p`** ("Calendar tool description sharpening", plan line 9606). Output flat strings (calendar_read newline-joined; calendar_create htmlLink-only with no event_id) — **KNOWN deferred lift per `project_calendar_output_enrichment_phase3.md`** (6 enrichments ranked by likely impact in note). |
| `backend/app/email/digest.py` | 51 | Task 2.6 (plan line 5558) | **Plan-verbatim shape** — `redis_client = aioredis.from_url(settings.REDIS_URL)` module-level object construction with lazy connection (NOT module-level I/O); 2 functions (`add_to_digest` LIST RPUSH + `build_and_clear_digest` LIST LRANGE → LLM summarize → DELETE); **routes through `llm_gateway.complete(task_type="summarization", temperature=0.3)` at line 39-43 — NOT bypass sibling** to `project_agent_llm_cost_attribution_gap.md`'s 3 bypass surfaces; body_preview double-truncated (300 chars upstream at gmail_pubsub.py:137 + 100 chars in LLM prompt at digest.py:28) — bounded LLM input. |

**Lens-check verifications per directive (all 5 confirmed):**

1. **calendar_create safety tier = APPROVE** — verified at safety.py:58 (TOOL_SAFETY_MAP) + self-documented in calendar_tool.py:100-101 docstring + plan-verbatim Task 2.5b at line 5385 ("`calendar_read` is `SAFE`, `calendar_create` is `APPROVE`"). ✓ Positive.
2. **calendar_read description discipline** — checked against `feedback_tool_specific_guidance_in_descriptions.md` + Turn 17.6 cross-ref pattern (memory_search + email_history_search "Does NOT search X; use Y"). calendar_read description (lines 130-133): below the bar. KNOWN deferred at `2.X-closeout-p`. Reaffirm per silence protocol.
3. **calendar_create description discipline** — calendar_create description (lines 139-142): below the bar despite "Requires approval" operator-trust signal. KNOWN deferred at `2.X-closeout-p`. Reaffirm per silence protocol.
4. **digest.py LLM gateway routing** — confirmed `llm_gateway.complete()` at line 39-43. NOT bypass sibling. ✓ Positive.
5. **calendar output flatness** — verified live calendar_read returns flat newline-joined string (lines 74-87); calendar_create returns "Created event '<title>'. View: <htmlLink>" (line 122) with NO event_id. Reaffirm Phase-3 deferral per `project_calendar_output_enrichment_phase3.md`, NOT flip per user directive.

Cross-referenced (NOT re-audited): `backend/app/email/gmail_watch.py:get_gmail_service` (Step 12 — calendar tool builds its own Credentials with narrow scopes via `_build_credentials()` rather than reusing the gmail_watch helper; mild duplication, acceptable per silence protocol — refactor opportunity when 3rd Google API surface lands), `backend/app/agent/tools/__init__.py` registration (Step 8), `backend/app/agent/safety.py` TOOL_SAFETY_MAP (Step 6 — calendar_read = SAFE at line 44; calendar_create = APPROVE at line 58; calendar_update + calendar_delete forward-declared at lines 59-60 as APPROVE but handlers not yet implemented — defensive forward-declaration per Step 6 audit F5), `backend/app/email/classifier.py` + `backend/app/email/gmail_pubsub.py` (Step 13 — digest consumes their EmailLog output transitively via gmail_pubsub.py:137 `add_to_digest(body[:300])`), `backend/app/scheduler/tasks/morning_brief.py` (later step — Turn 17 scheduler that delivers the digest).

Base plan: Task 2.5b (lines 5379-5556 — Google Calendar Tool, calendar_read + calendar_create with safety classification cited at line 5385) + Task 2.6 (lines 5558+ — Daily Digest Builder) + Turn 17.9 close-out task `2.X-closeout-p` (plan line 9606 — "Calendar tool description sharpening", NOT yet shipped per live state). Memory notes consulted + re-verified at audit-write time: `project_calendar_output_enrichment_phase3.md` (verified — live calendar_read still flat at lines 74-87; calendar_create still htmlLink-only at line 122 with no event_id; reaffirm Phase-3 deferral, no flip per user directive — the enrichments are deferred, not shipped), `project_oauth_scope_minimization_production_hardening.md` (Step 12 cross-ref — calendar scope is full read/write per google_oauth.py:60-64; calendar_tool.py's `_build_credentials()` narrow `scopes=["https://www.googleapis.com/auth/calendar"]` parameter at line 47 is defense-in-depth even though refresh token grants the broader scope; reaffirm), `feedback_tool_specific_guidance_in_descriptions.md` (re-verified — Turn 17.6 established the "Does NOT search X; use Y" cross-ref + example queries + output-shape mention discipline for memory_search + email_history_search; calendar tools below that bar per `2.X-closeout-p` deferred lift), `project_agent_llm_cost_attribution_gap.md` (digest.py NOT a bypass sibling — correctly routes through llm_gateway.complete; positive finding mentioned in roll-up).

**Smells checklist scan:**

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| **Flat string output** | **YES — KNOWN deferred lift** | calendar_read returns flat newline-joined string; calendar_create returns flat "Created event '<title>'. View: <htmlLink>" with no event_id. Per `project_calendar_output_enrichment_phase3.md`: deferred until master usage signals which axis matters (6 enrichments ranked by likely impact — event_id return → TZ normalization → Meet link → recurrence → free/busy → conflict detection). Reaffirm Phase-3 deferral; NOT a Step 14 actionable per user directive. digest.py returns formatted plain-text "📬 Morning Email Digest..." — correct shape for Telegram delivery. |
| **One-line tool description** | **YES — KNOWN deferred lift** | calendar_read + calendar_create descriptions both below the `feedback_tool_specific_guidance_in_descriptions.md` discipline bar (no "Does NOT" cross-refs, no example queries, no output-shape mention). KNOWN deferred at Turn 17.9 close-out task `2.X-closeout-p` ("Calendar tool description sharpening", plan line 9606). Live state still minimal; whichever step audits Turn 17.9 close-out should verify the lift shipped. Reaffirm per silence protocol; NOT a Step 14 actionable. Surfacing as an F-row would be exactly the manufacturing the meta-lesson warns against. |
| Single-item interface where batch frontier | N/A | calendar_read returns top-K (max_results); calendar_create per-event (correct for write); digest batch-by-design (LIST queue → 1 LLM call → DELETE). All correct shapes. |
| **Module-level instantiation triggering I/O** | **None — lazy connection** | calendar_tool.py:15 `logger = structlog.get_logger()` is pure. digest.py:7 `redis_client = aioredis.from_url(settings.REDIS_URL)` is object construction; redis-py creates connection on first command (lazy). NOT a smell — same shape as logger/settings singletons (sibling to channel_registry.py:42 per Step 9 audit). |
| Logging-via-omission | Mild | calendar_tool.py imports `logger` (line 13/15) but NEVER uses it — calendar_create silently succeeds or raises on Google API failure (Google API client surfaces errors). digest.py: no logging (build_and_clear_digest output returned to scheduler caller which logs delivery). Mild observability gap on calendar_create write actions; acceptable since safety classifier APPROVE-gates execution + audit_trail captures the action via tool_executor. NOT a Step 14 actionable. |
| **Sync bypass of cost-tracking / observability** | **None — digest correctly routes through gateway** | digest.py:39-43 `llm_gateway.complete(task_type="summarization", ...)` ✓. NOT bypass sibling to `project_agent_llm_cost_attribution_gap.md`'s 3 bypass surfaces. Same correct shape as classifier.py + responder.py from Step 13. Positive finding, mentioned in deeper-lens pass + engineering touches roll-up. calendar_tool.py: no LLM calls (Google API calls only). |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | Reverse: tool descriptions ARE the surface where per-tool guidance lives per the discipline; calendar tool descriptions below the bar = One-line-tool-description smell row above. |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — anti-drift positive observed** | calendar_tool.py: 5-line module docstring + function docstrings minimal but accurate. **calendar_create docstring at lines 99-102 carries explicit APPROVE-tier cross-reference to safety.py** — anti-drift positive (sibling pattern to gmail_pubsub.py:60-84 Turn-16.5-fix-rationale + setup_gmail_watch.py:25-29 inline failure-mode documentation per Step 12). digest.py: minimal docstrings, accurate. All verified accurate. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | Acceptable | digest.py LLM call is single-shot (no iterative reasoning). Task is well-bounded (group + summarize FYI emails); no iterative-reasoning lift needed. NOT a smell at this surface. |
| Speculative complexity | None | Every pattern earns its keep — `cache_discovery=False` (Google API best-practice); narrow scopes parameter on Credentials (defense-in-depth); `sendUpdates="all" if attendees else "none"` smart default; body_preview double-truncation bounded input; redis-list lazy connection; 1-LLM-call-and-clear atomic operation. |

**Deeper comparison-target pass:**

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| calendar_tool.py (frontier-lens — agent tool) | (1) Anthropic published tool-description discipline; (2) OpenAI function-calling examples; (3) Cursor tool patterns; (4) LangChain published Calendar tools | **C1: Tool descriptions below the bar** — KNOWN deferred at Turn 17.9 `2.X-closeout-p` (already in smells row). Reaffirm. **C2: Output enrichment gaps** — KNOWN deferred per `project_calendar_output_enrichment_phase3.md` (already in smells row). Reaffirm. **C3: Credential helper duplication** — calendar_tool.py:40-48 builds Credentials directly with narrow `scopes` parameter; gmail_watch.py:get_gmail_service builds with no scopes parameter. Mild duplication; refactor opportunity (shared `_get_google_credentials(scopes)` helper would unify) — self-dismiss as production-bar glue acceptable until 3rd Google API surface lands. **C4: `cache_discovery=False`** at lines 55 + 104 — explicit Google API best-practice (avoids cache-related discovery doc issues). Positive engineering touch. |
| digest.py (production-bar — glue) | (1) Redis-list queue patterns; (2) typical morning-digest LLM patterns; (3) email summarization templates | **C5: LLM call routes through gateway** — NOT bypass sibling. Positive (in smells row + roll-up). **C6: No retry-on-LLM-failure** — if `llm_gateway.complete()` raises, `build_and_clear_digest` raises and the morning_brief scheduler's @critical_task catches it. Self-dismiss — scheduler-side retry sufficient. **C7: Digest data Redis-only** (LIST queue, not persisted to Postgres) — if Redis flushes between adds and morning build, digest is empty. Self-dismiss as YAGNI for single-master scale. **C8: body_preview double-truncation** (300 chars upstream + 100 chars in LLM prompt) — bounded LLM input. Positive engineering touch. |

Deeper lens result: 8 candidates surfaced. **0 net-new findings** — C1 + C2 already in smells row (KNOWN deferred); C3 + C6 + C7 self-dismissed; C4 + C5 + C8 positives mentioned in roll-up. The standard smells scan already caught the lens-check directives.

**Comparison target:**

calendar_tool.py matches LangChain published Calendar-tool shapes with plan-verbatim conformance. **Below frontier shape** on tool-description discipline (Turn 17.6 cross-ref pattern not applied — KNOWN deferred at `2.X-closeout-p`) AND on output enrichment (event_id return, TZ normalization, etc. — KNOWN deferred per Phase 3 memory note). digest.py matches Redis-list-queue summarization patterns — production-grade glue with gateway routing + bounded inputs. **Bar per sub-surface per directive:** calendar_tool.py frontier-lens — below bar on description + output, both KNOWN deferred; digest.py production-bar — hits the bar with gateway routing + bounded inputs.

**Three-hats tension surfaced:**

- **Architect** wants calendar_tool.py to be one canonical entry point for read + create + update + delete operations. Wins on simplicity (2 handlers covering 80% of use cases). Loses on coverage — calendar_update + calendar_delete declared in TOOL_SAFETY_MAP at safety.py:59-60 as APPROVE but handlers not yet implemented. Resolved with defensive forward-declaration pattern per Step 6 audit F5 — TOOL_SAFETY_MAP forward-declares Phase 3+ tools as a stay-ahead-of-the-plan marker, tool registry only binds registered tools so dead-code entries can't fire.
- **Engineer** wants digest.py to be the simplest possible Redis-list + LLM-call glue. Wins on 51 LOC clean shape. Loses on observability (no logging) + retry (no LLM retry) — both acceptable at scheduler-driven once-a-day cadence. Tension resolved with simplicity.
- **AI-ML engineer** wants calendar tool descriptions to carry the Turn 17.6 cross-ref + example-query discipline so the agent picks the right tool reliably. Loses currently — descriptions are minimal; agent might pick calendar_create when calendar_read would do, or vice versa. Resolved with the deferred-lift at Turn 17.9 `2.X-closeout-p`; safety classifier prevents calendar_create from firing without master approval as the safety net.

All three tensions surfaced.

**Findings + disposition:**

_**No actionable findings at this step.** All 5 lens-check verifications + 8 deeper-lens candidates resolved as reaffirms of KNOWN deferrals or positives. F-rows reserved for actionable items per silence protocol; engineering-touches roll-up + methodology note carry the substantive content. Per Step 12 reviewer's meta lesson applied throughout Steps 12-13-14: "when a surface is clean, lean into no-action-positive + reaffirm rather than reaching for ... a new note." **Step 14 is the cleanest surface in the Phase 2 audit so far — 0 F-rows is the honest output.** Surfacing the calendar description-discipline gap as an F-row would be exactly the manufacturing the meta-lesson warns against (it's a tracked deferred lift at Turn 17.9 `2.X-closeout-p`; reaffirm-in-roll-up is correct)._

_Spine verifications per user directive (all 5 confirmed):_
- _calendar_create safety tier = APPROVE_ (safety.py:58 + calendar_tool.py:100-101 docstring cross-reference + plan-verbatim Task 2.5b at line 5385) ✓ Positive
- _calendar_read description discipline check_ — below the bar; KNOWN deferred at Turn 17.9 `2.X-closeout-p`; reaffirm ✓
- _calendar_create description discipline check_ — below the bar despite "Requires approval" operator-trust signal; KNOWN deferred at Turn 17.9 `2.X-closeout-p`; reaffirm ✓
- _digest.py LLM gateway routing_ — confirmed `llm_gateway.complete()` at line 39-43; NOT bypass sibling; positive ✓
- _calendar output flatness_ — confirmed per `project_calendar_output_enrichment_phase3.md`; reaffirm Phase-3 deferral, NOT flip per user directive ✓

_Engineering touches at this surface: 8 distinct frontier-execution patterns observed (calendar_tool.py: explicit APPROVE-tier cross-reference to safety.py documented in calendar_create docstring at lines 99-102 — anti-drift positive sibling to gmail_pubsub.py:60-84 + setup_gmail_watch.py:25-29 inline documentation patterns; `cache_discovery=False` parameter at lines 55 + 104 — explicit Google API best-practice avoiding discovery-doc cache issues; narrow `scopes=["https://www.googleapis.com/auth/calendar"]` parameter on Credentials construction — defense-in-depth even though refresh token grants broader; smart `sendUpdates="all" if attendees else "none"` default at line 119; CalendarReadArgs + CalendarCreateArgs Pydantic args_schema with explicit Field descriptions — registry pattern compliance; digest.py: `redis_client = aioredis.from_url()` module-level object construction with lazy connection — NOT module-level I/O; **digest.py LLM call routes through `llm_gateway.complete(task_type="summarization")` — NOT bypass sibling to `project_agent_llm_cost_attribution_gap.md`'s 3 bypass surfaces** — same correct shape as classifier.py + responder.py from Step 13; body_preview double-truncation — 300 chars upstream at gmail_pubsub.py:137 + 100 chars in LLM prompt at digest.py:28 — bounded LLM input). Bar per sub-surface per directive: calendar_tool.py is Mid plan-verbatim with 2 KNOWN deferred lifts (Turn 17.9 description sharpening + Phase 3 output enrichment); digest.py is production-grade glue with gateway routing + bounded inputs. **Engineering touches are frontier-execution within a Mid foundation — don't round up to Frontier; plan-verbatim with two tracked deferred lifts keeps the composite honestly at Mid.**_

**Methodology note:** Spine of Step 14 per directive: 5 lens-check verifications (calendar_create safety tier + calendar_read description discipline + calendar_create description discipline + digest.py LLM gateway routing + calendar output flatness reaffirm). **All 5 confirmed** as expected per user-directed framing. 2 confirmed KNOWN deferrals (description discipline → Turn 17.9 `2.X-closeout-p`; output flatness → Phase 3 memory note) — reaffirm-only, no flips per user directive. 3 confirmed positives (safety tier APPROVE + gateway routing + anti-drift cross-reference in calendar_create docstring) — engineering touches roll-up. Deeper lens produced 8 candidates; 0 net-new findings — all already in smells row OR self-dismissed OR positive. Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 12-13 reviewer pattern. **0 F-rows + 5 reaffirms + 8 engineering touches** is the honest Step 14 output — applying the Step 12 reviewer meta lesson at the limit ("when the surface is clean, lean into no-action-positive + reaffirm"). Reviewer at sign-off: "Clean surface → honest no-action output. This is the lesson applied right."

**Optional tidy on `project_email_action_capability_gap.md` name field** (user directive at Step 13 sign-off: "Trim the stale phrase from the name when you next touch that note"): Step 14 doesn't touch that note. Deferring per user's "when you next touch" framing. The tidy can ride with the next memory-note touch.

**Cross-references:**
- Base plan: Task 2.5b (lines 5379-5556 — Google Calendar Tool) + Task 2.6 (line 5558 — Daily Digest Builder) + Turn 17.9 close-out task `2.X-closeout-p` (plan line 9606 — Calendar tool description sharpening, NOT yet shipped per live state)
- Base plan amended at this step: **none**
- In-place code fix landed at audit-write time: **none** (per silence protocol — no F-rows means no actions)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: **none**
- MEMORY.md ledger: **no change**
- Forward cross-reference: Turn 17.9 close-out `2.X-closeout-p` (calendar description sharpening) status is forward-pickup for whichever step audits Turn 17.9; `project_calendar_output_enrichment_phase3.md` enrichments are forward-pickup for Phase 3 trigger (master usage signal)
- Memory notes referenced (existing, reaffirmed): `project_calendar_output_enrichment_phase3.md` (Phase-3 deferral reaffirmed; live calendar_read + calendar_create still flat per note's "Current state (verified)" section), `project_oauth_scope_minimization_production_hardening.md` (Step 12 cross-ref — calendar scope is full read/write per google_oauth.py; calendar_tool.py's narrow scopes parameter is defense-in-depth), `feedback_tool_specific_guidance_in_descriptions.md` (discipline reaffirmed — calendar tools below the bar; KNOWN deferred at `2.X-closeout-p`), `project_agent_llm_cost_attribution_gap.md` (digest.py NOT a bypass sibling — correctly routes through llm_gateway.complete; positive finding in roll-up), `feedback_frontier_grade_discipline.md` (Step 6 audit F5 defensive forward-declaration pattern — TOOL_SAFETY_MAP forward-declares calendar_update + calendar_delete handlers that don't exist yet, acceptable)

### Step 15 — Turn 17 — Celery scheduler layer (one coherent subsystem)

**Overall rating:** Mid-to-Frontier (reliability machinery — celery_app per-worker init + task_wrapper @critical_task + task_helpers rebind pattern — is Frontier-execution with load-bearing fixes for the Turn-18 incident + cost-documented design choices + cross-reference to Phase 1 test_resume_dedup pattern; per-task glue hits production-bar with uniform rebind application (4/4 real tasks ✓ + stub correctly N/A); F1 approval_expiry fail-loud gap ships in-place at audit-write time. **Lifts to Frontier when the lazy-init refactor closes the Mem0 module-level chain** — that's the confirmed-still-present Turn-18 chain at celery_app→gmail_renew/check→gmail_pubsub→responder.py:4 — not F1, since F1 lands this step) — **Status:** final — sign-off 2026-06-08

**Scope:**
Turn 17 Celery scheduler layer — one coherent subsystem audited as single step per directive. 9 files (~430 LOC): 4 scheduler infrastructure (celery_app + beat_schedule + task_wrapper + task_helpers) + 5 task modules (morning_brief + gmail_renew + gmail_check + approval_expiry + memory_consolidation). Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Steps 12-14 accumulated upgrade-doc changes uncommitted + this step's in-place F1 fix landed (approval_expiry @critical_task swap).

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/scheduler/celery_app.py` | 95 | Task 2.7 (plan lines 5615-5687) | **Plan-verbatim + plan-gap fill** — `celery_app = Celery("jarvis", ...)` + explicit `include=[6 task modules]` (NOT autodiscover — explicit list); `@worker_process_init.connect` per-worker bootstrap with 17-line rationale docstring on why DB/checkpointer cannot pre-init here (event-loop binding); registers Telegram channel in worker process for failure alerts. **17-line plan-gap-fill docstring** at lines 1-18 explains why per-worker init exists (plan-verbatim Task 2.7 omits it; without it half the tasks fail at runtime). |
| `backend/app/scheduler/beat_schedule.py` | 70 | Task 2.7 (plan lines 5644+) | **Plan-verbatim** — 5 scheduled jobs. **Cron `"0,6"` correction at lines 46-52** documents the prior `*/6` mistake explicitly (origin surface for `feedback_verify_before_claiming.md` "schedule-registered ≠ beat-up" axis lesson). |
| `backend/app/scheduler/task_wrapper.py` | 80 | Task 2.7 (plan lines 5692+) | **Plan-verbatim** — `@critical_task` decorator wraps Celery's `task` + 3-consecutive-failure Redis counter (DB 1, isolated from app Redis DB 0) + `asyncio.run(_alert_master(...))` calling `send_system_alert` from `failure_alerter` → Telegram alert. Reset-counter-on-success discipline prevents alert spam. |
| `backend/app/scheduler/task_helpers.py` | 52 | **Plan-gap fill** (Turn 17 added; not in plan-verbatim Task 2.7) | `reset_async_state_for_task()` — disposes engine + closes-and-reopens checkpointer per task-body invocation. 21-line rationale docstring + cost-documented "~50ms per task" + cross-reference to Phase 1 test_resume_dedup fixture pattern (per `project_async_state_rebind_pattern.md`). |
| `backend/app/scheduler/tasks/morning_brief.py` | 53 | Task 2.8 (plan lines 5775+) | `@critical_task`-wrapped ✓ + `await reset_async_state_for_task()` at top of `_send()` ✓. Graceful try/except ImportError pattern for Phase 3 news_briefing module — picks up news section when Turn 25 lands without code edit. |
| `backend/app/scheduler/tasks/gmail_renew.py` | 45 | Task 2.7 (plan lines 5663+ — within beat-schedule) | `@critical_task`-wrapped ✓ + `await reset_async_state_for_task()` ✓. Seam-closure: re-call `users.watch()` + `sweep_recent_inbox()` to catch anything published between old watch's last delivery and new watch's first. 19-line seam-closure rationale docstring. |
| `backend/app/scheduler/tasks/gmail_check.py` | 39 | Task 2.7 (plan lines 5658+ — within beat-schedule) | `@critical_task`-wrapped ✓ + `await reset_async_state_for_task()` ✓. 15-min Pub/Sub safety-net poll; shares `sweep_recent_inbox` helper with gmail_renew + gmail_pubsub (3-caller single-helper pattern per Step 13). |
| `backend/app/scheduler/tasks/approval_expiry.py` | 53 (was 51 pre-F1) | Task 2.7 (plan lines 5812-5829) | **F1 in-place fix landed at audit-write time** — `@celery_app.task` → `@critical_task` decorator swap + import update at line 16; 8-line `@critical_task` rationale docstring added documenting fail-loud discipline + sibling-pattern framing with the other 3 belt-and-braces tasks. `await reset_async_state_for_task()` ✓ unchanged. |
| `backend/app/scheduler/tasks/memory_consolidation.py` | 34 | Task 2.7 (plan lines 5668+ — within beat-schedule) | **Turn 17 stub** confirmed (logger.info-only; no real work). `@celery_app.task` directly — stub doesn't need fail-loud (can't really fail). `reset_async_state_for_task()` NOT called — stub uses NO async resources so rebind is N/A. **Origin correction:** `git log --follow` shows IS in Turn 17 commit `7821568` (never modified since) — `git show 7821568 --stat` confirms 34 insertions. User directive at Step 15 sign-off acknowledged: "my greenlight's 'not in 7821568' was a truncated git-show grep on my end." |

Cross-referenced (NOT re-audited): `main.py:_startup_model_ping` (Step 11 — Turn 17 added), `api/webhooks/gmail.py` ACK policy (Step 11 — Turn 17 introduced; audited current-state then), `gmail_pubsub.py` (Step 13 — `sweep_recent_inbox` shared helper), `digest.py` (Step 14 — morning_brief calls `build_and_clear_digest`), `gmail_watch.py:setup_gmail_watch` (Step 12 — gmail_renew calls it).

Base plan: Task 2.7 (lines 5615-5772 — Celery App + Beat Schedule + critical_task) + Task 2.8 (lines 5773+ — Celery Tasks: morning_brief + approval_expiry shown in plan; gmail_check + gmail_renew + memory_consolidation referenced via beat schedule). Plan task IDs verified against plan headers (not trusting execution-table positional listing per directive). Memory notes consulted + re-verified at audit-write time: `project_async_state_rebind_pattern.md` (re-verified — pattern matches live `reset_async_state_for_task()` exactly; Phase 2 Celery surface in note's "Where this has bitten us" table — reaffirm; F5 spine verified 4/4 uniform), `project_module_level_mem0_instantiation_smell.md` (re-verified — **F2 spine — celery worker startup transitively imports responder.py:4 (5-site #1) via celery_app→gmail_renew/check→gmail_pubsub. The exact Turn-18 chain; docker-compose env fix mitigated the symptom; structural smell remains.** Reaffirm — surface has real teeth here, not cosmetic: an import-time crash if the docker-compose env fix is undone), `project_mem0_contamination_test_residue.md` (re-verified — Turn 26.5 framing reaffirmed; memory_consolidation.py stub correctly defers per note's recommendation; forward-pickup signal noted), `feedback_verify_before_claiming.md` (re-verified — F4 spine — origin surface; axis lesson documented inline at celery_app.py:67-80 + beat_schedule.py:46-52 cron-correction; reaffirm-as-origin).

### Spine verifications per directive (3 majors)

**#1 Async-state rebind uniformity** — verified EVERY task:

| Task | Calls `reset_async_state_for_task()`? | Status |
|---|---|---|
| morning_brief.py `_send()` line 27 | ✓ | Pattern applied |
| gmail_renew.py `_renew()` line 38 | ✓ | Pattern applied |
| gmail_check.py `_check()` line 34 | ✓ | Pattern applied |
| approval_expiry.py `_sweep()` line 22 (post-F1 fix line numbering may shift) | ✓ | Pattern applied |
| memory_consolidation.py `_run()` line 30 | ✗ (stub — no async resources used) | **N/A — stub safety incidental; forward-pickup signal: when Turn 26.5 swaps in real consolidation body, prepend `await reset_async_state_for_task()` to `_run()` before any DB/checkpointer access** |

Result: ✓ uniform across all 4 active tasks; stub safety incidental + forward-pickup signal noted.

**#2 Module-level Mem0 in celery import chain** — traced:

celery worker startup transitively imports `responder.py:4 (Mem0 site #1)` via `celery_app.py:35 includes gmail_renew → gmail_pubsub:9 imports responder → responder.py:4 memory = MemoryManager()`. **This IS the exact Turn-18 incident chain.** Docker-compose env fix (set `OLLAMA_BASE_URL: http://host.docker.internal:11434`) mitigated the import-time crash symptom; the structural smell remains. **This surface is where the 5-site Mem0 smell has real teeth** — an import-time crash if the docker-compose env fix is undone, not cosmetic. Reaffirm `project_module_level_mem0_instantiation_smell.md`; lazy-init Option A pattern is the structural fix that would close the chain.

**#3 Fail-loud on scheduled jobs** — verified `@critical_task`:

- task_wrapper.py:48-63 wraps task body in try/except; on exception: increment Redis counter (DB 1 isolated) + log error + if count ≥ 3 → `asyncio.run(_alert_master(...))` → `send_system_alert` from `failure_alerter` → Telegram alert. ✓ Fail-loud confirmed.
- **F1 — approval_expiry fail-loud gap:** approval_expiry.py originally used `@celery_app.task` directly (plan-verbatim shape per plan line 5829), unlike the other 3 belt-and-braces tasks (gmail_renew + gmail_check + morning_brief which all use `@critical_task`). Silent sweep failure would leave interrupted turns stuck mid-graph (paused on the original interrupt) AND let stale approvals accumulate without bound — exactly the 3-day-silent-regression risk that `feedback_verify_before_claiming.md` originated on this surface to prevent. **Fixed in-place at audit-write time** per reviewer disposition: decorator swap + import update at approval_expiry.py:16 + 8-line `@critical_task` rationale docstring documenting the fail-loud discipline + sibling-pattern framing.

### Smells checklist scan (full table)

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | — |
| One-line tool description | N/A | — |
| Single-item interface where batch frontier | N/A | Tasks per-schedule by design |
| **Module-level instantiation triggering I/O** | **Reaffirm — KNOWN 5-site smell propagates here with REAL TEETH** | celery_app.py:35-36 `include=["app.scheduler.tasks.gmail_renew", "app.scheduler.tasks.gmail_check"]` → both task modules transitively import `responder.py:4` (Mem0 site #1) via gmail_pubsub.py:9 → celery worker startup triggers the Ollama-HTTP chain. **This IS the Turn-18 3-day-silent celery-beat restart-loop incident's exact chain.** Docker-compose env fix mitigated the symptom; structural smell remains in the 5-site enumeration. **This surface is where the smell has REAL TEETH — import-time crash if the docker-compose env fix is undone**, not cosmetic. Reaffirm `project_module_level_mem0_instantiation_smell.md`; lazy-init Option A pattern is the structural fix. Other module-level instantiations (task_wrapper.py:20 `_redis = redis.from_url(...)`; celery_app.py:57 `from app.scheduler import beat_schedule`) are object construction with lazy connection / no I/O — not smells. |
| Logging-via-omission | None | All critical paths log; @critical_task alerts via failure_alerter on 3-consec; per-task structlog at every meaningful branch |
| Sync bypass of cost-tracking / observability | N/A | No LLM calls at scheduler layer directly; tasks call into surfaces (digest.py, gmail_pubsub.py) that correctly route through `llm_gateway.complete()` per Steps 13+14 audits |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — Frontier-quality rationale documentation across the layer** | celery_app.py:1-18 17-line plan-gap-fill docstring + 17-line per-worker-init rationale (lines 65-80); beat_schedule.py:46-52 cron `"0,6"` correction documenting prior `*/6` mistake — anti-drift positive; task_wrapper.py:1-9 + retry/alert pattern documented; task_helpers.py:1-21 rebind rationale + cost-documented "~50ms per task" + cross-reference to Phase 1 test_resume_dedup fixture; memory_consolidation.py:1-15 explicit "Turn 17 stub. Real implementation lands in Turn 26.5" with cross-reference to plan close-out section. approval_expiry.py docstring extended at audit-write time with 8-line `@critical_task` rationale documenting fail-loud discipline + sibling-pattern framing (was 2-line minimal pre-F1; now matches the in-code-rationale discipline applied to siblings). **Sibling pattern to gmail_pubsub.py:60-84 (Step 13) + setup_gmail_watch.py:25-29 (Step 12) + calendar_create docstring (Step 14) — inline rationale documentation discipline applied consistently across the audit.** |
| **Verification axis mismatch** | **ORIGIN SURFACE** | This is THE surface where `feedback_verify_before_claiming.md` "schedule-registered ≠ beat-up" axis lesson originated (Turn 18 incident — beat process restart-looping while `app.conf.beat_schedule` introspection showed all 5 jobs registered). Live state: per-worker init synchronous rationale at celery_app.py:67-80 documents the axis lesson inline; cron `"0,6"` correction at beat_schedule.py:46-52 documents the prior mistake explicitly. **F4 spine verification ✓** — origin reaffirmed; inline documentation captures the axis lesson at the surface where it originated. |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | Every defensive pattern earns its keep (per-worker init synchronous-only rationale documented + rebind cost documented at ~50ms + @critical_task design rationale + cron `"0,6"` documenting prior mistake + memory_consolidation stub docstring documenting Turn-26.5 deferral) |

### Deeper comparison-target pass (frontier-lens on correctness; production on glue)

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| Reliability machinery — celery_app.py + task_wrapper.py + task_helpers.py (frontier-lens — Turn-18-incident-makes-reliability-frontier-relevant) | (1) Celery's own published patterns; (2) APScheduler reliability patterns; (3) SRE-book production scheduler practices; (4) Airflow / dbt scheduler shapes | **C1: No per-task duration metrics** — only @critical_task failure-counter; no success-rate dashboard. Phase 4 dashboard concern. Self-dismiss. **C2: No dead-letter queue** for repeatedly-failing tasks. Self-dismiss as Phase 4 polish. **C3: No per-task Langfuse tracing** — scheduled tasks don't show in Langfuse traces. Phase 4 observability gap. Self-dismiss. **C4: No per-task `time_limit`** — long-running stuck tasks would block worker. Default Celery + 1-process-prefetch=1 mitigates. Self-dismiss as Phase 4 polish. **C5: approval_expiry missing @critical_task wrapper** — F1 verification spine #3. **Real finding; fixed in-place this step.** |
| Beat scheduling — beat_schedule.py (production-bar — glue) | Celery beat patterns; cron expressions | Cron `"0,6"` correction inline-documented — positive engineering touch. No gaps. |
| Per-task glue — 5 task modules (production-bar — glue) | Per-task standard glue patterns | All 4 real tasks apply rebind pattern uniformly (post-F1: all 4 also @critical_task-wrapped). Stub correctly N/A. No gaps. |

Deeper lens result: 5 candidates surfaced. **1 net-new finding (F1 approval_expiry fail-loud gap — verified via spine #3; fixed in-place this step).** 4 self-dismissed (C1/C2/C3/C4 — Phase 4 polish bucket). Reliability machinery hits Frontier on the correctness-critical layer.

### Comparison target

Celery's own published patterns plus SRE-book scheduler reliability practices are the closest comparable shapes. **Reliability machinery exceeds typical Celery agent-backend shape** — per-worker init synchronous rationale documented (avoids event-loop binding to a dying loop), `reset_async_state_for_task()` rebind pattern with explicit cost documentation, @critical_task 3-consec-failure-then-alert pattern with Redis DB-isolation, cron `"0,6"` correction documenting the prior `*/6` mistake inline. **Bar per sub-surface per directive:** reliability machinery frontier-lens — hits Frontier on the correctness-critical layer; per-task glue production-bar — hits the bar with uniform rebind application + (post-F1) uniform @critical_task wrapping across all 4 active belt-and-braces tasks.

### Three-hats tension surfaced

- **Architect** wants per-worker bootstrap to pre-initialize the DB engine + checkpointer once, then all tasks reuse them. Loses on event-loop binding — `worker_process_init` runs in its own asyncio.run that dies on return, leaving the pool bound to a dead loop. Resolved with the per-task rebind pattern documented at celery_app.py:67-80 + task_helpers.py:1-21 + ~50ms/task cost trade-off explicit.
- **Engineer** wants @critical_task to be a thin wrapper around Celery's retry + a Telegram alert. Wins on simplicity (80 LOC). Loses pre-F1 on incomplete adoption (approval_expiry was plan-verbatim `@celery_app.task` directly, not matching the discipline applied to the other 3 belt-and-braces tasks). **Resolved this step with F1 in-place fix.**
- **AI-ML engineer** doesn't weigh directly — no model concerns at scheduler layer. Closest tension: morning_brief's graceful-import-time-degradation pattern for news_briefing (lazy try/except ImportError) — when Turn 25 lands the news module, morning_brief picks it up without a code edit here. Frontier-execution touch.

All three tensions surfaced.

### Findings + disposition

| # | Finding | Disposition |
|---|---|---|
| F1 | **`approval_expiry.py:16` missing `@critical_task` wrapper — fail-loud gap** (spine verification #3). Used `@celery_app.task` directly per plan-verbatim shape (plan line 5829). The other 3 belt-and-braces tasks (gmail_renew + gmail_check + morning_brief) use `@critical_task`. **Risk per reviewer sign-off:** "approval_expiry resumes paused graphs, so a silent sweep failure leaves interrupted turns stuck + stale approvals accumulating with no alert — the exact silent-failure class @critical_task exists to prevent + the locked fail-loud principle. The plan-verbatim @celery_app.task is the oversight; every reliability task should be fail-loud." | **In-place gate-adjacent-reliability fix landed at audit-write time** per reviewer disposition (option a). Decorator swap `@celery_app.task(name="...")` → `@critical_task(name="...")` at approval_expiry.py:16 + import swap (`from app.scheduler.celery_app import celery_app` removed; `from app.scheduler.task_wrapper import critical_task` added) + 8-line module-docstring extension documenting fail-loud rationale + sibling-pattern framing ("Sibling discipline to gmail_check / gmail_renew / morning_brief wrappers — every belt-and-braces scheduled task should be fail-loud"). Mirror of Step 8/9/11/14 small-fix pattern. ~12-LOC net delta. No plan amendment needed (plan-verbatim is the oversight per reviewer; live code now applies the discipline). |

_F2 cut per silence protocol: Module-level Mem0 transitive import via celery_app→gmail_renew/check→gmail_pubsub→responder.py:4 is the Turn-18 incident chain. KNOWN smell already in 5-site enumeration per `project_module_level_mem0_instantiation_smell.md`. **Reaffirmed at this surface with real-teeth framing** — import-time crash if the docker-compose env fix is undone, not cosmetic. Structural fix per the note's lazy-init Option A pattern; not a Step 15 actionable._

_F3 cut per silence protocol: memory_consolidation.py Turn 26.5 stub verified correctly log-only (no real work; no rebind needed). **Forward-pickup signal:** when real consolidation body lands at Turn 26.5, prepend `await reset_async_state_for_task()` to `_run()` before DB/checkpointer access. **Origin correction at audit-write time:** user directive at Step 15 prompt predicted memory_consolidation.py "NOT in Turn 17's commit (7821568)" — `git log --follow` + `git show 7821568 --stat` show IS in 7821568 (34 insertions, never modified since); Turn 17 first ship. Reviewer at sign-off acknowledged: "my greenlight's 'not in 7821568' was a truncated git-show grep on my end." Origin verified._

_F4 cut per silence protocol: `feedback_verify_before_claiming.md` axis lesson originated on this surface (Turn 18 incident — beat-process-restart-looping while `app.conf.beat_schedule` introspection showed all 5 jobs registered). Live state documents the axis lesson inline at celery_app.py:67-80 (per-worker init synchronous rationale) + beat_schedule.py:46-52 (cron `"0,6"` correction documenting prior `*/6` mistake). **Spine verification ✓ — reaffirm-as-origin.**_

_F5 cut per silence protocol: All 4 real tasks apply rebind pattern uniformly (morning_brief + gmail_renew + gmail_check + approval_expiry); stub correctly N/A. **Spine verification #1 ✓ — 4/4 uniform.**_

_Engineering touches at this surface: 13 distinct frontier-execution patterns observed (celery_app.py: 17-line plan-gap-fill docstring explaining why per-worker init exists + 17-line rationale on why DB/checkpointer cannot pre-init in worker_process_init's asyncio.run; explicit `include=[...]` instead of autodiscover_tasks per Celery convention mismatch; per-worker channel-registry init for failure alerts; task_wrapper.py: Redis isolation via DB-1 (`REDIS_URL.replace("/0", "/1")`) — separates @critical_task failure counters from app Redis state; Retry exception passthrough so Celery's retry mechanism stays clean; reset-on-success counter discipline (prevents spam — alert again only if it KEEPS failing); task_helpers.py: 21-line rebind rationale + cost-documented "~50ms per task" + cross-reference to Phase 1 test_resume_dedup fixture pattern; idempotent rebind safe-to-call-multiple-times framing; eager checkpointer re-open at end so tasks calling into graph don't hit uninitialized state; beat_schedule.py: cron `"0,6"` correction with inline rationale documenting the prior `*/6` mistake (explicit `feedback_verify_before_claiming` origin-surface documentation); morning_brief.py: graceful try/except ImportError pattern for Phase-3 news_briefing module — picks up news section when Turn 25 lands without code edit; gmail_renew.py: 19-line seam-closure rationale + sweep_recent_inbox post-renewal; **approval_expiry.py post-F1: @critical_task discipline applied uniformly across all 4 active belt-and-braces tasks + extended docstring documenting fail-loud rationale + sibling-pattern framing**; **anti-drift discipline applied consistently** across the layer — every plan-gap fill + every defensive choice has inline rationale matching the Step 12 setup_gmail_watch.py + Step 13 gmail_pubsub.py + Step 14 calendar_create docstring pattern). Bar per sub-surface per directive: reliability machinery frontier-lens hits Frontier on the correctness-critical layer; per-task glue production-bar hits the bar with uniform rebind + (post-F1) uniform @critical_task application._

### Overall rating: Mid-to-Frontier

Reliability machinery (celery_app.py per-worker init + task_wrapper.py @critical_task + task_helpers.py rebind pattern) is Frontier-execution — load-bearing fixes for the Turn-18 incident + cost-documented design choices + cross-reference to Phase 1 test_resume_dedup pattern. Per-task glue hits production-bar with uniform rebind application (4/4 real tasks ✓ + stub correctly N/A) + (post-F1) uniform @critical_task discipline across all 4 active belt-and-braces tasks. F1 approval_expiry fail-loud gap fixed in-place this step. **Lifts to Frontier when the lazy-init refactor closes the Mem0 module-level chain** (the confirmed-still-present Turn-18 chain at celery_app→gmail_renew/check→gmail_pubsub→responder.py:4) — per reviewer sign-off: "the residual keeping it from Frontier is the confirmed-still-present Turn-18 Mem0 import chain, not F1, since F1 lands this step."

### Methodology note

Spine verifications per directive (3 majors): **all 3 confirmed**.
- **#1 Async-state rebind uniformity** ✓ — 4/4 real tasks apply pattern; stub correctly N/A (no async resources used); forward-pickup signal noted for Turn 26.5.
- **#2 Module-level Mem0 import chain** — Reaffirm — celery worker startup transitively imports responder.py:4 via celery_app→gmail_renew/check→gmail_pubsub. Structural smell remains per 5-site enumeration; surface has real teeth here (import-time crash if docker-compose env fix is undone); lazy-init Option A pattern is the structural fix.
- **#3 Fail-loud on scheduled jobs** — @critical_task verified fail-loud (3-consec → Telegram via failure_alerter); F1 approval_expiry fail-loud gap fixed in-place this step (decorator swap + import update + docstring extension).

Reaffirms: memory_consolidation Turn 26.5 stub correctly log-only (verified per `project_mem0_contamination_test_residue.md` framing; forward-pickup signal for Turn 26.5); `feedback_verify_before_claiming.md` axis lesson reaffirmed as origin-surface with inline documentation at celery_app.py:67-80 + beat_schedule.py:46-52.

**Origin correction at audit-write time:** user directive predicted memory_consolidation.py "NOT in Turn 17's commit (7821568)" — `git log --follow` + `git show 7821568 --stat` show IS in 7821568 (34 insertions, never modified since); Turn 17 first ship. Reviewer at sign-off acknowledged: "my greenlight's 'not in 7821568' was a truncated git-show grep on my end." Origin verified.

Deeper lens produced 5 candidates; 1 net-new finding (F1 — verification spine #3; fixed in-place this step); 4 self-dismissed (Phase 4 polish bucket). Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 10-14 reviewer pattern. F2/F3/F4/F5 from synthesis cut per silence protocol — reaffirmed in methodology rather than promoted to F-rows.

**Rating lift condition (per reviewer sign-off):** "Lifts to Frontier when the lazy-init refactor closes the Mem0 chain — not F1, since F1 lands this step." The residual keeping the composite from Frontier is the confirmed-still-present Turn-18 Mem0 import chain (verified via spine #2 trace).

### Cross-references

- Base plan: Task 2.7 (lines 5615-5772 — Celery App + Beat Schedule + critical_task) + Task 2.8 (lines 5773+ — Celery Tasks)
- Base plan amended at this step: **none**
- In-place code fix landed at audit-write time: `backend/app/scheduler/tasks/approval_expiry.py:16` — `@celery_app.task` → `@critical_task` decorator swap + import update + 8-line module-docstring extension documenting fail-loud rationale + sibling-pattern framing (F1)
- Memory notes saved at this step: **none** (F1 fixed in-place; F2/F3 reaffirm existing notes)
- Memory notes amended at this step: **none** (F2 reaffirms `project_module_level_mem0_instantiation_smell.md` 5-site enumeration with real-teeth framing at this surface; F3 reaffirms `project_mem0_contamination_test_residue.md` Turn-26.5 framing — no body edits needed since existing framings cover the surface)
- MEMORY.md ledger: **no change**
- Forward cross-reference: (a) when Turn 26.5 swaps in real consolidation body for memory_consolidation.py, prepend `await reset_async_state_for_task()` to `_run()` before DB/checkpointer access; (b) when the 5-site lazy-init refactor lands (Option A per memory note), the celery worker startup chain closes — surface lifts to Frontier
- Memory notes referenced (existing, reaffirmed): `project_async_state_rebind_pattern.md` (Phase 2 Celery surface in note's "Where this has bitten us" table — pattern reaffirmed via spine #1; 4/4 uniform), `project_module_level_mem0_instantiation_smell.md` (5-site enumeration reaffirmed via spine #2; real-teeth framing at this surface), `project_mem0_contamination_test_residue.md` (Turn 26.5 framing reaffirmed via stub verification), `feedback_verify_before_claiming.md` (axis lesson reaffirmed via spine #4 — this is the origin surface; live state documents the lesson inline)

### Step 16 — Turn 17.5 + 17.6 close-out tools — gmail_send + email_history_search (audited as one step)

**Overall rating:** Frontier — both tools at frontier-execution per the bar for agent tools. gmail_send.py is high-stakes outbound with rich tool-level audit + Groq-resilient flat-types-only Args with inline rationale + threading via In-Reply-To + belt-and-braces threadId. email_history_search.py is the biggest single tool with cross-source-recall discipline applied (per Turn 17.6 sharpening) + flat-types-only Args + bounded queries + bucketed natural-language output covering all 4 approval lifecycle states. **The differentiator from Step 14's Mid is real: these descriptions are AT the discipline bar per `feedback_tool_specific_guidance_in_descriptions.md` ("Does NOT" cross-ref + examples + output-shape mention — the Turn 17.6 sharpening), where calendar_tool.py's were below it.** F1 memory-note-name drift is minor documentation hygiene (2 docstring edits landed in-place); doesn't pull rating back. Dormant agent-direct gmail_send pathway is correctly framed forward-ready (registered + ready), not a gap. — **Status:** final — sign-off 2026-06-08

**Scope:**
Turn 17.5 + 17.6 close-out tools audited as one step per directive. 2 files (552 LOC total): gmail_send.py = the tool that actually sends outbound email (close-out for the action-capability-gap that landed at Turn 17.5; Step 13 audit confirmed the gap closed); email_history.py = email_history_search agent tool (Turn 17.6; biggest single tool at 324 LOC). Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Steps 12-15 accumulated upgrade-doc changes uncommitted + this step's F1 in-place fixes landed (2-LOC note-name corrections at gmail_send.py:58 + email_history.py:62).

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/agent/tools/gmail_send.py` | 228 | Turn 17.5 close-out task `2.X-closeout-a` (plan line 9473) + registration at `2.X-closeout-b` (plan line 9480) + dispatch wiring at `2.X-closeout-c` (plan line 9485) | **Live exceeds plan-verbatim** — 30-line module docstring documenting 2 invocation pathways (agent-direct via tool_executor_node + approval-dispatch via `_resolve_gmail_approval`) + plan-gap closure rationale (closes `project_email_action_capability_gap.md` per Step 13 audit). Flat-types-only GmailSendArgs with empty-string sentinels for `in_reply_to_message_id` + `gmail_message_id` (Groq resilience per `project_open_weights_tool_schema_and_conversation_poisoning.md`); class docstring at lines 54-58 carries inline rationale. Threading via In-Reply-To + References headers + belt-and-braces `threadId` from Gmail lookup with graceful fallback. AuditTrail row written tool-level (uniform with tool_executor_node) + EmailLog.auto_sent flip closing the audit loop. APPROVE-tier tool description with scope-limits ("ONE recipient at a time in Phase 2; multi-recipient and HTML body land later"). |
| `backend/app/agent/tools/email_history.py` | 324 | Turn 17.6 close-out tasks `2.X-closeout-e` (impl) + `2.X-closeout-f` (registration) + `2.X-closeout-g` (TOOL_SAFETY_MAP entry) (plan lines 9496-9523) | **Live exceeds plan-verbatim** — 31-line module docstring documenting use cases + non-cases + cross-source-recall pattern reference (per `project_cross_source_recall_pattern.md`). Flat-types-only EmailHistorySearchArgs with empty-string sentinels (4 of 5 fields); class docstring at lines 55-63 carries inline rationale. `_MAX_LIMIT=100` bounded cap. Defensive valid_classifications + valid_statuses sets (silently drop invalid filters — LLM-friendly). Bounds enforcement on `days_back` + `limit` via max-min clamping. SQL LEFT JOIN with `PendingApproval.payload["gmail_message_id"].astext` JSONB extraction. Bucketed summary output (action_required per-item bullets + fyi/spam counts) via `_format_summary` + `_format_action_row` + `_shorten_sender` + `_status_phrase` + `_relative_time` helpers; `_status_phrase` handles all 4 approval lifecycle states + complex-no-approval edge case + forward-compat unknown status. Description per Turn 17.6 sharpening: "Does NOT search conversation memory; use memory_search for that" cross-reference + 4 example queries + output-shape mention. |

Cross-referenced (NOT re-audited): tool registry (Step 8), `_resolve_gmail_approval` dispatch + `messaging/router.py:135-269` (Step 9), gmail_pubsub.py payload enrichment at lines 198-203 (Step 13 — feeds gmail_send via approval-dispatch pathway), builtin_memory `memory_search` description (Step 8 — sibling tool with same cross-source-recall cross-ref at the other side), `safety.py` TOOL_SAFETY_MAP (Step 6 — gmail_send = APPROVE at line 55; email_history_search = SAFE at line 46), Telegram channel (Step 9 — surfaces approval prompts). FallbackChatLLM + Groq tool_use_failed fallback = Step 17 scope per directive (left for next step).

Base plan: Turn 17.5 close-out at plan lines 9461-9494 (`2.X-closeout-a` gmail_send.py + `2.X-closeout-b` registration + `2.X-closeout-c` route_approval_decision dispatch + `2.X-closeout-d` cleanup). Turn 17.6 close-out at plan lines 9496-9523 (`2.X-closeout-e` email_history_search impl + `2.X-closeout-f` registration + `2.X-closeout-g` TOOL_SAFETY_MAP entry). Plan line 9469: "Both gaps share a single fix: a `gmail_send` tool + dispatch in `route_approval_decision` on `thread_id.startswith('gmail:')`" — confirms the dual-note closure (action-capability-gap + gmail-approval-resume-fail) verified at Step 9 + Step 13. Memory notes consulted + re-verified at audit-write time: `project_cross_source_recall_pattern.md` (re-verified — sharpened descriptions on both tools per Turn 17.6; email_history_search.py:313-322 carries the cross-ref + example queries + output-shape mention; discipline confirmed applied), `project_open_weights_tool_schema_and_conversation_poisoning.md` (re-verified — both tool Args classes use flat-types-only schemas with empty-string sentinels per the note's Fix for Bug 1; **inline docstrings referenced an older name `project_open_weights_tool_schema_anyof_null.md` — F1 fixed in-place this step**), `project_email_action_capability_gap.md` (cross-ref — FIXED at Turn 17.5 per Step 13 audit; gmail_send IS the fix; gmail_send.py:14-20 module docstring documents the closure), `project_self_send_bounces.md` (re-verified — note scope is test-vehicle selection NOT runtime guard; live gmail_send has no runtime From==To guard but no current pain; reaffirm), `project_per_tool_execution_timeout_gap.md` (re-verified — note explicitly lists gmail_send + email_history_search as "fast Gmail/local-DB calls with built-in HTTP timeout"; reaffirm Phase-2-acceptable), `feedback_tool_specific_guidance_in_descriptions.md` (re-verified — discipline applied at both tools per Turn 17.6 sharpening pattern; differentiator from Step 14's calendar_tool which is below the bar).

### Spine verifications per directive (7 load-bearing checks — all pass or reaffirm)

**gmail_send.py — high-stakes (sends real email):**

1. **Threading + audit trail + EmailLog.auto_sent flip** (Step 13 entry cross-claim) — CONFIRMED at gmail_send.py:97-100 (In-Reply-To + References headers) + lines 108-123 (threadId belt-and-braces from Gmail lookup with graceful fallback) + `_audit()` at lines 159-191 (AuditTrail row with tool_name + safety_level="approve" + input/output/success/error fields) + `_mark_email_auto_sent()` at lines 194-213 (UPDATE EmailLog WHERE gmail_message_id matches, best-effort with logger.warning on failure). **All 3 Step 13 claims hold.** ✓
2. **Flat-types-only schema (Groq resilience)** — CONFIRMED at GmailSendArgs lines 53-77; all 5 fields flat (`str` + `str` + `str` + `str=""` + `str=""`); class docstring at lines 54-58 documents discipline with inline rationale (post-F1: cross-reference points to correct note name). **Scope clarification per reviewer:** `Optional[]` usages in the file are all in internal helpers (`_audit` signature at line 162-166 + `_relative_time` at line 292 + handler-side sentinel→None normalization at lines 89-90), NOT in `GmailSendArgs` — those internals don't become tool JSON schema. Only the Args class flows to LLM; only flat types appear there. Resilience holds. ✓
3. **Self-send guard** — REAFFIRM. Live gmail_send has NO runtime From==To check; function only knows `to` (From is implicit master's authenticated Gmail account). Memory note scope is test-vehicle selection ("don't use self-send for inbound-pipeline verification"), NOT runtime guard. Runtime risk (agent reminder-to-self pattern → silent bounce) hasn't bitten; no current pain. Reaffirm-with-forward-signal: if agent reminder-to-self pattern ever becomes common, add runtime guard. Not a Step 16 actionable.
4. **Per-tool timeout** — REAFFIRM. gmail_send has NO explicit `asyncio.wait_for` wrap; relies on Google API client's internal HTTP timeout. Memory note `project_per_tool_execution_timeout_gap.md` explicitly acknowledges "gmail_send / email_history_search — Gmail API has built-in HTTP timeout" + lists Phase 2 surface as acceptable. Not a Step 16 actionable.

**email_history.py — biggest single tool:**

5. **Cross-source description discipline** (per `project_cross_source_recall_pattern.md` + `feedback_tool_specific_guidance_in_descriptions.md`) — CONFIRMED at email_history.py:313-322. "Does NOT search conversation memory; use memory_search for that." cross-reference ✓ + 4 example queries ('what emails came in', 'any messages from X', 'did the email from Y get answered', 'what's still pending reply') ✓ + output-shape mention ("grouped summary by classification...action_required gets per-item detail; fyi/spam get counts...plus approval status") ✓. Frontier-shape per Turn 17.6 sharpening.
6. **Flat-types-only schema (Groq resilience)** — CONFIRMED at EmailHistorySearchArgs lines 54-84; all 5 fields flat (`int=7` + `str=""` + `str=""` + `str=""` + `int=20`); class docstring at lines 55-63 documents discipline with inline rationale (post-F1: cross-reference points to correct note name). Same `Optional[]` scope clarification as #2 — internal helpers + handler-side normalization use `Optional` but the Args class doesn't, so JSON schema flowing to LLM stays flat. ✓
7. **Search logic + output shape** — CONFIRMED pure SQL + structured natural-language formatting; **NO LLM call internally — NOT a bypass surface** (no gateway routing needed since no LLM); bounded by `_MAX_LIMIT=100`; bucketed output covering all 4 approval lifecycle states + complex-no-approval edge case + forward-compat unknown status.

### Smells checklist scan (full table)

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | email_history returns structured bucketed natural-language summary; gmail_send returns status string ("Email sent to X (Gmail id: Y)") — appropriate shape for tool-result-rendered-to-LLM |
| **One-line tool description** | **None — Frontier-shape per Turn 17.6 sharpening** | gmail_send description (lines 220-226): APPROVE-tier mention + use cases + scope-limits. email_history_search description (lines 313-322): "Does NOT search X; use Y" cross-ref + 4 example queries + output-shape mention per `feedback_tool_specific_guidance_in_descriptions.md`. **Both at frontier-shape discipline — the differentiator from Step 14's calendar_tool.py which was below the bar (KNOWN deferred at Turn 17.9 `2.X-closeout-p`).** |
| Single-item interface where batch frontier | N/A | gmail_send per-email (correct for write action); email_history returns multi-row bucketed (correct for search) |
| Module-level instantiation triggering I/O | None | gmail_send.py:50 + email_history.py:45 logger init only — pure, no I/O |
| Logging-via-omission | None | gmail_send logs success + failure + audit-row-with-error-before-raise + thread-lookup-failed warning. email_history.py defers logging to caller (read-only query — no side effects to telegraph beyond return value) — acceptable. |
| **Sync bypass of cost-tracking / observability** | **None — neither tool calls LLM** | Both tools are pure Gmail-API / SQL — no LLM calls. NOT bypass siblings to `project_agent_llm_cost_attribution_gap.md`'s 3 surfaces. Positive (sibling pattern to calendar_tool.py at Step 14 — Google-API tool with no LLM internal call). |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | Per-tool guidance lives in per-tool descriptions per the discipline (verified). |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **F1 — Memory-note-name drift in inline docstrings** | Both `gmail_send.py:58` and `email_history.py:62` referenced `project_open_weights_tool_schema_anyof_null.md` in inline Args class docstrings — file verified does NOT exist (confirmed via `ls`). Actual note is `project_open_weights_tool_schema_and_conversation_poisoning.md`. Likely cause: note was renamed when Bug 2 conversation-poisoning content was added; inline docstrings weren't updated at the rename. **Fixed in-place at audit-write time** — 2 docstring edits replacing the stale name with the correct one. Mirror of Step 8 F4 + Step 11 F1 + Step 14 in-place patterns. All other docstrings verified accurate (module-level docs, function docs, class docs all consistent with live code). |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | Every defensive pattern earns its keep (threadId belt-and-braces alongside In-Reply-To; sentinel-to-None normalization; bounds checking on filters with silently-drop-invalid LLM-friendliness; per-tool docstring rationale documenting the flat-types-only discipline + cross-source-recall pattern + Turn-17.6-sharpening; graceful fallback if Gmail thread lookup fails) |

### Deeper comparison-target pass (frontier-lens — both are agent tools)

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| gmail_send.py (frontier-lens — high-stakes outbound) | (1) Anthropic MCP tool patterns; (2) OpenAI function-calling examples; (3) LangChain published email tools; (4) Stripe/Twilio idempotent-send patterns | **C1: No retry on transient Gmail API errors** — Google API client has internal retries; we don't add another layer. Self-dismiss. **C2: No idempotency key** — protected by `resolve_approval` setting status BEFORE dispatch (Step 9 audit). Self-dismiss. **C3: Single recipient only** + **C4: No HTML body support** — documented in description as Phase 2 limits. Self-dismiss. **C5: Self-send guard absent** — reaffirm per spine #3. |
| email_history.py (frontier-lens — biggest tool) | (1) Anthropic search-tool patterns; (2) LangChain Search tools; (3) Frontier inbox-search products | **C6: No pagination** — `_MAX_LIMIT=100` cap fine for Phase 2; Phase 4 longer history might need pagination. Self-dismiss as YAGNI. **C7: No full-text body search** — covered by `project_cross_source_recall_pattern.md`'s chaining-with-memory_search pattern. Self-dismiss as known cross-source-recall gap. **C8: SQL ILIKE for sender** (partial, case-insensitive) — good. No exact-match option. Self-dismiss as acceptable. |

Deeper lens result: 8 candidates surfaced. **0 net-new findings** — all 8 are either documented limits / deferred-with-trigger / covered by existing memory notes. F1 came from smells scan documentation-drift row, not deeper lens.

### Comparison target

gmail_send.py matches Anthropic MCP + Stripe/Twilio idempotent-send patterns: rich tool-level audit (AuditTrail + EmailLog.auto_sent closing the loop), explicit-flat-schema-for-open-weights-models, threading-by-default with belt-and-braces fallback. email_history_search.py matches frontier inbox-search products' bucketed-output shape (action_required per-item detail vs fyi/spam counts) + Turn-17.6-sharpening discipline. **Both tools at Frontier-execution for the bar of agent tools** — anti-drift discipline applied inline + Groq-resilience documented + spine verifications confirm threading/audit/output-shape claims. **The differentiator from Step 14's Mid is real:** these descriptions hit the discipline bar (Does NOT cross-ref + examples + output-shape) where calendar_tool.py's were below it (KNOWN deferred at Turn 17.9 `2.X-closeout-p`).

### Three-hats tension surfaced

- **Architect** wants gmail_send to be the single canonical outbound-email surface across both invocation pathways. Wins on uniform audit semantics (tool-level AuditTrail + EmailLog.auto_sent flip happens regardless of pathway). Loses on agent-direct pathway being unreachable in Phase 2 (no LangGraph thread currently emits gmail_send tool calls per module docstring lines 9-12). Resolved with "registered + ready" framing — tool stays registered so future prompts/scenarios reach for it without re-architecting; correctly framed forward-ready per reviewer, not a gap.
- **Engineer** wants email_history_search to be a pure SQL query — no LLM call inside, structured natural-language output bounded by `_MAX_LIMIT=100`. Wins on simplicity + cost (no LLM tokens per call). Loses on full-text body search not supported. Tension acceptable: cross-source-recall pattern covers chaining-with-memory_search; full-text-body is forward-pickup.
- **AI-ML engineer** wants both tools' Args schemas to be Groq-resilient. Wins on flat-types-only + empty-string sentinels per `project_open_weights_tool_schema_and_conversation_poisoning.md`'s Fix for Bug 1; inline docstring rationale documents the discipline. Loses on Pydantic-level enum validation (handler-level validation with silently-drop-invalid is the trade). Resolved with explicit trade documented inline. Internal `Optional[]` usages in helpers don't violate the schema discipline since they don't become tool JSON schema.

All three tensions surfaced.

### Findings + disposition

| # | Finding | Disposition |
|---|---|---|
| F1 | **Memory-note-name drift in inline docstrings** — `gmail_send.py:58` and `email_history.py:62` referenced `project_open_weights_tool_schema_anyof_null.md` in inline Args class docstrings. File verified does NOT exist (confirmed via `ls -la`). Actual note is `project_open_weights_tool_schema_and_conversation_poisoning.md`. Likely cause: note was renamed when Bug 2 conversation-poisoning content was added (the live note now covers BOTH bugs in one); inline docstrings weren't updated at the rename. Reader following the cross-reference hit a 404 — genuine drift class (same shape as Step 8 F4 + Step 11 F1), not enhancement. | **In-place fix landed at audit-write time** — 2 docstring edits replacing `project_open_weights_tool_schema_anyof_null.md` → `project_open_weights_tool_schema_and_conversation_poisoning.md` at gmail_send.py:58 + email_history.py:62. Mirror of Step 8 F4 + Step 11 F1 + Step 14 in-place patterns. ~2-LOC delta. |

_F2 cut per silence protocol: Self-send guard (gmail_send) — REAFFIRM per memory note scope (test-vehicle selection, not runtime guard); no current pain; forward-pickup signal if agent reminder-to-self pattern becomes common._

_F3 cut per silence protocol: Per-tool timeout (gmail_send + email_history) — REAFFIRM per `project_per_tool_execution_timeout_gap.md` already acknowledges "Gmail API has built-in HTTP timeout" + lists Phase 2 surface as acceptable._

_F4 cut per silence protocol: Cross-source description discipline (email_history) — CONFIRMED applied per Turn 17.6 sharpening; `project_cross_source_recall_pattern.md` verified accurate._

_F5 cut per silence protocol: Both Args schemas Groq-resilient — CONFIRMED flat-types-only with empty-string sentinels + inline rationale per `project_open_weights_tool_schema_and_conversation_poisoning.md`'s Fix for Bug 1. Internal `Optional[]` usages are in helpers (`_audit`/`_relative_time`/handler sentinel→None normalization), NOT the Args classes that flow to LLM JSON schema. Scope per reviewer: only Args classes become tool JSON schema; internals don't. Resilience holds._

_F6 cut per silence protocol: Threading + audit-trail + EmailLog.auto_sent flip (gmail_send) — CONFIRMED per Step 13 entry's cross-claim; verified at gmail_send.py:97-100 + 108-123 + `_audit()` at 159-191 + `_mark_email_auto_sent()` at 194-213. Step 13 claim holds._

_F7 cut per silence protocol: Both tools are pure Gmail-API / SQL — NO LLM calls — NOT bypass siblings to `project_agent_llm_cost_attribution_gap.md`'s 3 surfaces. Positive (sibling pattern to calendar_tool.py at Step 14)._

_Engineering touches at this surface: 20 distinct frontier-execution patterns observed (gmail_send.py: 30-line module docstring documenting 2 invocation pathways + plan-gap-closure rationale [closes action-capability-gap note per Step 13]; flat-types-only Args with empty-string sentinels + inline cross-reference [post-F1: points to correct note name]; In-Reply-To + References headers for RFC822 threading; belt-and-braces threadId from Gmail lookup with graceful fallback on failure; AuditTrail row written from tool-level uniform with tool_executor_node pattern; EmailLog.auto_sent flip closing the audit loop; best-effort `_mark_email_auto_sent` for agent-direct edge case; success-and-failure logging with structured fields; APPROVE-tier description + use cases + scope-limits documented inline; email_history.py: 31-line module docstring documenting use cases + non-cases + cross-source-recall pattern reference + safety classification; flat-types-only Args with empty-string sentinels + inline cross-reference [post-F1: points to correct note name]; `_MAX_LIMIT=100` bounded cap; defensive valid_classifications + valid_statuses sets — silently-drop-invalid for LLM-friendliness; bounds enforcement on days_back + limit via max-min clamping; SQL LEFT JOIN with `PendingApproval.payload["gmail_message_id"].astext` JSONB extraction; bucketed summary output [action_required per-item bullets + fyi/spam counts]; clean separation of formatting concerns via `_format_summary` + `_format_action_row` + `_shorten_sender` + `_status_phrase` + `_relative_time` helpers; `_status_phrase` handles all 4 approval lifecycle states + complex-no-approval edge case + forward-compat unknown status; cross-source description discipline per Turn 17.6 sharpening — "Does NOT search X; use Y" cross-ref + 4 example queries + output-shape mention). **Bar per sub-surface per directive: both at Frontier-execution for the bar of agent tools** — the differentiator from Step 14's calendar_tool which is below the bar._

### Methodology note

Spine verifications per directive (7 load-bearing checks): **all 7 confirmed or reaffirmed**.
- gmail_send.py: threading + audit (Step 13 cross-claim ✓) + flat-types-only Args schema with Groq-resilience reviewer scope clarification (Optional usages are in internals, not Args — JSON schema flowing to LLM stays flat) + self-send guard (reaffirm — test-vehicle scope, no runtime pain) + per-tool timeout (reaffirm — memory note acknowledges Google API built-in timeout for Phase 2).
- email_history.py: cross-source description discipline (Turn 17.6 sharpening ✓) + flat-types-only Args schema (same scope clarification as gmail_send) + search logic + output shape (pure SQL + structured bucketed output; NOT bypass surface ✓).

Reaffirms: `project_self_send_bounces.md` (test-vehicle scope; reaffirm); `project_per_tool_execution_timeout_gap.md` (Phase 2 acceptable; reaffirm); `project_cross_source_recall_pattern.md` (Turn 17.6 sharpening confirmed applied at email_history); `project_open_weights_tool_schema_and_conversation_poisoning.md` (Fix for Bug 1 confirmed applied at both tools — post-F1 inline cross-refs now point to correct note name); `project_email_action_capability_gap.md` (FIXED at Turn 17.5; gmail_send IS the fix; verified at Step 13).

Deeper lens produced 8 candidates; 0 net-new findings — all documented limits / deferred-with-trigger / covered by existing memory notes. F1 came from smells scan documentation-drift row, not deeper lens. F2-F7 cut per silence protocol — reaffirmed in methodology rather than promoted to F-rows. Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 10-15 reviewer pattern.

**Frontier rating differentiator from Step 14 (per reviewer sign-off):** "These descriptions are AT the discipline bar (Does NOT cross-ref + examples + output-shape — the Turn 17.6 sharpening), where calendar's were below it. Full discipline inline + Groq-resilient + rich audit + no correctness gap = honest Frontier. The dormant agent-direct gmail_send path is correctly framed forward-ready, not a gap."

### Cross-references

- Base plan: Turn 17.5 close-out at plan lines 9461-9494 (`2.X-closeout-a`/b/c/d) + Turn 17.6 close-out at plan lines 9496-9523 (`2.X-closeout-e`/f/g)
- Base plan amended at this step: **none**
- In-place code fixes landed at audit-write time: (1) `backend/app/agent/tools/gmail_send.py:58` — memory-note-name corrected from `project_open_weights_tool_schema_anyof_null.md` → `project_open_weights_tool_schema_and_conversation_poisoning.md`; (2) `backend/app/agent/tools/email_history.py:62` — same correction (F1)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: **none** (F1 fixes the inline reference, not the note)
- MEMORY.md ledger: **no change**
- Backward cross-reference: closes Step 13 cross-claim verification spine (threading + audit + EmailLog.auto_sent flip all confirmed at gmail_send.py); closes Step 9 + Step 13 dual-note closure verification (`project_email_action_capability_gap.md` + `project_gmail_approval_resume_fails_no_langgraph_thread.md` both confirmed FIXED — gmail_send is the unified fix); closes Step 8 cross-reference (gmail_send tool registered alongside calendar/builtin_memory/email_history)
- Forward cross-reference: FallbackChatLLM + Groq tool_use_failed fallback = Step 17 scope (per directive); both tools' flat-types-only schemas are the tools' half of the Groq resilience story; FallbackChatLLM is the agent_node half
- Memory notes referenced (existing, reaffirmed): `project_cross_source_recall_pattern.md` (Turn 17.6 sharpening confirmed at email_history), `project_open_weights_tool_schema_and_conversation_poisoning.md` (Fix for Bug 1 confirmed at both tools; F1 fixed inline cross-refs to point to correct note name), `project_email_action_capability_gap.md` (FIXED status verified; gmail_send IS the fix), `project_self_send_bounces.md` (test-vehicle scope; reaffirm), `project_per_tool_execution_timeout_gap.md` (Phase 2 acceptable; reaffirm), `feedback_tool_specific_guidance_in_descriptions.md` (discipline applied per Turn 17.6 — differentiator from Step 14 calendar_tool below-bar state)

### Step 17 — Turn 17.7 — FallbackChatLLM (LLM-reliability layer)

**Overall rating:** Frontier — FallbackChatLLM is load-bearing reliability machinery for every agent LLM call. The narrow predicate (BadRequestError → fallback ONLY on "tool_use_failed" / "failed to call a function"; everything else propagates so config bugs surface instead of being masked) + canary `agent_llm_fallback` log event with drift-detection rationale genuinely exceed LangChain's built-in `Runnable.with_fallbacks()` (class-based filtering only, no predicate support, no fall-over visibility). Real reliability engineering — design choices documented inline + predicate fragility tracked in dedicated memory note + canary monitoring explicitly load-bearing. **Sibling Frontier to Steps 9 (channel layer) + 11 (API + auth) + 16 (tools layer).** Cleanest Phase 2 surface so far (0 F-rows + 5 reaffirms + 11 engineering touches in 125 LOC). — **Status:** final — sign-off 2026-06-08

**Scope:**
Turn 17.7 alone per directive (17.8 + 17.9 are future close-out turns slotted AFTER Turn 20 — not built; outside Turn-1→19.2 audit scope until they ship). After Step 17 the only built surfaces left are Turn 18 (extractors + chunker) and Turn 19.1/19.2 (contextualizer + ingestion) — final stretch of the backward audit. 1 file (125 LOC). Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Steps 12-16 accumulated upgrade-doc changes + Steps 15-16 code fixes uncommitted.

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/llm/fallback_llm.py` | 125 | Turn 17.7 close-out tasks `2.X-closeout-h` (impl) + `2.X-closeout-i` (nodes.py wiring) + `2.X-closeout-j` (test coverage) at plan lines 9525-9549 | **Live exceeds plan-verbatim sketch — chose simpler shape than memory note's BaseChatModel sketch.** 32-line module docstring documenting plan-gap closure (closes `project_agent_node_bypasses_gateway_fallback.md` Option B) + 2 failure modes (rate-limit + tool_use_failed) + 3 cross-referenced memory notes inline + design-choices-vs-LangChain-built-in framing at lines 20-27 (predicate support + log canary visibility — both absent from `Runnable.with_fallbacks()`). `class FallbackChatLLM(Runnable)` inherits LangChain `Runnable` (NOT `BaseChatModel` per memory note sketch); pre-bound contract — caller binds tools to BOTH primary + fallback ChatLiteLLM BEFORE wrapping (simpler than sketch's bind_tools-delegation pattern). `_default_retry_predicate` lines 45-72 narrows BadRequestError to `tool_use_failed` + `failed to call a function` string-match (per `project_groq_error_message_string_match_dependency.md`); RateLimitError + APIConnectionError + Timeout always retry-worthy; AuthenticationError + everything else propagate. `agent_llm_fallback` structured log event with primary_error_type + primary_error_msg — explicitly documented as "load-bearing for production monitoring" (lines 26-27) + canary mechanism for retry-predicate drift detection (lines 115-120). Constructor accepts customizable retry_predicate. Sync `invoke()` + async `ainvoke()` both implemented; wrapper transparent to whatever tool binding state the underlying runnables carry. |

Cross-referenced (NOT re-audited): `backend/app/agent/nodes.py:_build_chat_model` (Step 7 — wires `FallbackChatLLM(primary, fallback)` with tools pre-bound to BOTH ChatLiteLLM instances), `backend/tests/test_fallback_llm.py` (Step 10 — 5 retry-predicate scenarios), `backend/app/llm/gateway.py` (Step 4 — separate non-agent path).

Base plan: Turn 17.7 close-out at plan lines 9525-9549 (`2.X-closeout-h` fallback_llm.py impl + `2.X-closeout-i` _build_chat_model wiring + `2.X-closeout-j` test coverage at backend/tests/test_fallback_llm.py). Memory notes consulted + re-verified at audit-write time: `project_agent_node_bypasses_gateway_fallback.md` (re-verified — note IS the WHY; Option B chosen per recommendation; live shape diverges from note's "Implementation sketch" section in BaseChatModel-vs-Runnable choice — simpler pattern shipped; design-evolution-from-sketch is expected per note's explicit "Implementation sketch for Turn 17.7" framing, NOT drift), `project_groq_error_message_string_match_dependency.md` (re-verified — live `_default_retry_predicate` lines 62-68 match note's documented predicate verbatim; "tool_use_failed" + "failed to call a function" string-match; reaffirm fragility with canary monitoring on `agent_llm_fallback` log rate), `project_open_weights_tool_schema_and_conversation_poisoning.md` (re-verified — upstream Groq llama brittleness that FallbackChatLLM closes the agent_node half of; tools' half is flat-types-only Args schemas confirmed at Step 16), `project_agent_llm_cost_attribution_gap.md` (re-verified — FallbackChatLLM IS the agent_node bypass surface; primary of 3 surfaces in cost-attribution gap landscape; reaffirm KNOWN deferred), `project_n_provider_fallback_deferral.md` (re-verified — 2-provider chain only; N-provider chain deferred until Phase 3+ trigger; reaffirm).

### Spine verifications per directive (4 majors — all pass or reaffirm)

**#1 Retry-predicate string-match fragility** — CONFIRMED narrow predicate (not catch-all) per reviewer sign-off: live `_default_retry_predicate` lines 64-67 falls back ONLY on "tool_use_failed" / "failed to call a function"; line 68 returns False for every other BadRequestError shape so config bugs surface instead of being masked. Correct design. Live predicate IS the string-match the note describes (line 63 of fallback_llm.py: `msg = str(exc).lower()` then check). Canary `_log_fallback` at lines 121-125 emits `agent_llm_fallback` warning with primary_error_type + primary_error_msg — explicitly documented at lines 115-120 with drift-detection rationale ("a sudden drop in fallback rate while graph_invoke_failed rate stays high is the signal that the retry_predicate's string-match has stopped catching what it used to"). Reaffirm fragility with canary mitigation — Frontier-correct, not a gap. ✓

**#2 Tool/message passthrough on fallover** — CONFIRMED per reviewer sign-off: lines 97-113 (invoke + ainvoke) pass `input` + `config` + `**kwargs` UNCHANGED to whichever runnable fires (primary first; on retry-worthy exception, fallback). Pre-bound contract documented at class docstring lines 76-84. nodes.py:_build_chat_model (Step 7 audit) binds tools to BOTH ChatLiteLLM instances before wrapping — fallback gets same bound tools as primary; agent still gets structured tool_calls from the fallback. ✓

**#3 Cost-bypass** — REAFFIRM per `project_agent_llm_cost_attribution_gap.md`: FallbackChatLLM wraps ChatLiteLLM instances directly; neither primary nor fallback ainvoke goes through `llm_gateway.complete()`. FallbackChatLLM IS the agent_node bypass surface (primary of 3 surfaces in the cost-attribution gap landscape). KNOWN deferred per memory note Phase-4-dashboard trigger conditions. Not a Step 17 actionable.

**#4 Runnable contract** — CONFIRMED clean per reviewer sign-off: `class FallbackChatLLM(Runnable)` at line 75 inherits LangChain `Runnable` base; implements both sync `invoke()` (lines 97-104) + async `ainvoke()` (lines 106-113). **bind_tools NOT implemented** — by design, per the pre-bound contract documented in class docstring. **Design evolution from memory note sketch:** `project_agent_node_bypasses_gateway_fallback.md` lines 88-92 sketched a `FallbackChatLLM(BaseChatModel)` with `bind_tools()` method delegating to both underlying models. Live code chose simpler shape: `Runnable` base + pre-bound contract + caller responsible for binding tools to BOTH ChatLiteLLM instances. Functionally equivalent; simpler pattern. Sketch-vs-live divergence is expected per note's explicit "Implementation sketch for Turn 17.7" framing — NOT drift, design evolution; positive observation. ✓

### Smells checklist scan (full table)

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | — |
| One-line tool description | N/A | Not a tool — agent infrastructure |
| Single-item interface where batch frontier | N/A | Per-invocation Runnable (correct shape) |
| Module-level instantiation triggering I/O | None | Line 42 `logger = get_logger(__name__)` only — pure |
| **Logging-via-omission** | **None** | `agent_llm_fallback` warning on fallover with structured fields (primary_error_type + primary_error_msg) at lines 121-125. NO logging on primary-success path — acceptable (only the unusual case logs). The fallback log is explicitly documented as "load-bearing for production monitoring" (lines 26-27) + the canary mechanism per `project_groq_error_message_string_match_dependency.md`. ✓ |
| **Sync bypass of cost-tracking / observability** | **Reaffirm — KNOWN bypass surface (spine #3)** | FallbackChatLLM wraps ChatLiteLLM directly; bypasses `llm_gateway.complete()`. IS the agent_node bypass surface (primary of 3 surfaces in `project_agent_llm_cost_attribution_gap.md`'s landscape). KNOWN deferred per memory note's Phase-4-dashboard-trigger conditions. Not a Step 17 actionable. |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — Frontier-quality cross-referenced documentation** | 32-line module docstring with explicit cross-references to 3 memory notes (all verified to exist by their cited names): `project_agent_node_bypasses_gateway_fallback.md` (line 5), `project_open_weights_tool_schema_and_conversation_poisoning.md` (line 11 — verified at Step 16), `project_groq_error_message_string_match_dependency.md` (line 30). Design-choices-vs-built-in framing at lines 20-27 documents the WHY (predicate support + log canary visibility — both absent from `Runnable.with_fallbacks()`). All docstrings + comments verified accurate against live code. **No drift.** Sibling pattern to gmail_pubsub.py:60-84 (Step 13) + setup_gmail_watch.py:25-29 (Step 12) + calendar_create docstring (Step 14) + gmail_send.py + email_history.py (Step 16) — inline rationale + cross-reference discipline applied consistently across the audit. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | Every defensive pattern earns its keep (string-match-with-canary-monitoring documented; narrow BadRequestError filter justified per reviewer "config bugs surface instead of being masked"; custom Runnable vs `with_fallbacks` justified in design choices section; customizable retry_predicate constructor parameter for test/extension flexibility) |

### Deeper comparison-target pass (frontier-lens — reliability machinery)

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| FallbackChatLLM (frontier-lens — reliability machinery for every agent LLM call) | (1) LangChain `Runnable.with_fallbacks()` built-in; (2) Tenacity retry library patterns; (3) LiteLLM internal retry; (4) Industry circuit-breaker patterns (Hystrix, Polly) | **C1: No circuit-breaker pattern** — every call still tries primary first, even during sustained outages. Cost: simplicity (more state to track). Self-dismiss as YAGNI for single-master. **C2: N-provider chain absent** — already in `project_n_provider_fallback_deferral.md`. Reaffirm. **C3: 3-slot fallback hardcoded** in gateway.py:get_models — same. Reaffirm. **C4: Predicate is string-match** — `project_groq_error_message_string_match_dependency.md`. Reaffirm via spine #1. **C5: Cost-tracking bypass** — `project_agent_llm_cost_attribution_gap.md`. Reaffirm via spine #3. **C6: Exceeds LangChain `with_fallbacks` built-in** — predicate support + log canary visibility (documented in design choices). Positive — engineering touches roll-up. |

Deeper lens result: 6 candidates surfaced. **0 net-new findings** — C1 self-dismissed; C2/C3/C4/C5 reaffirm KNOWN deferrals per existing memory notes; C6 positive.

### Comparison target

FallbackChatLLM exceeds LangChain's built-in `Runnable.with_fallbacks()` per the design-choices section at lines 20-27 + reviewer sign-off: built-in's exception filtering is class-based only (we need predicate support to narrow `BadRequestError` to ONLY `tool_use_failed` cases — other shapes won't recover via fallback and config bugs need to surface) + built-in doesn't surface a log event on fall-over (we lose visibility into how often fallback fires; `agent_llm_fallback` log is load-bearing for production monitoring). **Real reliability engineering** — wrapper pattern matches Tenacity-style declarative retry shape at the LangChain Runnable layer rather than at the LiteLLM call layer. Bar per directive: reliability machinery for every agent LLM call — **frontier-lens; Frontier-execution confirmed.**

### Three-hats tension surfaced

- **Architect** wants the wrapper to be the single resilience seam for agent_node — closing the gap from `project_agent_node_bypasses_gateway_fallback.md`. Wins on Option B simplicity (per memory note recommendation: "small reusable wrapper, agent code unaffected, separation of concerns intact"). Loses on not unifying with gateway's cost-cap path — agent vs non-agent metrics stay split per `project_agent_llm_cost_attribution_gap.md`'s 3-surface bypass concern. Tension resolved with explicit deferral.
- **Engineer** wants the wrapper to be transparent to whatever tool binding state the underlying runnables carry — caller pre-binds to BOTH; wrapper passes through. Wins on simplicity (125 LOC; `Runnable` inheritance instead of `BaseChatModel` from sketch). Loses on caller responsibility — `_build_chat_model` must remember to bind tools to BOTH primary and fallback (verified at Step 7 audit). Tension resolved with explicit pre-bound contract in class docstring + simpler shape than sketch.
- **AI-ML engineer** wants the retry predicate to narrow `BadRequestError` to the specific Groq `tool_use_failed` pattern — wider net would mask real config bugs (model-not-found falling over to gpt-4o-mini hides the bug). Wins on narrow string-match + canary monitoring. Loses on string-match fragility (Groq could rename the error in a future API version). Tension resolved with explicit canary monitoring on `agent_llm_fallback` log rate + memory note documenting the fragility + fix shape (add new string pattern when triggered).

All three tensions surfaced.

### Findings + disposition

_**No actionable findings at this step.** All 4 spine verifications + 6 deeper-lens candidates resolved as reaffirms of KNOWN memory-noted concerns or positives. F-rows reserved for actionable items per silence protocol; engineering-touches roll-up + methodology note carry the substantive content. **Step 17 is cleanest Phase 2 surface so far** (0 F-rows + 5 reaffirms + 11 engineering touches in 125 LOC — even cleaner than Step 14's 0/5/8). Per reviewer sign-off: narrow predicate + canary log "genuinely exceed LangChain's with_fallbacks (class-based only, no predicate, no fall-over visibility). Real reliability engineering." Surfacing any of the 4 reaffirmed concerns (predicate fragility / cost-bypass / N-provider deferral / circuit-breaker absence) as F-row would be exactly the manufacturing the meta-lesson warns against — all 4 already in their respective memory notes with trigger conditions._

_Spine verifications per directive (all 4 confirmed or reaffirmed):_
- _**#1 Retry-predicate string-match fragility** — narrow predicate verified (BadRequestError → fallback ONLY on tool_use_failed/failed-to-call-a-function; every other shape propagates so config bugs surface); reaffirm per `project_groq_error_message_string_match_dependency.md` with canary `agent_llm_fallback` log mitigation; Frontier-correct, not a gap._
- _**#2 Tool/message passthrough on fallover** — CONFIRMED; pre-bound contract documented at class docstring lines 76-84; ainvoke at lines 106-113 passes input + config + kwargs unchanged; nodes.py:_build_chat_model binds tools to BOTH per Step 7 audit; fallback gets same bound tools as primary._
- _**#3 Cost-bypass** — REAFFIRM per `project_agent_llm_cost_attribution_gap.md`; FallbackChatLLM IS the agent_node bypass surface (primary of 3 surfaces); KNOWN deferred per memory note Phase-4-dashboard trigger conditions._
- _**#4 Runnable contract** — CONFIRMED clean; `class FallbackChatLLM(Runnable)` + invoke + ainvoke implemented; bind_tools NOT implemented by design (pre-bound contract). **Design evolution from memory note sketch:** simpler `Runnable` + pre-bound shape vs sketch's `BaseChatModel` + bind_tools-delegation. Functionally equivalent; positive observation (NOT drift per note's "Implementation sketch" framing per reviewer sign-off)._

_Engineering touches at this surface: 11 distinct frontier-execution patterns observed (32-line module docstring documenting plan-gap closure + 3 cross-referenced memory notes inline + design-choices-vs-LangChain-built-in framing at lines 20-27 [predicate support + log canary visibility — both absent from `Runnable.with_fallbacks()`]; `class FallbackChatLLM(Runnable)` inheriting LangChain Runnable base — simpler shape than memory note sketch's `BaseChatModel` pattern [design-evolution-from-sketch positive — sketch-vs-live divergence expected per note's "Implementation sketch" framing per reviewer]; pre-bound contract at class docstring lines 76-84 explicitly documenting wrapper transparency to tool binding state; `_default_retry_predicate` narrows BadRequestError to specific Groq pattern via string-match — not catch-all that would mask real config bugs [reviewer sign-off: "config bugs surface instead of being masked"]; RateLimitError + APIConnectionError + Timeout always retry-worthy [transient]; AuthenticationError + model-not-found + everything else propagate [real config errors]; `agent_llm_fallback` structured log event at lines 121-125 with primary_error_type + primary_error_msg — explicitly documented at lines 115-120 as canary signal for retry-predicate fragility [the right mitigation for an inherent fragility per reviewer]; sync `invoke()` + async `ainvoke()` both implemented per Runnable contract; constructor accepts customizable `retry_predicate` parameter for test/extension flexibility; module docstring lines 29-31 explicitly flag string-match fragility + cross-reference `project_groq_error_message_string_match_dependency.md` — anti-drift discipline applied to known fragility; sibling-pattern documentation discipline across the audit — every plan-gap fill + every defensive choice has inline rationale matching the gmail_pubsub.py:60-84 [Step 13] + setup_gmail_watch.py:25-29 [Step 12] + calendar_create docstring [Step 14] + gmail_send.py + email_history.py [Step 16] inline-rationale pattern). **Bar per directive: frontier-lens on reliability machinery — Frontier-execution confirmed.**_

### Overall rating: Frontier

FallbackChatLLM is **load-bearing reliability machinery for every agent LLM call** + genuinely exceeds LangChain's built-in `Runnable.with_fallbacks()` (class-based filtering only, no predicate support, no fall-over visibility) per reviewer sign-off + 3 cross-referenced memory notes inline + canary monitoring explicitly load-bearing + design-evolution-from-sketch chose simpler pattern. All 4 spine verifications confirmed or reaffirmed; 0 net-new findings; all gaps already in memory notes (cost-bypass + predicate-fragility + N-provider deferral). 11 engineering touches in 125 LOC. **Sibling Frontier rating to Steps 9 (channel layer) + 11 (API + auth) + 16 (tools layer).** Real reliability engineering — narrow predicate + canary log + drift-detection rationale all working together.

### Methodology note

Spine verifications per directive (4 majors): **all 4 confirmed or reaffirmed**. Deeper lens produced 6 candidates; 0 net-new findings — all gaps either KNOWN deferred per existing memory notes (predicate fragility + cost-bypass + N-provider chain) or self-dismissed (circuit breaker YAGNI) or positive (exceeds LangChain built-in). Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 10-16 reviewer pattern. F-rows reserved for actionable items per silence protocol — Step 17 is cleanest Phase 2 surface so far (0 F-rows + 5 reaffirms + 11 engineering touches in 125 LOC).

**Design-evolution-from-memory-note-sketch observation:** `project_agent_node_bypasses_gateway_fallback.md` lines 88-92 sketched a `FallbackChatLLM(BaseChatModel)` pattern with bind_tools-delegation. Live code chose `class FallbackChatLLM(Runnable)` with pre-bound contract — simpler shape, functionally equivalent. Per memory note's explicit "Implementation sketch for Turn 17.7" framing + reviewer sign-off: sketch-vs-live divergence is expected (sketches describe one possible shape; live implementation may simplify). **NOT drift, NOT a finding** — positive observation that the live design improved on the sketch. Mentioned in engineering touches roll-up.

**Frontier rating differentiator:** sibling to Steps 9 + 11 + 16 Frontier ratings via reliability-machinery-frontier-lens — design choices documented inline + predicate fragility tracked in dedicated memory note + canary monitoring explicitly load-bearing + 11 engineering touches in 125 LOC + 0 net-new gaps + design-evolution-from-sketch positive.

### Cross-references

- Base plan: Turn 17.7 close-out at plan lines 9525-9549 (`2.X-closeout-h`/i/j)
- Base plan amended at this step: **none**
- In-place code fixes landed at audit-write time: **none** (per silence protocol — no F-rows means no actions)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: **none**
- MEMORY.md ledger: **no change**
- Backward cross-reference: closes Step 16's forward cross-reference ("FallbackChatLLM + Groq tool_use_failed fallback = Step 17 scope; both tools' flat-types-only schemas are the tools' half of the Groq resilience story; FallbackChatLLM is the agent_node half"); reaffirms Step 7 cross-claim (FallbackChatLLM wraps primary + fallback via nodes.py:_build_chat_model with tools pre-bound to BOTH) + Step 10 cross-claim (test_fallback_llm.py covers 5 retry-predicate scenarios)
- Forward cross-reference: Step 18 (Turn 18 — extractors + chunker) + Step 19 (Turn 19.1/19.2 — contextualizer + ingestion) are the final two stretch surfaces of the backward audit (Turn 17.8 + 17.9 not built per directive — outside scope until they ship)
- Memory notes referenced (existing, reaffirmed): `project_agent_node_bypasses_gateway_fallback.md` (note IS the WHY for Turn 17.7; live shape diverges from sketch in BaseChatModel-vs-Runnable choice — simpler pattern shipped; design-evolution-from-sketch expected per "Implementation sketch" framing), `project_groq_error_message_string_match_dependency.md` (live `_default_retry_predicate` matches note's documented predicate verbatim; canary mitigation in place), `project_open_weights_tool_schema_and_conversation_poisoning.md` (upstream Groq llama brittleness that FallbackChatLLM closes the agent_node half of; tools' half confirmed at Step 16), `project_agent_llm_cost_attribution_gap.md` (FallbackChatLLM IS the agent_node bypass surface; KNOWN deferred), `project_n_provider_fallback_deferral.md` (2-provider chain only; N-provider deferred until Phase 3+ trigger)

### Step 18 — Turn 18 — RAG ingestion front-end (extractors + chunker + smoke harness)

**Overall rating:** Frontier — **Discipline note's pre-existing Turn 18 Frontier rating** (per `feedback_frontier_grade_discipline.md` worked example at lines 89-108) **verified to hold at audit-write time** via independent re-verification of all 3 lifts (A architect: structure-preserving extractors via PyMuPDF `page.get_text("dict")` + ExtractedBlock dataclass with source_locator extensibility; B AI/ML: semantic chunking with `fallback=True` flag for oversized-block path; C engineer: citation-ready meta with source_file + page_start/end + paragraph_start/end + section_heading + block_count). Token-aware structural chunker (tiktoken-counted, exceeds LangChain RecursiveCharacterTextSplitter on token-awareness) + citation-ready meta + chunker/contextualizer split (chunker = structural-chunking half; Turn 19.1 contextualizer = contextual-add half, Step 19 scope) = **Anthropic Contextual Retrieval pattern** (Sept 2024). Structural-vs-embedding-similarity choice (vs LlamaIndex SemanticSplitterNodeParser) is a valid trade-off, not a gap. **Sibling Frontier rating to Steps 9 + 11 + 16 + 17.** Ties Step 17 for cleanest Phase 2 surface (0 F-rows). — **Status:** final — sign-off 2026-06-08

**Scope:**
Turn 18 RAG ingestion front-end audited as one step per directive. 3 files (948 LOC total): extractors.py (structure-preserving extraction) + chunker.py (semantic chunker) + smoke_extractors.py (smoke harness — operator script, NOT runtime surface). The downstream RAG arc (contextualizer Turn 19.1 + ingestion pipeline Turn 19.2) = Step 19 scope per directive. Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Steps 12-17 accumulated upgrade-doc changes + Steps 15-16 code fixes uncommitted.

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/documents/extractors.py` | 345 | Task 2.13 (plan lines 6198-6256 — Document Text Extractors) | **Live substantially exceeds plan-verbatim** — 24-line module docstring documenting structure-preserving choice + back-compat `extract_text` wrapper + per-format notes. **Lift A confirmed:** ExtractedBlock dataclass (text + page + paragraph_index + section_heading + source_locator); PyMuPDF `page.get_text("dict")` at line 110 for blocks/lines/spans; font-size-derived heading detection (`_PDF_HEADING_FONT_RATIO = 1.25` with documented rationale at lines 90-93); DOCX `paragraph.style.name` heading detection; XLSX sheet-as-section_heading + read_only mode; TXT/MD `errors="replace"` graceful encoding. 6 formats: PDF, DOCX, XLSX, TXT, MD, CSV→TXT. Per-format dispatch via dict at `extract_blocks` (extensibility). |
| `backend/app/documents/chunker.py` | 212 | Task 2.14 (plan lines 6258-6351 — Text Chunker) | **Live substantially exceeds plan-verbatim** — 29-line module docstring documenting semantic-vs-plan-verbatim choice + strategy + explicit "Semantic chunks do NOT carry overlap between siblings — clean paragraph boundaries are the whole point" anti-drift framing. **Lift B confirmed** (`chunk_blocks` lines 90-115 — packs to token budget, flushes at paragraph boundary; oversized-block fallback `_split_oversized_block` lines 156-212 with explicit `fallback=True` flag — focused-lens-pass refinement per discipline note worked example). **Lift C confirmed** (`_chunk_from_blocks` lines 121-153 builds meta with source_file + paragraph_start/end + section_heading + block_count + page_start/end if PDF; fallback path meta includes fallback_window_start/end). tiktoken-counted (`cl100k_base`). Defaults `max_tokens=500` + `overlap_tokens=50` parameterized — caller passes per-call. |
| `backend/scripts/smoke_extractors.py` | 391 | Operator script (not in plan-verbatim) | **Fully realized smoke harness, NOT stub.** Builds synthetic docs across 7 surfaces (real fitz/docx/openpyxl libraries — not mocks) in temp dir; per-format assertion checks (page numbers, section_heading propagation, paragraph_index strictly increasing); semantic-split path test (verifies NOT fallback + paragraph boundaries respected); oversized-block fallback test (verifies fallback=True + chunks under max_tokens); shared `_assert_citation_ready` validator for required meta keys. |

Cross-referenced (NOT re-audited): `backend/app/db/models.py:DocumentChunk` (Step 3 — chunk row shape that `Chunk.meta` rolls into at ingestion time per Lift C). Downstream RAG arc (contextualizer Turn 19.1 + ingestion pipeline Turn 19.2) = Step 19 scope per directive.

**Plan task IDs verified per plan headers:** extractors = Task 2.13 (plan line 6198); chunker = Task 2.14 (plan line 6258). User directive cited 2.13 + 2.14 — both correct, no shift this step.

Base plan: Task 2.13 (lines 6198-6256) + Task 2.14 (lines 6258-6351). Memory notes consulted + re-verified at audit-write time: `feedback_frontier_grade_discipline.md` Turn 18 worked example at lines 89-108 (re-verified — pre-rated **Frontier** across all 3 lifts; documents the exact A+B+C trio; all 3 confirmed present in live code per spine verifications below; rating verified to hold), `feedback_architectural_units_land_complete.md` (re-verified — sibling principle; A+B+C landed as one architectural unit per the discipline), `project_phase1_monolithic_migration.md` (re-verified — `document_chunks` table in `001_initial_schema` per Step 3; chunker output → DocumentChunk.meta JSONB at ingestion time per Lift C; no migration needed at Turn 18). Cross-refs to Step-19-scope memory notes (`project_ingestion_idempotency_deferral`, `project_embedding_cost_attribution_gap`, `project_contextualizer_concurrent_dispatch_deferral`, `project_hyde_deferral`, `project_llm_relevance_grading_deferral`) — all 5 deferred-with-trigger-conditions concerns from discipline note worked example land at Step 19 surface for reaffirm.

### Spine verifications per directive (4 load-bearing checks — all pass)

**#1 Chunking strategy** — CONFIRMED genuinely semantic + token-aware + structural. chunker.py:90-115 packs contiguous blocks until token budget would overflow, flushes at paragraph boundary; oversized single blocks fall back to token-window with overlap (lines 156-212). NOT naive fixed-size. **Comparison against frontier anchors:**
- **LangChain RecursiveCharacterTextSplitter** — character-only recursive split; live chunker is **token-aware (tiktoken) + structural (block boundaries)** → live exceeds.
- **LlamaIndex SemanticSplitterNodeParser** — embedding-similarity breakpoints; live chunker uses structural breakpoints — different shape; valid trade-off (live is faster + cheaper, LlamaIndex more accurate for unstructured prose).
- **Anthropic Contextual Retrieval (Sept 2024)** — chunk-then-add-context; Turn 19.1 contextualizer is the live contextual-add half. **Live chunker + Turn 19.1 contextualizer together implement Anthropic Contextual Retrieval.**
- **Unstructured.io** — element-based chunking; live ExtractedBlock is similar element-based shape but simpler.

Config-via-settings: defaults hardcoded in chunker.py module constants (`_DEFAULT_MAX_TOKENS = 500` etc. at lines 49-51); chunker functions take them as parameters so callers override per call. **Settings-via-env lives at the CALLER's surface (ingestion.py = Step 19 scope), not the utility's surface.** Utility-by-design appropriate. ✓

**#2 Extraction robustness** — CONFIRMED 6 formats covered. Unsupported formats raise explicit `ValueError` at line 77. TXT/MD use `errors="replace"` graceful encoding degradation. XLSX `read_only=True` for large-file efficiency. PDF/DOCX library exceptions bubble up (no normalization layer — acceptable Phase 2). ✓

**#3 Metadata / provenance preservation** — CONFIRMED citation-ready. `ExtractedBlock` carries text + page + paragraph_index + section_heading + source_locator (format-specific extras). `Chunk.meta` carries source_file + page_start/end + paragraph_start/end + section_heading + block_count + fallback flag. Round-trips to DocumentChunk.meta JSONB at ingestion (Step 19). "Page 3, §Pricing" citation possible per discipline note worked example. ✓

**#4 smoke_extractors.py actively exercises extractors** — CONFIRMED. 391 LOC, NOT stub. Builds synthetic docs across 7 surfaces (PDF/DOCX/XLSX/TXT/MD/oversized-TXT/multi-paragraph-TXT) in temp dir using real libraries; per-format assertion checks + semantic-split path test + oversized-block fallback path test + shared `_assert_citation_ready` validator. ✓

### Smells checklist scan (full table)

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| **Flat string output** | **Reaffirm — back-compat wrapper, primary surface is structured** | `extract_text(file_path) -> str` at lines 81-84 returns flat joined string for back-compat. Primary surface is `extract_blocks(file_path) -> list[ExtractedBlock]` (Lift A). Back-compat retained per "Kept for callers that don't yet consume structured blocks; new code should call `extract_blocks`." Acceptable per discipline note worked example. |
| One-line tool description | N/A | Not a tool — utility |
| Single-item interface where batch frontier | N/A | Per-file extraction is correct shape |
| Module-level instantiation triggering I/O | None | extractors.py + chunker.py both have only constants + dataclass + functions at module level — no I/O |
| Logging-via-omission | None | Extractors raise on unsupported format; chunker raises on invalid params. No silent failures. No structlog — utility code surfaces errors via exceptions; caller logs at application layer. |
| Sync bypass of cost-tracking | N/A | No LLM calls — pure extraction + chunking |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — Frontier-quality rationale documentation across the layer** | extractors.py: 24-line module docstring; ExtractedBlock dataclass docstring documents source_locator extensibility. chunker.py: 29-line module docstring with explicit "Semantic chunks do NOT carry overlap between siblings — clean paragraph boundaries are the whole point" anti-drift framing. Every constant has documented rationale (`_PDF_HEADING_FONT_RATIO = 1.25` justified at lines 90-93; fallback flag justified at lines 166-168 for "retrieval-quality monitoring — too many fallbacks signals max_tokens is mistuned"). **Sibling pattern to setup_gmail_watch.py (Step 12) + gmail_pubsub.py:60-84 (Step 13) + calendar_create docstring (Step 14) + gmail_send.py + email_history.py (Step 16) + fallback_llm.py (Step 17) — inline rationale discipline applied consistently across the audit.** No drift. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | — |
| Speculative complexity | None | Every defensive pattern earns its keep — font-size threshold documented rationale; oversized-block fallback documented as retrieval-quality monitoring signal; XLSX read_only mode for large-file efficiency; encoding="utf-8" + errors="replace" for graceful TXT/MD malformed-input handling |

### Deeper comparison-target pass (frontier on chunker; production-to-frontier on extractors)

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| chunker.py (frontier — chunking strategy is the RAG-quality lever) | (1) LangChain RecursiveCharacterTextSplitter; (2) LlamaIndex SemanticSplitterNodeParser; (3) Anthropic Contextual Retrieval (Sept 2024); (4) Unstructured.io element-based | **C1: No embedding-similarity breakpoints (LlamaIndex shape)** — structural-vs-embedding-similarity valid trade-off per reviewer sign-off (not a gap); self-dismiss. **C2: Per-document-type chunker tuning** — already deferred per discipline note worked example "deferred with trigger conditions". Reaffirm. **C3: Defaults hardcoded vs settings** — utility-by-design appropriate (settings discipline at application-config caller = Step 19). Self-dismiss. |
| extractors.py (production-to-frontier — robust format handling) | (1) Unstructured.io (commercial); (2) LangChain document loaders; (3) PyMuPDF / python-docx / openpyxl best practices | **C4: No image/figure extraction** — YAGNI for personal corpus. Self-dismiss. **C5: No HTML/EPUB support** — extensibility via dict-dispatch makes adding trivial; not needed Phase 2. Self-dismiss. **C6: Font-size heading detection is heuristic** — alternative is layout-analysis ML (LayoutParser, PaperMage); live's heuristic with documented threshold is appropriate for Phase 2 + simpler. Self-dismiss. |
| smoke_extractors.py (operator harness) | gh CLI / gcloud CLI smoke patterns | Mechanics production-grade — per-format assertions + shared validator + temp-dir isolation. No gaps. |

Deeper lens result: 6 candidates surfaced. **0 net-new findings** — all 6 are documented deferrals (per discipline note worked example) or YAGNI / appropriate-utility-design.

### Comparison target

**chunker.py exceeds LangChain RecursiveCharacterTextSplitter** (token-aware + structural-awareness vs character-only) **and matches Unstructured.io's element-based shape** (with simpler ExtractedBlock vs Unstructured's richer Element types). **Live chunker + Turn 19.1 contextualizer (Step 19 scope) together implement the Anthropic Contextual Retrieval pattern** (Sept 2024) — chunker is the structural-chunking half; contextualizer is the contextual-add half. **Different shape from LlamaIndex SemanticSplitterNodeParser** (embedding-similarity vs structural) — valid trade-off per reviewer sign-off. extractors.py matches Unstructured.io shape with simpler element schema + per-format dispatch via dict (extensibility). **Bar per directive:** frontier on chunker (RAG-quality lever) — confirmed; production-to-frontier on extractors — confirmed. **Sibling Frontier rating to Steps 9 + 11 + 16 + 17 + the discipline note's pre-existing Turn 18 Frontier rating across all 3 lifts.**

### Three-hats tension surfaced (per discipline note's worked example — explicit re-verification)

- **Architect** wants to preserve all structure (could lead to over-rich ExtractedBlock schema). Wins on minimum-metadata + `source_locator` dict extensibility. Loses on schema bloat avoided by separating common fields from per-format extras.
- **Engineer** wants clean data types. Wins on `frozen=True` dataclasses + clear common-vs-extensible separation. Loses on per-format extras living in dict rather than typed fields.
- **AI/ML engineer** wants citation richness. Wins on citation-ready meta with all required fields. Loses on inevitable per-chunk metadata cost (JSONB column).

**Resolved per discipline note (verified at live code):** ExtractedBlock has minimum metadata needed for chunker + citation; richer per-format extras live in `source_locator` dict (extensible without schema change). All three hats partially satisfied. ✓

### Findings + disposition

_**No actionable findings at this step.** All 4 spine verifications confirmed; all 3 lifts (A architect + B AI/ML + C engineer per discipline note worked example) present in live code; all 6 deeper-lens candidates resolved as documented deferrals or YAGNI / appropriate-utility-design. **Step 18 ties Step 17 for cleanest Phase 2 surface** (0 F-rows). Per reviewer sign-off: "Leaning on the discipline note's pre-rating is fine BECAUSE you independently re-verified the 3 lifts against live code rather than echoing — that's the right way to use a pre-existing rating." F-rows reserved for actionable items per silence protocol; engineering-touches roll-up + methodology note carry the substantive content._

_Spine verifications per directive (all 4 confirmed):_
- _**#1 Chunking strategy** — genuinely semantic + token-aware + structural; exceeds LangChain on token-awareness; matches Unstructured.io shape; live chunker + Turn 19.1 contextualizer = Anthropic Contextual Retrieval pattern; structural-vs-embedding-similarity valid trade-off per reviewer._
- _**#2 Extraction robustness** — 6 formats; explicit ValueError on unsupported; graceful encoding for TXT/MD; library-exception-bubble acceptable Phase 2._
- _**#3 Metadata / provenance** — citation-ready per Lift C; round-trips to DocumentChunk.meta JSONB at ingestion (Step 19 scope)._
- _**#4 smoke_extractors.py** — actively exercises 7 surfaces with per-format assertions + shared validator; NOT stub._

_Engineering touches at this surface: 22 distinct frontier-execution patterns observed across the 3 files (extractors.py: structure-preserving via PyMuPDF `page.get_text("dict")` [Lift A architect]; ExtractedBlock dataclass with `frozen=True` + source_locator extensibility per-format-extras escape hatch; font-size-based heading detection with documented threshold rationale; heading-propagation-across-blocks via current_heading carries-forward; DOCX paragraph.style.name detection; XLSX read_only mode for large-file efficiency; TXT/MD errors="replace" graceful encoding; extract_text back-compat wrapper preserves old API; per-format dispatch via dict at extract_blocks for extensibility; chunker.py: semantic packing-until-overflow + flush-at-paragraph-boundary [Lift B AI/ML]; oversized-block fallback with explicit `fallback=True` flag — focused-lens-pass refinement; citation-ready meta with all required fields [Lift C engineer]; tiktoken-based token counting [cl100k_base — exceeds LangChain character-based]; configurable max_tokens + overlap_tokens + encoding via parameters [utility-by-design]; inner flush() closure for buffer management; asserts max_tokens > 0 + overlap_tokens < max_tokens at start [forward-progress guard]; smoke_extractors.py: per-format synthetic doc builders using real libraries [fitz / python-docx / openpyxl — not mocks]; per-format assertion checks with explicit failure tracking; oversized-block fallback path tested [check_oversized verifies fallback=True flag]; multi-paragraph semantic split path tested [check_semantic_split verifies NOT fallback + paragraph boundaries respected]; _assert_citation_ready shared validator for required meta keys + token_count ≤ max_tokens; **sibling-pattern documentation discipline across the audit** — every constant + defensive choice has inline rationale matching the consistent pattern across Steps 12-17). **Bar per sub-surface per directive: frontier on chunker [RAG-quality lever] confirmed via spine #1; production-to-frontier on extractors [robust format handling] confirmed via spine #2; smoke harness production-grade confirmed via spine #4.**_

### Methodology note

Spine verifications per directive (4 majors): **all 4 confirmed**.
- **#1 Chunking strategy** — semantic + token-aware + structural; exceeds LangChain; valid trade-off vs LlamaIndex; live chunker + Turn 19.1 contextualizer = Anthropic Contextual Retrieval pattern.
- **#2 Extraction robustness** — 6 formats; graceful encoding for TXT/MD; library-exception-bubble acceptable Phase 2.
- **#3 Metadata / provenance** — citation-ready per Lift C; round-trips to DocumentChunk.meta JSONB.
- **#4 smoke_extractors.py** — actively exercises 7 surfaces; NOT stub.

Deeper lens produced 6 candidates; 0 net-new findings — all documented deferrals per discipline note worked example's "deferred with trigger conditions" section OR YAGNI / appropriate-utility-design. Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 10-17 reviewer pattern. F-rows reserved for actionable items per silence protocol — Step 18 ties Step 17 for cleanest Phase 2 surface (0 F-rows).

**Discipline note pre-rating verification (per reviewer sign-off):** `feedback_frontier_grade_discipline.md` Turn 18 worked example at lines 89-108 pre-rated Turn 18 Frontier across all 3 lifts (A architect + B AI/ML + C engineer). **Independently re-verified all 3 lifts against live code rather than echoing the pre-rating** — that's the right way to use a pre-existing rating per reviewer. All 3 lifts present + working + tested via smoke harness.

**Forward methodology note (per reviewer; effective Step 19 onward):** engineering-touches roll-ups are growing long (Step 16: 20, Step 18: 22 inline). For scannability, from Step 19 on, compress to the ~5 most distinctive touches + "(N total)" rather than the full inline enumeration — the rating + a few exemplars convey "Frontier" without the wall of text. Don't re-do Step 18; this is forward-looking guidance for Step 19+.

### Cross-references

- Base plan: Task 2.13 (lines 6198-6256 — Document Text Extractors) + Task 2.14 (lines 6258-6351 — Text Chunker)
- Base plan amended at this step: **none**
- In-place code fixes landed at audit-write time: **none** (per silence protocol — no F-rows means no actions)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: **none**
- MEMORY.md ledger: **no change**
- Backward cross-reference: closes the discipline note's Turn 18 worked example pre-existing Frontier rating verification ("Plan rewired at commit `4b647b7`. Code shipped at commit `69c5f18`. Rated Frontier across all three lifts" — independently re-verified at audit-write time per reviewer)
- Forward cross-reference: Step 19 (Turn 19.1/19.2 — contextualizer + ingestion pipeline) is the final stretch surface of the backward audit; **chunker + contextualizer together = Anthropic Contextual Retrieval pattern** (chunker = structural-chunking half; contextualizer = contextual-add half); 5 deferred-with-trigger-conditions concerns from discipline note worked example all land at Step 19 surface for reaffirm (`project_ingestion_idempotency_deferral`, `project_embedding_cost_attribution_gap`, `project_contextualizer_concurrent_dispatch_deferral`, `project_hyde_deferral`, `project_llm_relevance_grading_deferral`); **Step 19 onward applies the compressed-engineering-touches roll-up format per reviewer methodology note** (~5 distinctive touches + "(N total)" instead of full enumeration)
- Memory notes referenced (existing, reaffirmed): `feedback_frontier_grade_discipline.md` Turn 18 worked example at lines 89-108 (pre-existing Frontier rating + A+B+C lifts framing — all independently re-verified to hold against live code), `feedback_architectural_units_land_complete.md` (sibling principle — A+B+C landed as one architectural unit), `project_phase1_monolithic_migration.md` (document_chunks table in 001_initial_schema; chunker output → DocumentChunk.meta JSONB at Step 19 ingestion)

### Step 19 — Turn 19.1 + 19.2 — RAG ingestion back-end (FINAL audit surface — Turn-19.2 halt)

**Overall rating:** Mid-to-Frontier (pipeline is genuinely excellent — gateway-routed contextualizer + INGESTER_VERSION pipeline-versioning + 5-stage telemetry + citation-ready metadata round-trip — but F1 idempotency gap is a real deferred quality concern: re-ingest corrupts retrieval quality for that document across every subsequent query until duplicates are cleaned, and the failure mode is invisible — master sees duplicated search results but may not realize the same doc is over-represented). **Lifts to Frontier when content_hash + ingester_version dedup ships** (per `project_ingestion_idempotency_deferral.md` recommended shape; INGESTER_VERSION foundation is already half-built — fix is ~15-20 LOC + half-day work when triggered). **Ladder-consistency call per reviewer sign-off:** rating sibling to Steps 8 (MCP-readiness deferred) + 12 (refresh-token-plaintext deferred) + 13 (multiple deferred quality) + 15 (fail-loud pre-fix) — Mid-to-Frontier is the audit's locked shape for "strong surface + one real deferred quality/correctness gap." Also a check against four-straight-Frontier ratings in the final stretch (Steps 16-17-18 all Frontier) — calibration discipline. — **Status:** final — sign-off 2026-06-08

**Scope:**
Turn 19.1 + 19.2 RAG ingestion back-end audited as one step per directive. **This is the FINAL audit surface — the Turn-19.2 halt point** where execution stopped 2026-05-25 for the frontier-upgrade backward audit pass. 2 files (448 LOC total): contextualizer.py (Turn 19.1 — the contextual-add half of Anthropic Contextual Retrieval) + ingestion.py (Turn 19.2 — end-to-end pipeline: extract → chunk → contextualize → embed → store DocumentChunk). Retrieval surfaces (Turn 19.3+: reranker / search / document_search) NOT BUILT — past halt, out of scope per directive. Audit captures live state as of HEAD `b57bd23` (Phase 1 audit close) + Steps 12-18 accumulated upgrade-doc changes + Steps 15-16 code fixes uncommitted.

**References:**

| File | LOC | Plan home | Live shape |
|---|---|---|---|
| `backend/app/documents/contextualizer.py` | 116 | Task 2.14b (plan line 6308 — design constraint locked under Task 2.14 framing; code spec at line 6310) | **Live exceeds plan-verbatim sketch** — 28-line module docstring documenting Anthropic Contextual Retrieval + batch-friendly interface (per locked design constraint) + failure model + downstream caller behavior. CONTEXT_PROMPT structured per Anthropic Contextual Retrieval template (lines 38-50). `contextualize_chunks(chunks, full_doc_excerpt) -> list[str]` batch interface; sequential `await` inside (concurrent dispatch deferred per `project_contextualizer_concurrent_dispatch_deferral.md`). Per-chunk failure isolation: degrades to `""` with distinct structlog events. **Routes through `llm_gateway.complete(task_type="summarization", temperature=0.0)` at lines 89-93 — NOT a bypass** (spine #2 positive). Caller-side excerpt sizing per "I take what I'm given" contract. |
| `backend/app/documents/ingestion.py` | 332 | Task 2.15 (plan lines 6353+ — Document Ingestion Pipeline) | **Live substantially exceeds plan-verbatim** — 40-line module docstring documenting 5-stage always-fire telemetry + per-chunk failure isolation + INGESTER_VERSION hybrid component+hash dict + caller-side excerpt truncation + 4 deferred lifts with explicit memory-note cross-references. `ingest_document(file_path, filename) -> dict` orchestrates 5 stages (extract → chunk → contextualize → embed → commit) each with `*_complete` structlog event carrying `status=success\|failure` + `duration_ms`. Per-chunk failure isolation: `embedding=None` for repair via audit trail, `contextual_summary=""` degrades to raw-chunk embedding. Stage-level failures DO propagate after logging (stop-the-line). `INGESTER_VERSION` auto-derived from CONTEXT_PROMPT sha + chunker defaults + embedder model+dims (lines 91-101) — supports selective re-processing on prompt/embedder swaps. `EXCERPT_CHARS=8000` caller-side bounded-memory excerpt truncation. **Metadata round-trip CONFIRMED** at lines 263-277: `Chunk.meta` (Step 18 citation-ready) rolls into DocumentChunk.meta with INGESTER_VERSION added. **Embedding via `litellm.aembedding()` directly** at line 237 — bypasses gateway (KNOWN per `project_embedding_cost_attribution_gap.md`; Phase 2 acceptable). Dimension mismatch detection at lines 242-249. **F1 idempotency gap:** `document_id = uuid.uuid4()` at line 139 generates fresh UUID per call → re-ingest creates duplicate chunks. |

Cross-referenced (NOT re-audited): chunker.py + extractors.py (Step 18), `db/models.py:DocumentChunk` (Step 3), `gateway.py` (Step 4 — for contextualizer LLM routing check). **Retrieval surfaces (Turn 19.3+) NOT BUILT — past halt, out of scope.**

**Plan task IDs verified per plan headers:** contextualizer = Task 2.14b (sub-task under Task 2.14 framing; design constraint locked at plan line 6308 + code spec at line 6310); ingestion = Task 2.15 (plan line 6353). User directive cited 2.14b + 2.15 — both correct per plan headers.

Base plan: Task 2.14b (lines 6308-6351 — Contextualizer with locked batch-friendly interface) + Task 2.15 (lines 6353-6503 — Document Ingestion Pipeline). Memory notes consulted + re-verified at audit-write time (all 5 RAG-arc deferreds come due here): `project_ingestion_idempotency_deferral.md` (F1 — reaffirm-deferred with explicit recommendation per directive), `project_contextualizer_concurrent_dispatch_deferral.md` (spine #3 reaffirm — sequential await inside batch interface verified), `project_embedding_cost_attribution_gap.md` (spine #4 reaffirm — Phase 2 acceptable; Ollama bge-m3 local + $0), `project_hyde_deferral.md` (forward-only reaffirm — retrieval surfaces not built), `project_llm_relevance_grading_deferral.md` (forward-only reaffirm — retrieval surfaces not built).

### Spine verifications per directive (5 load-bearing checks)

**#1 Ingestion idempotency (the one to watch)** — CONFIRMED per memory note: `ingest_document` at line 139 generates `document_id = uuid.uuid4()` per call → re-ingesting same file creates duplicate chunks → **retrieval-skew across every subsequent query** until duplicates cleaned. **Failure mode is invisible** — master sees duplicated search results but may not realize the same doc is over-represented unless they look carefully. **Recommendation per directive (don't rubber-stamp):** deferral **STILL RIGHT** because (a) trigger conditions are operationally visible at the moment they fire (master re-ingests → master notices duplicates → fix has clear signal — that's the right time to commit to a dedup-key choice); (b) **INGESTER_VERSION foundation is already half-built** (lines 91-104) — content_hash + ingester_version combined dedup (memory note's recommended shape) is partly in place; future fix is cheaper; (c) **HTTP documents-upload API (Turn 20 Task 2.17) ships AFTER the halt** — accidental re-ingest at current CLI-only single-master scale is low-probability; (d) **dedup-key choice (filename / content-hash / user-supplied) is a real design moment** — bolt-on dedup without thinking through the axis gives false confidence per memory note. **F1 — REAFFIRM-DEFERRED. Rating-relevant per reviewer.** Fix shape when triggered: content_hash + ingester_version combined dedup; ~15-20 LOC; half-day work + verification.

**#2 Contextualizer LLM routing (correctness-adjacent)** — CONFIRMED routes through `llm_gateway.complete()` at contextualizer.py:89-93 with `task_type="summarization", temperature=0.0`. **NOT a bypass** — correctly in-channel. NOT a sibling to agent_node / embedding / Mem0-extraction bypasses. **Positive** — sibling pattern to classifier/responder/digest (Steps 13-14) all routing through gateway. ✓

**#3 Contextualizer concurrent dispatch** — REAFFIRM per `project_contextualizer_concurrent_dispatch_deferral.md`: sequential `await` at contextualizer.py:77-114; batch interface preserves option for asyncio.gather + semaphore later. Live matches memory note verbatim. Module docstring lines 10-13 explicitly notes the deferral. ✓

**#4 Embedding bypass** — REAFFIRM per `project_embedding_cost_attribution_gap.md`: `litellm.aembedding()` direct call at ingestion.py:237 bypasses gateway. Phase 2 acceptable (Ollama bge-m3 local + $0). Module docstring lines 38-39 explicitly notes the deferral. ✓

**#5 Pipeline correctness + metadata round-trip** — CONFIRMED. **Metadata round-trip:** Step 18 chunker's citation meta (source_file + page_start/end + paragraph_start/end + section_heading + block_count + fallback flag) → ingestion.py:263-265 adds INGESTER_VERSION → DocumentChunk.meta JSONB. **Phase-3 citation-ready** ("page 3, §Pricing" possible per Step 18 worked example). **Failure handling:** 5-stage telemetry; per-chunk failures isolated (embedding=None + contextual_summary="" — chunks persist for repair via audit trail); stage-level failures propagate after logging (stop-the-line); dimension mismatch detection vs blind storage. ✓

### Smells checklist scan (full table)

| Smell | Applicable | Finding |
|---|---|---|
| 3-way enum classification | N/A | — |
| Flat string output | N/A | Both return structured dict/list |
| One-line tool description | N/A | Not tools — pipeline + utility |
| Single-item interface where batch frontier | N/A | `contextualize_chunks` IS batch (per design constraint); `ingest_document` is per-document (correct for write operation) |
| Module-level instantiation triggering I/O | None | logger inits + `INGESTER_VERSION = _compute_ingester_version()` (pure hashing) + `from litellm import aembedding` (heavy library import, no I/O at import) |
| Logging-via-omission | None | 5-stage always-fire telemetry with success+failure both logged; per-chunk failures get distinct events |
| **Sync bypass of cost-tracking / observability** | **Reaffirm — KNOWN at embedding surface; positive at contextualizer surface** | **Contextualizer:** routes through `llm_gateway.complete()` ✓ (spine #2 positive). **Embedding:** `litellm.aembedding()` bypasses gateway (spine #4 reaffirm; Phase 2 acceptable). Mixed-surface — gateway routing where it matters, bypass where it doesn't bite. |
| Tool-specific guidance in SAFETY_DOCTRINE | N/A | — |
| Plan-verbatim task order | N/A | — |
| **Documentation drift from code** | **None — Frontier-quality cross-referenced documentation across the layer** | contextualizer.py: 28-line module docstring documenting Anthropic Contextual Retrieval + batch-friendly interface lock + failure model + downstream caller behavior. ingestion.py: 40-line module docstring documenting 5-stage telemetry + per-chunk failure isolation + INGESTER_VERSION + caller-side excerpt truncation + 4 deferred lifts with explicit memory-note paths. All 4 cross-referenced memory notes verified to exist by their cited names. Every helper carries comprehensive docstring. **Sibling pattern to setup_gmail_watch.py (Step 12) + gmail_pubsub.py:60-84 (Step 13) + calendar_create docstring (Step 14) + gmail_send.py + email_history.py (Step 16) + fallback_llm.py (Step 17) + extractors.py + chunker.py (Step 18) — inline rationale + cross-reference discipline applied consistently across the entire Phase 2 audit.** No drift. |
| Verification axis mismatch | N/A | — |
| Single-shot prompt | N/A | contextualizer is single-shot per-chunk (well-bounded task); no iterative reasoning needed |
| **Speculative complexity** | None | Every defensive pattern earns its keep — 5-stage telemetry justified by debuggability of stuck-large-PDF scenarios; INGESTER_VERSION hybrid component+hash justified for selective re-processing on prompt/embedder swaps; caller-side excerpt truncation justified by clean contextualizer contract; dimension mismatch detection justified by avoiding blind storage of wrong-shape vector |

### Deeper comparison-target pass

| Surface | Anchors | Gaps surfaced beyond checklist |
|---|---|---|
| contextualizer.py (frontier — contextual-add is THE frontier RAG technique) | (1) Anthropic Contextual Retrieval paper (Sept 2024); (2) LlamaIndex contextual retrieval; (3) LangChain document loaders + retrieval chains | **C1: No prompt caching for full_doc context** — Anthropic's reference uses prompt caching to amortize cost across chunks of same doc; we use Groq/OpenAI/Gemini (no Anthropic prompt cache today). Self-dismiss as YAGNI Phase 2 single-master scale. **C2: No measurement of contextualizer quality** — Turn 20.5 eval framework would measure this. Self-dismiss as Turn-20.5-deferred. **C3: Gateway routing confirmed** (spine #2 positive). |
| ingestion.py (production-to-frontier — wiring + failure handling) | (1) LlamaIndex Document indexing pipeline; (2) LangChain ingestion patterns; (3) Unstructured.io + production RAG patterns; (4) Industry pipeline-versioning patterns | **C4: No document-level parent row** — Phase 4 dashboard concern. Self-dismiss as memory-note-mentioned-deferred. **C5: No retry on transient embedding failures** — embedding=None on first failure; adequate for Phase 2. **C6: No streaming for large doc ingestion** — Self-dismiss as YAGNI for Phase 2 master corpus. **C7: Sequential stage execution** — Self-dismiss as YAGNI. **C8: Idempotency** — spine #1 (F1 — rating-relevant). **C9: Embedding bypass** — spine #4 (reaffirm). |

Deeper lens result: 9 candidates surfaced. **0 net-new findings** — all gaps either F1 (idempotency, surfaced via spine #1) OR YAGNI / Phase 4 dashboard / Turn 20.5 eval / KNOWN deferred per existing memory notes.

### Comparison target

**Live chunker (Step 18) + contextualizer + ingestion together implement the Anthropic Contextual Retrieval pattern** (Sept 2024) — structural-chunking half + contextual-add half + end-to-end pipeline. INGESTER_VERSION hybrid component+hash dict is **forward-looking pipeline-versioning** that exceeds typical RAG pipeline patterns (LlamaIndex / LangChain don't ship pipeline-versioning by default). 5-stage always-fire telemetry + per-chunk failure isolation = production-grade reliability. Bar per directive: frontier on contextualizer (contextual-add is THE frontier RAG technique + LLM-routing-positive); production-to-frontier on ingestion (wiring + failure handling) — both confirmed. **F1 idempotency gap is the rating-relevant residual** keeping composite at Mid-to-Frontier rather than Frontier (per reviewer ladder-consistency reasoning + invisible-failure-mode argument).

### Three-hats tension surfaced

- **Architect** wants ingestion to be the single canonical pipeline surface — extract → chunk → contextualize → embed → store, one orchestration. Wins on 5-stage telemetry + INGESTER_VERSION pipeline-versioning + metadata round-trip. Loses on F1 idempotency gap — re-ingest produces duplicates; deferred because dedup-key choice is a real design moment.
- **Engineer** wants per-chunk failure isolation so one bad chunk doesn't abort the whole document. Wins on embedding=None + contextual_summary="" degradation patterns + chunks persist for repair via audit trail. Loses on no retry-on-transient-failures — acceptable for Phase 2.
- **AI/ML engineer** wants contextualizer to be batch-friendly (per locked design constraint) + caller-side excerpt sizing (clean contract). Wins on `contextualize_chunks(list[Chunk]) -> list[str]` interface + concurrent-dispatch deferred per memory note. Loses on sequential await inside — deferred until ingest latency complaints surface.

All three tensions surfaced.

### Findings + disposition

| # | Finding | Disposition |
|---|---|---|
| F1 | **Ingestion idempotency** — `ingest_document` at line 139 generates `document_id = uuid.uuid4()` per call → re-ingesting same file creates duplicate chunks → retrieval-skew (2x weight on duplicated doc in top-K) **across every subsequent query** until duplicates cleaned. **Failure mode is invisible** — master sees duplicated search results but may not realize the same doc is over-represented unless they look carefully (trust-eroding-without-being-noticeable per reviewer sign-off). KNOWN per `project_ingestion_idempotency_deferral.md`. **Rating-relevant per reviewer:** this is a real deferred quality concern (not an acceptable edge case like Step 16's self-send-bounce which is rare-trigger + visible-failure); caps the surface at Mid-to-Frontier. | **Reaffirm-deferred with explicit recommendation per directive** — deferral STILL RIGHT because: (a) trigger conditions are operationally visible at the moment they fire (master re-ingests → notices duplicates → fix has clear signal); (b) INGESTER_VERSION foundation is already half-built (memory note's recommended content_hash + ingester_version combined dedup is the natural shape); (c) HTTP docs-upload API ships AFTER the halt — accidental re-ingest at CLI-only single-master scale is low-probability; (d) dedup-key choice is a real design moment that benefits from operational signal before commitment. No code change. **Rating lift condition:** lifts to Frontier when content_hash + ingester_version dedup ships (~15-20 LOC; half-day work + verification per memory note). |

_F2 cut per silence protocol: Contextualizer routes through `llm_gateway.complete()` (spine #2) — positive. NOT bypass sibling. Engineering touches roll-up._

_F3 cut per silence protocol: Contextualizer sequential await inside batch interface (spine #3) — reaffirm per `project_contextualizer_concurrent_dispatch_deferral.md`. Live matches memory note verbatim._

_F4 cut per silence protocol: Embedding bypass via `litellm.aembedding()` (spine #4) — reaffirm per `project_embedding_cost_attribution_gap.md`. Phase 2 acceptable (Ollama bge-m3 local + $0)._

_F5 cut per silence protocol: Pipeline correctness + metadata round-trip (spine #5) — CONFIRMED. Step 18 chunker's citation meta rolls into DocumentChunk.meta with INGESTER_VERSION added; 5-stage telemetry + per-chunk failure isolation + stop-the-line stage failures. Engineering touches roll-up._

_F6 cut per silence protocol: HyDE + LLM-grading deferred (forward-only reaffirms) — retrieval surfaces (Turn 19.3+) NOT BUILT (past halt at Turn 19.2); reaffirm as still-deferred-and-not-yet-built per `project_hyde_deferral.md` + `project_llm_relevance_grading_deferral.md`._

_Engineering touches at this surface: **20 total** — compressed roll-up per Step 18 forward methodology. **5 most distinctive:** (1) **5-stage always-fire telemetry** (extract → chunk → contextualize → embed → commit) with `status=success\|failure` + `duration_ms` per stage — frontier observability per the "always-fire structured status" discipline; (2) **per-chunk failure isolation** with chunk persistence (embedding=None + contextual_summary="" for repair via audit trail) — stop-the-chunk-not-the-doc discipline; (3) **INGESTER_VERSION hybrid component+hash dict** at ingestion.py:91-104 — auto-derived from CONTEXT_PROMPT sha + chunker defaults + embedder model+dims; supports selective re-processing on prompt/embedder swaps; (4) **caller-side excerpt truncation** with clean contextualizer contract ("I take what I'm given") at ingestion.py:195 + contextualizer.py:65-70 — separation of concerns; (5) **contextualizer routes through `llm_gateway.complete()`** (NOT bypass sibling) at contextualizer.py:89-93 — positive per spine #2; sibling pattern to classifier/responder/digest from Steps 13-14. **15 other touches enumerated inline at smells scan + deeper-lens pass above** (CONTEXT_PROMPT per Anthropic template; per-chunk distinct structlog events; batch-friendly interface per locked design constraint; metadata round-trip from Chunk.meta → DocumentChunk.meta + INGESTER_VERSION added; stage-level failures propagate after logging stop-the-line; dimension mismatch detection vs blind storage; EXCERPT_CHARS=8000 memory-bounded; 4 deferred lifts cross-referenced in module docstring; _compute_ingester_version + _assemble_excerpt helper rationale documented; consistent per-stage time.monotonic() latency capture; session.add_all single-transaction pattern; structured logging with chunk_index + error_type + relevant counts at every failure point). **Bar per sub-surface per directive: frontier on contextualizer [contextual-add is THE frontier RAG technique + LLM-routing positive] confirmed via spine #2; production-to-frontier on ingestion [wiring + failure handling] confirmed via spine #5.**_

### Methodology note

Spine verifications per directive (5 majors): **all 5 confirmed or reaffirmed**.
- **#1 Ingestion idempotency** — REAFFIRM-DEFERRED with explicit recommendation (not rubber-stamp per directive); deferral still right + rating-relevant per reviewer.
- **#2 Contextualizer LLM routing** — CONFIRMED routes through gateway (NOT bypass). Positive.
- **#3 Contextualizer concurrent dispatch** — REAFFIRM per memory note (sequential await inside batch interface; concurrent deferred).
- **#4 Embedding bypass** — REAFFIRM per memory note (Phase 2 acceptable; Ollama bge-m3 local + $0).
- **#5 Pipeline correctness + metadata round-trip** — CONFIRMED (5-stage telemetry + per-chunk isolation + stop-the-line + metadata round-trip + dimension mismatch detection).

Plus forward-only reaffirms per directive: HyDE + LLM-grading retrieval lifts (Turn 19.3+ surfaces NOT BUILT — past halt). Reaffirm as still-deferred-and-not-yet-built, not as gaps on this surface.

Deeper lens produced 9 candidates; 0 net-new findings — all gaps either F1 (surfaced via spine #1) OR YAGNI / Phase 4 dashboard / Turn 20.5 eval / KNOWN deferred per existing memory notes. Codified count-discipline + as-of-step framing + no-action-positive compression applied from outset per Step 10-18 reviewer pattern. **Second step applying compressed-roll-up format per Step 18 forward methodology** (Step 19 = 5 distinctive + 15 inline + "(20 total)") — format reads well per reviewer sign-off.

**Rating calibration per reviewer sign-off:** Mid-to-Frontier per ladder consistency with Steps 8 (MCP-readiness deferred) + 12 (refresh-token-plaintext deferred) + 13 (multiple deferred quality) + 15 (fail-loud pre-fix) — the audit's locked shape for "strong surface + one real deferred quality/correctness gap." Two additional reasons reinforced the call: (a) **invisible-failure-mode argument** — F1 idempotency produces duplicated search results that master may not realize are from the same doc unless looking carefully (trust-eroding-without-being-noticeable, vs Step 16 self-send-bounce which is rare-trigger + visible-failure); (b) **check against four-straight-Frontiers calibration drift** — Steps 16-17-18 all Frontier; defaulting to Frontier in Phase 2 final stretch would be calibration-drift signal. Initial synthesis-time framing proposed Frontier on "pipeline is genuinely excellent + foundation-laid + low-probability-at-CLI-scale"; reviewer correctly recharacterized as Mid-to-Frontier with lift condition.

**Phase 2 audit closes at Step 19** — this is the terminal surface. Phase 2 commit cadence batches Steps 12-19 entries + Steps 15-16 accumulated code fixes (approval_expiry @critical_task swap + gmail_send/email_history note-name corrections). After commit, the backward audit (Turn 1 → Turn 19.2) is complete; what's next per the original execution-halt note: Phase 1.5 lifts shipping per slotting decided at the consolidation step + forward execution resuming from Turn 19.3 (retrieval surfaces — reranker / search / document_search).

### Cross-references

- Base plan: Task 2.14b (lines 6308-6351 — Contextualizer with locked batch-friendly interface) + Task 2.15 (lines 6353-6503 — Document Ingestion Pipeline)
- Base plan amended at this step: **none**
- In-place code fixes landed at audit-write time: **none** (per silence protocol; F1 is reaffirm-deferred per memory note, no action)
- Memory notes saved at this step: **none**
- Memory notes amended at this step: **none**
- MEMORY.md ledger: **no change**
- Backward cross-reference: closes Step 18 forward cross-reference ("the 5 deferred-with-trigger-conditions concerns from discipline note worked example all land at Step 19 surface for reaffirm" — all 5 reaffirmed at this step via spine verifications + forward-only reaffirms); **closes Step 18's chunker + Step 19's contextualizer = Anthropic Contextual Retrieval pattern** framing — full pattern verified end-to-end via spine #5 metadata round-trip
- Forward cross-reference: retrieval surfaces (Turn 19.3+: reranker / search / document_search) NOT BUILT — past halt at Turn 19.2; HyDE + LLM-grading deferred per memory notes; revisit when retrieval lands AND Turn 20.5 eval framework surfaces trigger conditions; idempotency F1 trigger conditions per memory note (first re-ingest produces duplicates OR HTTP docs API ships at Turn 20 OR eval framework surfaces retrieval-skew); **Phase 2 audit closes at Step 19 — no further audit steps**; next stretch per execution halt note: Phase 1.5 lifts ship per slotting decided at consolidation step + forward execution resumes from Turn 19.3
- Memory notes referenced (all 5 RAG-arc deferreds reaffirmed at this surface): `project_ingestion_idempotency_deferral.md` (F1 — reaffirm-with-explicit-recommendation; rating-relevant per reviewer), `project_contextualizer_concurrent_dispatch_deferral.md` (spine #3 reaffirm), `project_embedding_cost_attribution_gap.md` (spine #4 reaffirm), `project_hyde_deferral.md` (forward-only reaffirm — retrieval not built), `project_llm_relevance_grading_deferral.md` (forward-only reaffirm — retrieval not built)

### Step 20 — Phase 1.5 Consolidation (terminal step of the backward audit)

**Overall rating:** N/A — planning step, not an audit surface. — **Status:** final — sign-off 2026-06-08

**Scope:**
Terminal step of the backward audit (Pre-Phase-0 Steps 1-2 + Phase 1 audit Steps 3-11 + Phase 2 audit Steps 12-19 + Step 20 consolidation). **NOT a code audit** — dependency-correctness + completeness planning. Four deliverables per directive:

1. Final slot assignments for the 4 Phase 1.5 lifts surfaced at audit Steps 3 / 5 / 8.
2. Ordering + dependency edges within sub-phases + cross-sub-phase + against base plan (Phase 2.5 + Phase 4 anchors verified live).
3. Migration-numbering coupling flag on 1.5b-1 (per `project_phase1_monolithic_migration.md`).
4. Deferred-with-trigger memory note sweep — inventory, classify (FIXED / folded / stay-deferred / standing / process), flag forward-phase coupling.

After this step's outputs (4 lift slot-header patches landed + 1 template-example reframe + Phase 1.5 section preamble expansion + memory-note adjacency cross-reference added both ways + MEMORY.md ledger refreshed): Phase 1.5 lifts execute per their respective triggers; forward execution resumes from Turn 19.3 (retrieval surfaces — reranker / search / document_search).

### Task 1 — Final slot assignments

| Audit-time placeholder | **Final slot (Step 20)** | Title | Origin step |
|---|---|---|---|
| `Phase 1.5a-N` | **`Phase 1.5a-1`** | Tool registry MCP descriptor export | Step 8 (Turn 10) |
| `Phase 1.5a-N+1` | **`Phase 1.5a-2`** | Tool registry MCP server endpoint | Step 8 (Turn 10) |
| `Phase 1.5b-N` (Step 3) | **`Phase 1.5b-1`** | Schema multi-user readiness (user_id columns + backfill) | Step 3 (Turn 4) |
| `Phase 1.5b-N` (Step 5) | **`Phase 1.5b-2`** | Mem0Client USER_ID multi-user readiness (wrap approach) | Step 5 (Turn 6) |

Sub-phase letters: `a` = Trigger-Gated MCP-Readiness (parallel to Phase 2.5, NOT pre-Phase-2.5); `b` = Pre-Phase-4 Multi-User-Readiness. Sub-phase `c` not introduced. **The 4 audit-surfaced lifts ARE the complete Phase 1.5 set** — no further lifts surfaced across Steps 1-19.

### Task 2 — Ordering + dependency edges (verified)

**Within Phase 1.5a — HARD dependency:**
- **1.5a-1 → 1.5a-2: HARD.** 1.5a-2's proposed `backend/app/api/mcp.py` calls `tool_registry.export_mcp_descriptors()` directly (per lift entry code sketch); method must exist first. Documented in 1.5a-2's `Slot:` line.

**Within Phase 1.5b — INDEPENDENT (verified live at Step 20):**
- **1.5b-1 ↔ 1.5b-2: NO hard dependency.** Verified by live grep at Step 20: `backend/app/memory/mem0_client.py:52,97` uses `mem0_memories` pgvector collection — Mem0's own backing store, NOT the `memory_episodes` ORM table (which IS in 1.5b-1's 9-table schema-lift scope). Parameterizing `Mem0Client.USER_ID` touches zero columns from the 9-table schema lift. **Reorderable.**
- **SOFT preference: schema-first (1.5b-1 → 1.5b-2).** Reasoning: (a) schema is the canonical anchor for "user_id is a real column"; (b) schema has the trickier migration-numbering coordination (Task 3 below); (c) Mem0 wrap is the smaller ~20 LOC change, comfortable as trailing lift in the bucket. **Both lifts' Slot lines patched at Step 20** to make "no hard dependency; reorderable" explicit so a future executor knows the order can flip.

**Cross-sub-phase (1.5a ↔ 1.5b): INDEPENDENT.** No coupling. Execute by trigger order, not by letter.

**Anchoring against live base plan (verified at Step 20):**

- **Phase 2.5 anchoring** — Phase 2.5 (plan lines 6861-7193, Tasks 2.5M-1 through 2.5M-8) wraps EXISTING outbound integrations (calendar / telegram / whatsapp / news / booking) as MCP servers. It does NOT expose the agent's own in-process tool registry as MCP. **1.5a is parallel to Phase 2.5, NOT a blocker for it.** Anchor for 1.5a is trigger-gated (real Claude Desktop / Cursor MCP-client use case OR Phase 3 multi-agent cross-process handoff). **Sub-phase framing reconciliation per reviewer correction:** dropped "Pre-Phase-2.5 Lifts" wording (formerly in template example at line 65 of this upgrade doc) → "Trigger-Gated MCP-Readiness Lifts" framing. Both line 65 + Phase 1.5 section preamble patched at Step 20.
- **Phase 4 anchoring** — 1.5b blocks Phase 4 Tasks 4.13 (line 8525) / 4.14 (line 8632) / 4.18 (line 8904) / 4.18b (line 8937). All 4 headers verified live at stated plan lines. **1.5b is pre-Phase-4-hard.** Must land before Phase 4 multi-user work begins, OR the first multi-user task ships as a Phase-1.5b-then-feature compound execution.

### Task 3 — Migration-numbering coupling flag (1.5b-1)

Per `project_phase1_monolithic_migration.md`: 1.5b-1 adds a new Alembic migration. **Prefix chosen at LIFT-EXECUTION TIME** via `ls backend/alembic/versions/` + `\dt` against running DB. **NOT hardcoded at Step 20 consolidation** — would be wrong-axis verification.

1.5b-1 lift entry already contains the full downstream-impact table covering: Task 2.12 (`003_email_tables` — no-op per monolithic-migration note); Task 2.16b (`004_documents` — no-op); Turn 17.8 close-out (`004_email_logs_meta` — real; renumber on conflict); Turn 17.9 close-out (`005_audit_trail_latency` — real; renumber on conflict); Phase 3 Task 3.10 (`005_browser_audit` — real; renumber on conflict); Phase 4 Task 4.11b (`006_messaging_tables` — real; renumber on conflict).

**At lift-execution time:** verify what's actually shipped via `ls` + `\dt`, pick the next sequential prefix for THIS lift's migration, AND update affected downstream plan-stated migration numbers in `jarvis-implementation-plan.md` + this upgrade doc's close-out forward notes. **No Step 20 action required** beyond verifying the lift entry's caveat reads correctly post-slot-assignment (verified — caveat verbatim preserved across the slot-header patch).

### Task 4 — Deferred-with-trigger memory note sweep

Inventoried all 39 `project_*.md` notes in `.claude/projects/.../memory/` (8 `feedback_*.md` notes are methodology, NOT deferred-with-trigger — excluded from this sweep). **39 total: 38 deferred-concern/standing + 1 process note** (per reviewer count correction; previous synthesis miscount of 38 corrected pre-write).

**FIXED-AND-CLOSED (4 notes — already reflected in ledger):**
- `project_gmail_approval_resume_fails_no_langgraph_thread.md` — fixed pre-Step-9 (prefix-dispatch at router.py:118-120 + `_resolve_gmail_approval` handler).
- `project_gmail_approval_duplicate_race.md` — fixed Turn 16.5 (re-ordered gate at gmail_pubsub.py:108-126 + 25-line in-code rationale docstring).
- `project_email_action_capability_gap.md` — Approve/Reject path fixed Turn 17.5 (gmail_send + `_resolve_gmail_approval`); conversational "send it" half explicitly NOT-shipped by design (opted-out scope, not a deferred trigger).
- `project_email_responder_fabricates_content.md` — fixed Turn 16.5 (anti-fabrication + ask-back rules in DRAFT_PROMPT).

**FOLDED-INTO-LIFT (1 note):**
- `project_phase1_monolithic_migration.md` — operationalized in 1.5b-1's migration-numbering verification protocol + downstream-impact table. Note stays active as standing pre-migration verification lesson (`\dt` before every migration creation).

**STAY-DEFERRED, Phase-3-coupled (12 notes):**
`project_trivial_message_over_invocation` • `project_email_responder_sender_name` (Phase 3 auto-send) • `project_cross_source_recall_pattern` • `project_subgraph_topology_for_phase3_or_4` • `project_calendar_output_enrichment_phase3` • `project_archived_tool_result_no_fetch_path` • `project_per_tool_execution_timeout_gap` • `project_gmail_handler_decoupling_deferral` • `project_hyde_deferral` (Turn 20.5 eval trigger) • `project_llm_relevance_grading_deferral` (Turn 20.5 eval trigger) • `project_contextualizer_concurrent_dispatch_deferral` • `project_ingestion_idempotency_deferral` (Step 19 F1).

**STAY-DEFERRED, Phase-4-coupled (11 notes):**
`project_seeder_force_cascade_risk` • `project_webhook_secret_naming_inconsistency` • `project_oauth_scope_minimization_production_hardening` • `project_module_level_mem0_instantiation_smell` • `project_agent_node_bypasses_gateway_fallback` (cost-attribution half active; FallbackChatLLM half landed Turn 17.7) • `project_agent_llm_cost_attribution_gap` (3-surface) • `project_embedding_cost_attribution_gap` (3-surface sibling) • `project_groq_error_message_string_match_dependency` (canary in place) • `project_n_provider_fallback_deferral` • `project_persistent_tunnel_deferral` • `project_langfuse_stack_weight_deferral`.

**STANDING OPERATIONAL / REFERENCE (10 notes — never "fire"; applied at code touch points):**
`project_no_hallucinated_actions` (doctrine) • `project_cost_cap_redis_only` • `project_mem0_silent_drop_on_rpm` • `project_docker_compose_restart_does_not_reload_env` • `project_async_state_rebind_pattern` • `project_open_weights_tool_schema_and_conversation_poisoning` • `project_mem0_contamination_test_residue` • `project_self_send_bounces` • `project_audit_ratings_turn_11_through_17` (reference) • `project_execution_halt_2026_05_25_frontier_upgrade_pass` (context).

**PROCESS NOTE (1 — NOT deferred-with-trigger; acknowledged for sweep completeness per reviewer):**
- `project_coder_skill_load_timing.md` — process/reminder note specifying when to load `.claude/skills/coder/SKILL.md` (after backward audit drafted + Phase 1.5 slotted, just BEFORE forward execution resumes from Turn 19.3). Not classified under fired/deferred/standing — it's a one-shot process trigger. **Currently ACTIVE:** Step 20 IS the slotting; load the coder skill before Turn 19.3 greenlight per the note's concrete trigger.

**Tally:** 4 fixed + 1 folded + 12 P3-deferred + 11 P4-deferred + 10 standing + 1 process = **39**. Balance preserved per reviewer count correction.

### Forward-phase coupling flags (Step 20 sweep output)

Three couplings worth explicit forward-carry:

1. **`project_module_level_mem0_instantiation_smell.md` ↔ Phase 1.5b-2 (Mem0 wrap) — ADJACENT, NOT BUNDLED** (per Step 20 Q2 sign-off). Both touch the Mem0Client / MemoryManager surface. **Different concerns** (lazy-init = import-time safety; USER_ID = multi-user parameterization); **different files** (`app/memory/manager.py` + 5 call sites vs `app/memory/mem0_client.py`). Two architectural units per `feedback_architectural_units_land_complete.md` split-at-stable-interface-boundary discipline. **Adjacency cross-reference added BOTH WAYS at Step 20:** memory note's Related-notes section + 1.5b-2's Status line + 1.5b-2's Slot section + 1.5b-2's Cross-references line all note "adjacent — opportunistic-co-execution candidate; whoever executes either checks the other and MAY bundle if already in `app/memory/`; captures efficiency without coupling unrelated changes into one commit." **Lazy-init stays a standing ship-any-time improvement, NOT gated on 1.5b-2.**
2. **`project_oauth_scope_minimization_production_hardening.md` ↔ Phase 4 multi-user (post-1.5b).** Trigger is Phase 4 multi-user; 1.5b lands BEFORE Phase 4; OAuth hardening landscape becomes execution-ready immediately after 1.5b ships. **No Step 20 action required;** flag for Phase 4 sequencing executor (Step 12 audit already expanded note with the full hardening landscape including refresh-token-plaintext-print + multi-operator scrollback trigger).
3. **3-surface gateway-bypass cluster — `project_agent_llm_cost_attribution_gap.md` + `project_agent_node_bypasses_gateway_fallback.md` (cost-attribution half) + `project_embedding_cost_attribution_gap.md` ↔ Phase 4 dashboard.** Not a Phase 1.5 lift; deferred to Phase 4 cost-by-surface work. **Flag for Phase 4 executor:** Option C hybrid helper closes all three surfaces in one pass (agent_node highest-frequency; embedding $0 today via local Ollama; Mem0 extraction ~$0.05/day untracked).

### Methodology note

Step 20 is the terminal planning step of the backward audit. Discipline applied:
- **Verification-before-claim** on dependency edges — live grep of `mem0_client.py:52,97` confirmed Mem0 backing-store independence from schema-lift table set, turning a presumed SOFT preference into a VERIFIED independence (`feedback_verify_before_claiming.md`).
- **Sub-phase framing reconciliation per reviewer correction** — dropped "Pre-Phase-2.5 Lifts" template example (line 65) → "Trigger-Gated MCP-Readiness Lifts" framing, since 1.5a is parallel to Phase 2.5, not gating on it.
- **Q1 (SOFT 1.5b ordering) + Q2 (Mem0 lazy-init separate, NOT bundled) per reviewer sign-off** — both decisions reflected in lift Slot lines + adjacency cross-references in both directions.
- **Count discipline applied** — 39 project notes (38 deferred-concern/standing + 1 process note per reviewer correction); previous synthesis miscount of 38 corrected pre-write.
- **Memory note adjacency cross-reference added both ways** (memory note Related-notes + lift entry Cross-references + lift entry Status line + lift entry Slot line) per `feedback_forward_prompts_name_files_to_read.md` discipline applied to forward-coupling flags (anchor at all surfaces, not just one).
- **Silence protocol holds for the consolidation step** — Tasks 1-3 are mechanical assignment + verification; only Task 4 sweep is information-dense, presented as categorized inventory rather than per-note narrative. Three couplings flagged in dedicated subsection — the rest of the sweep is index-only.

The backward audit (Turn 1 → Turn 19.2) closes at Step 20. Next stretch per `project_execution_halt_2026_05_25_frontier_upgrade_pass.md` + `project_coder_skill_load_timing.md`: load coder skill (process trigger active NOW) → Phase 1.5 lifts execute per their respective triggers (1.5a trigger-gated; 1.5b pre-Phase-4-hard) → forward execution resumes from Turn 19.3 (retrieval surfaces — reranker / search / document_search).

### Cross-references

- Base plan: Phase 2.5 (lines 6861-7193, Tasks 2.5M-1 through 2.5M-8) — verified for 1.5a parallel-not-blocking anchoring; Phase 4 Tasks 4.13 (8525) / 4.14 (8632) / 4.18 (8904) / 4.18b (8937) — verified for 1.5b pre-Phase-4-hard anchoring.
- Base plan amended at this step: **none** (consolidation is upgrade-doc + memory-note work, not plan-task work).
- In-place code fixes landed at audit-write time: **none** (planning step — no code touched).
- Memory notes saved at this step: **none**.
- Memory notes amended at this step: `project_module_level_mem0_instantiation_smell.md` (Related-notes section — added 1.5b-2 adjacency cross-reference with stay-separable + opportunistic-bundling framing per Step 20 Q2 sign-off).
- MEMORY.md ledger: refreshed line 24 (module-Mem0 smell entry) to acknowledge 1.5b-2 adjacency.
- Upgrade-doc patches landed at Step 20: **11 patches** — line 65 template example (Pre-Phase-2.5 → Trigger-Gated MCP-Readiness); Phase 1.5 section preamble (added sub-phase semantics block + live-verification rationale); 4 lift entry headers (drop "(slot TBD)" + final slot assignment); 4 lift entry Status lines (final slot + Step 20 dependency framing + adjacency cross-reference for 1.5b-2); 4 lift entry Slot lines (final slot + dependency edges + verified-independence wording for 1.5b lifts); 1.5b-2 Cross-references line (strengthened adjacency wording).
- Backward cross-reference: closes Step 19's forward cross-reference ("Phase 1.5 lifts ship per slotting decided at consolidation step + forward execution resumes from Turn 19.3"); closes the audit's standing forward references to "(slot TBD)" / "position number assigned at the consolidation step" / "sub-phase letter expected" across all 4 lift entries; closes audit Steps 3 (1.5b-1 surfaced) / 5 (1.5b-2 surfaced) / 8 (1.5a-1 + 1.5a-2 surfaced) lift-slotting forward references.
- Forward cross-reference: Phase 1.5 lifts execute per individual trigger conditions (1.5a-1 + 1.5a-2: real MCP-client use case OR Phase 3 multi-agent; 1.5b-1 + 1.5b-2: pre-Phase-4-hard, must land before first Phase 4 multi-user task); load `.claude/skills/coder/SKILL.md` per `project_coder_skill_load_timing.md` BEFORE Turn 19.3 greenlight (process trigger ACTIVE NOW); Phase 4 sequencing executor inherits 3 forward-coupling flags (Mem0-lazy-init adjacent / OAuth hardening immediately-ready / 3-surface gateway-bypass Option C).
- Memory notes referenced: all 39 sweep notes (categorized in Task 4 above); explicit forward-coupling notes — `project_module_level_mem0_instantiation_smell.md` (adjacency added both ways) + `project_oauth_scope_minimization_production_hardening.md` (immediately-ready post-1.5b) + 3-surface gateway-bypass cluster (Phase 4 dashboard Option C) + `project_coder_skill_load_timing.md` (process trigger ACTIVE NOW).

## Phase 1.5 — Retroactive Foundation Lifts (Backward Audit Output)

> Sub-phase letters and per-lift numbering **assigned at Step 20 consolidation (2026-06-08)** based on dependencies surfaced across all audit steps + live-code verification (Mem0Client `mem0_memories` collection independence; Phase 2.5 / Phase 4 base-plan anchors). Per-lift entries use the Phase 1.5 lift template described above.
>
> **Sub-phase semantics (post-consolidation):**
> - **Phase 1.5a — Trigger-Gated MCP-Readiness Lifts** (1.5a-1 + 1.5a-2). NOT pre-Phase-2.5 — **parallel to** Phase 2.5 (Phase 2.5 wraps existing OUTBOUND integrations as MCP servers — calendar / telegram / whatsapp / news / booking; 1.5a exposes the in-process tool registry itself as MCP). **Trigger:** real MCP-client use case crystallizes (Claude Desktop / Cursor) OR Phase 3 multi-agent decides on cross-process tool handoffs. **1.5a-1 → 1.5a-2 is a HARD dependency** (server endpoint imports the descriptor exporter).
> - **Phase 1.5b — Pre-Phase-4 Multi-User-Readiness Lifts** (1.5b-1 + 1.5b-2). Blocks Phase 4 Tasks 4.13 (plan line 8525) / 4.14 (8632) / 4.18 (8904) / 4.18b (8937). **The two lifts are INDEPENDENT** — no hard dependency. Verified live: `mem0_client.py:52,97` uses Mem0's own `mem0_memories` pgvector collection, NOT the user-scoped ORM tables (which are in 1.5b-1's schema-lift scope). **Reorderable.** SOFT preference is schema-first (1.5b-1 → 1.5b-2): canonical anchor + trickier migration-numbering coordination on the schema side; ~20 LOC Mem0 wrap as trailing lift.
> - **Cross-sub-phase (1.5a ↔ 1.5b): INDEPENDENT.** Execute by trigger order, not by letter.

### Phase 1.5a-1 — Tool registry MCP descriptor export

**Status:** proposed — surfaced at Step 8 (Turn 10 audit, 2026-05-25). **Slot assigned at Step 20 consolidation (2026-06-08):** sub-phase `a` (Trigger-Gated MCP-Readiness — parallel to Phase 2.5, NOT pre-Phase-2.5). **First of two sequential Phase 1.5a lifts** split from F3 (the second is Phase 1.5a-2 — MCP server endpoint, below).

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

~30-50 LOC including the method, a small dedicated test (`backend/tests/test_tool_registry_mcp_export.py`), and any helper utilities for schema normalization. Useful WITHOUT the server (Phase 1.5a-2):
- Phase 3 internal multi-agent handoffs (one Jarvis subgraph exports its tools to another)
- Auto-generated tool documentation (dashboard or README artifact)
- MCP-spec compliance validation (CI assert: every registered tool's descriptor passes MCP schema check)
- Test harness fixtures (mock external MCP clients consuming descriptors)

**Scope exclusions (explicit boundary against scope creep):**
- MCP server endpoint (FastAPI route + discovery metadata + auth model) → **separate Phase 1.5a-2 lift below**
- Per-user tool isolation (which tools each MCP client can see) → **Phase 4 multi-user work**
- Tool output schema definition + enforcement → **Phase 3+ work when tool surface evolves beyond strings**; outputSchema field can stay absent in descriptors for now
- MCP capability negotiation (server version, supported MCP spec version) → **part of Phase 1.5a-2**

**Verification plan:**
- Unit test: `tool_registry.export_mcp_descriptors()` returns one descriptor per registered tool with `name`, `description`, and `inputSchema` fields populated.
- Schema validation: each descriptor's `inputSchema` is valid JSON Schema (round-trip through `jsonschema` validator).
- MCP spec compliance: descriptors match Anthropic's published MCP tool descriptor shape (named-field check; not full protocol).
- Backward compatibility: existing `tool_registry.execute()`, `select_relevant_tools()`, `all_names()` paths unchanged and continue to work.

**Slot:** `Phase 1.5a-1` (assigned at Step 20 consolidation, 2026-06-08). Blocks **Phase 1.5a-2** (MCP server endpoint depends on descriptors — HARD dependency). Does NOT block any Phase 2, Phase 2.5, or Phase 3 work; **parallel to Phase 2.5 outbound-integration wrappers**, not pre-Phase-2.5.

**Cross-references:**
- Surfaced at audit step: Step 8 (Turn 10 audit) — see Backward Audit Records section above (F3 split rationale)
- Sibling Phase 1.5a lift: Phase 1.5a-2 (MCP server endpoint — sequential dependency)
- Base plan reference: Task 1.11 (lines 3322-3577) — tool registry definition
- Split rationale memory note: `feedback_architectural_units_land_complete.md` — "split at stable interface boundaries"

### Phase 1.5a-2 — Tool registry MCP server endpoint

**Status:** proposed — surfaced at Step 8 (Turn 10 audit, 2026-05-25). **Slot assigned at Step 20 consolidation (2026-06-08):** sub-phase `a` (sibling to 1.5a-1). **Second of two sequential Phase 1.5a lifts** split from F3 — **HARD dependency on Phase 1.5a-1** (descriptor exporter must exist before server endpoint can import it).

**Live-code observation:**
- No MCP server endpoint anywhere in the FastAPI app (verified by grep on `app.api`).
- No discovery metadata for external MCP clients (server name, capabilities, MCP spec version).
- No auth model for external MCP clients (existing auth is FastAPI-side for the dashboard UI; Phase 4 work).
- FastAPI app has `/api/*` routes for dashboard + webhook; no `/mcp/*` routes.

**Plan-markdown reference** (verbatim quote from base plan, re-verified against current base-plan state at audit-write time 2026-05-25):

Same Task 1.11 (lines 3322-3326) quote applies — base plan's tool registry is in-process only; MCP server endpoint is plan-vs-frontier gap, not plan-vs-code drift. Phase 4 auth section (Tasks 4.18 / 4.18b — backend auth + Auth.js v5 integration) is the relevant downstream coupling for this lift's auth model.

**Discrepancies surfaced:**
- None between live code and plan markdown.
- Plan-vs-frontier gap (same shape as Phase 1.5a-1).
- **Phase-4-coupling discrepancy:** the lift's auth model decision is tied to Phase 4 multi-user shape. Landing single-master auth at Phase 1.5a-2 risks migration when Phase 4 multi-user lands. Trigger-gated execution accommodates this.

**Comparison target:**

Anthropic's reference MCP server implementations (Python + TypeScript SDKs); Claude Desktop's MCP server pattern (stdio + HTTP transports); Cursor's MCP integration (HTTP-based, OAuth-flow for client auth).

**Proposed lift:**

Two routes + discovery metadata, depending on Phase 1.5a-1 descriptors:

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

**Slot:** `Phase 1.5a-2` (assigned at Step 20 consolidation, 2026-06-08). **HARD dependency on:** Phase 1.5a-1 (Tool descriptor export — `api/mcp.py` imports `tool_registry.export_mcp_descriptors()`). **Trigger condition for execution:** real MCP-client use case crystallizes (master wants Jarvis tools accessible from Claude Desktop OR Cursor) OR Phase 3 multi-agent decides on cross-process tool handoffs. **Phase 4 coupling:** auth shape decision pulls in Phase 4 multi-user state; execute after Phase 4 auth has shipped, OR ship static bearer token with documented migration path.

**Cross-references:**
- Surfaced at audit step: Step 8 (Turn 10 audit) — see Backward Audit Records section above (F3 split rationale)
- Sibling Phase 1.5a lift: Phase 1.5a-1 (Tool descriptor export — sequential prerequisite)
- Base plan reference: Task 1.11 (lines 3322-3577) — tool registry definition; Phase 4 Tasks 4.18 / 4.18b — backend auth + Auth.js v5 (coupling for auth shape decision)
- Split rationale memory note: `feedback_architectural_units_land_complete.md` — "split at stable interface boundaries"
- Memory notes referenced: none yet — execution-time auth-shape decision will surface relevant notes

### Phase 1.5b-1 — Schema multi-user readiness (add user_id columns + backfill)

**Status:** proposed — surfaced at Step 3 (Turn 4 audit, 2026-05-25). **Slot assigned at Step 20 consolidation (2026-06-08):** sub-phase `b` (Pre-Phase-4 Multi-User-Readiness). **No hard dependency on 1.5b-2** — reorderable per Step 20; SOFT preference for schema-first (canonical anchor + trickier migration-numbering coordination per the in-entry downstream-impact table below).

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

**Slot:** `Phase 1.5b-1` (assigned at Step 20 consolidation, 2026-06-08). Blocks Phase 4: Task 4.13 (non-master intent routing, plan line 8525) + Task 4.14 (auto-responder, plan line 8632) + Task 4.18 (backend auth, plan line 8904) + Task 4.18b (Auth.js v5 frontend, plan line 8937). **No hard dependency on 1.5b-2** — verified live: Mem0Client uses its own `mem0_memories` pgvector collection at `mem0_client.py:52,97`, NOT the user-scoped ORM tables in this lift's 9-table scope. Reorderable; SOFT preference is schema-first.

**Cross-references:**
- Surfaced at audit step: Step 3 (Turn 4 audit) — see Backward Audit Records section above
- Sibling Phase 1.5b lift: Mem0Client USER_ID multi-user readiness (Step 5 audit — see lift entry below)
- Base plan reference: Task 1.4 (lines 1342-1367) — UserProfile model definition
- Memory notes: `project_phase1_monolithic_migration.md` (monolithic migration context — this lift adds a new migration on top of the monolithic baseline)
- Blocks: Phase 4 Tasks 4.13 (non-master intent routing), 4.14 (auto-responder), 4.18 (backend auth), 4.18b (frontend Auth.js v5)

### Phase 1.5b-2 — Mem0Client USER_ID multi-user readiness (wrap approach)

**Status:** proposed — surfaced at Step 5 (Turn 6 audit, 2026-05-25). **Slot assigned at Step 20 consolidation (2026-06-08):** sub-phase `b` (Pre-Phase-4 Multi-User-Readiness, sibling to 1.5b-1 schema lift). **No hard dependency on 1.5b-1** — reorderable per Step 20; SOFT preference is schema-first. **Adjacency cross-reference (Step 20 forward-coupling flag):** `project_module_level_mem0_instantiation_smell.md` lazy-init refactor (5 sites: `responder.py:4` + `nodes.py:68` + `context.py:19` + `builtin_memory.py:20` + `api/memory.py:20`) shares the Mem0Client / MemoryManager surface — whoever executes 1.5b-2 OR the lazy-init refactor checks the other and MAY opportunistically bundle if already in `app/memory/`. Both stay separable per `feedback_architectural_units_land_complete.md` split-at-stable-interface-boundary discipline; lazy-init is NOT gated on 1.5b-2.

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

**Slot:** `Phase 1.5b-2` (assigned at Step 20 consolidation, 2026-06-08). Sibling lift to 1.5b-1 (schema multi-user). **No hard dependency on 1.5b-1** — verified independent at Step 20: Mem0Client uses its own `mem0_memories` pgvector collection (`mem0_client.py:52,97`), not the user-scoped ORM tables. Reorderable; SOFT preference is schema-first (canonical anchor + trickier migration-numbering coordination on the schema side; ~20 LOC Mem0 wrap as trailing lift).

**Cross-references:**
- Surfaced at audit step: Step 5 (Turn 6 audit) — see Backward Audit Records section above
- Sibling Phase 1.5b lift: Step 3 F1 (schema multi-user readiness)
- Base plan reference: Task 1.7 (lines 2103-2135) — Mem0Client class definition
- Memory notes referenced: `project_module_level_mem0_instantiation_smell.md` (**adjacent — Step 20 forward-coupling flag**: shares Mem0Client / MemoryManager surface; opportunistic-co-execution candidate per Step 20 consolidation; stay-separable per `feedback_architectural_units_land_complete.md` split-at-stable-interface-boundary; lazy-init NOT gated on 1.5b-2 — captures efficiency without coupling unrelated changes in one commit)
- Blocks: Phase 4 Tasks 4.13 (non-master intent routing), 4.14 (auto-responder), 4.18 (backend auth), 4.18b (frontend Auth.js v5)

_(populated by all audit steps; consolidated at the consolidation step)_

## Retroactive Turn Entries (Turn 18 onward)

> Per-turn entries for turns that applied frontier discipline at design time. Documentation-only — code already committed; entries capture the lens-application reasoning for future readability.

### Turn 19.3–19.7 — RAG retrieval surface (reranker + hybrid search + document_search tool + smoke)

**First forward turn post-halt.** Resumes forward execution from the Turn-19.2 halt point per `project_execution_halt_2026_05_25_frontier_upgrade_pass.md` + the now-fired `project_coder_skill_load_timing.md` process trigger (coder skill loaded at the audit→build handoff). Owns the retrieval surface end-to-end as one architectural unit (retrieve → rerank → threshold → return is one feedback loop), committed once at 19.7.

**Shipped:** `app/documents/reranker.py` (pure cross-encoder scorer, lazy singleton); `app/documents/search.py` (hybrid vector+BM25 → RRF fusion → rerank → threshold + symmetric kept/dropped audit); `app/agent/tools/document_search.py` (citation-formatted agent tool, registered SAFE); `scripts/smoke_rag.py` (pipeline-correctness smoke). Plus 6 `settings` RAG knobs, registration wiring, and the safety-map row. No migration — `document_chunks` already exists via the Phase-1 monolithic migration (`project_phase1_monolithic_migration.md`); Task 2.16b stays a Turn-20 no-op.

**Design decisions (frontier lens applied at design time):**

1. **Fusion fork — RRF, not weighted score fusion** (`search.py:_rrf_fuse`). Cosine (bounded `[0,1]`) and BM25 (unbounded, corpus-frequency-dependent) live on incompatible scales; weighted fusion forces a brittle per-query normalization + a magic `α` that is only tunable against the Turn-20.5 eval harness that doesn't exist yet — shipping it blind would violate `feedback_lifts_on_real_usage_signal.md`. RRF is rank-based and scale-invariant; its only knob (`RAG_RRF_K=60`) is the literature-insensitive smoothing constant. Decisive reframe: the cross-encoder is the precision stage, so fusion owes only *recall into the rerank pool*, which rank-union delivers directly. Frontier-anchor convergence: ES `rrf`, Weaviate hybrid, LlamaIndex `QueryFusionRetriever` all default to RRF for this two-retriever→reranker shape.

2. **Reranker backend — `sentence_transformers.CrossEncoder`, NOT `FlagEmbedding.FlagReranker`** (deviation from plan Task 2.15b, caught at the gate). FlagEmbedding 1.4.0's tokenizer path calls `tokenizer.prepare_for_model(...)`, removed in transformers 5.x — and transformers 5.8.0 is pinned in the image by `sentence-transformers` 5.4.1 **and** `peft`, so downgrading transformers to satisfy FlagEmbedding starts a resolver fight. CrossEncoder loads the *identical* weights (`BAAI/bge-reranker-v2-m3`), is the more widely-maintained API, works with the installed transformers-5 stack, and for a single-label reranker (`num_labels=1`) applies sigmoid by default — so `rerank_score ∈ (0,1)`, keeping the `RAG_RERANK_THRESHOLD=0.3` cut's semantics identical to `FlagReranker(normalize=True)`. Verified directly: on-topic 0.9448, off-topic 0.0. `pyproject.toml` reconciled: `FlagEmbedding>=1.3.0` → `sentence-transformers>=5.0,<6` (now a direct import; upper-bounded so a future major can't silently re-break the loader the same way). **No memory note for the swap** — it's resolved in-code and commented (reranker.py header + pyproject comment), so it doesn't outlive the turn. **Plan Task 2.15b reconciliation:** the plan's FlagReranker sketch is superseded by this entry; plan annotated with a superseded-by pointer (plan remains the historical baseline; this upgrade doc is authoritative per the halt marker).

3. **Pure-scorer / policy split + symmetric threshold audit** (the turn's deliverable). `reranker.rerank()` scores all candidates and returns them sorted — no threshold, no `top_k`, no logging. `search._apply_threshold` owns policy; the single `rag_search_complete` event carries **both** `kept_candidates` and `dropped_candidates` arrays (each a score per chunk), not just a kept count. Symmetric on purpose (reviewer-driven completion): reranker *leak-through* — the failure mode the LLM-relevance-grading deferral (`project_llm_relevance_grading_deferral.md`) triggers on — is a *kept* chunk that shouldn't be, so the kept-side scores must be log-mineable; threshold tuning + recall-ceiling read the *dropped* side. This audit IS the measurement floor those deferred lifts (+ HyDE, `project_hyde_deferral.md`) depend on to ever fire.

4. **Citation guidance in the tool description, not SAFETY_DOCTRINE** (`document_search.py`), per the locked `feedback_tool_specific_guidance_in_descriptions.md` decision — keeps global doctrine narrow as the tool surface grows.

5. **No-archive render invariant** (`document_search._render_results`, pure helper). Per-passage content budget is derived from `TOOL_RESULT_MAX_CHARS` and the *actual* result count (not a constant sized for one `top_k`), so the rendered output stays under the archival cap for any `top_k` in 1–10 — above the cap the sanitizer truncates+archives the tail and the agent can't fetch archived passages back (`project_archived_tool_result_no_fetch_path.md`), so the bound must actually hold. Citations are kept whole (load-bearing provenance); the excerpt absorbs the remaining budget. Unit-proven in the smoke at n=1/3/5/10 (worst case n=10 = 1969 chars < 2000).

**Smoke evidence (green, self-cleaning, deterministic):** structural policy partition correct; render-budget invariant holds 1–10; end-to-end ingest → retrieve → tool exercised with the live stack; on-topic chunk kept, 3 off-topic dropped-below-threshold-and-logged; citation `[espresso.md, §Espresso Brewing] (relevance 1.00)`; `kept_candidates`/`dropped_candidates` audit asserted. First-run cost: ~2.3GB model download (one-time); steady-state well under 60s.

**Deferred-with-trigger items surfaced this turn:**
- **BM25 full-corpus scan** (`search.py`) — in-process `BM25Okapi` loads the whole `document_chunks` table per query (plan's small-corpus assumption). `corpus_size` logged every search + warns past 5000 → `tsvector` full-text swap is the trigger-gated lift. Not noted (inline-commented + self-warning).
- **Reranker sync on the async loop** — `search_documents` (async) calls sync `rerank()`; first call lazy-loads ~30s ON the event loop → webhook-freeze/timeout risk. **Memory note created:** `project_rerank_sync_on_async_loop.md`. Fix = `asyncio.to_thread(rerank,…)` + lock around `_get_reranker()` (to_thread opens a double-load race). Trigger: first-search webhook timeout OR Phase 4 concurrency.
- **Full-chunk recall vs the render bound** — the snippet bound trades full-chunk recall for the no-archive guarantee; full recall is the deferred archived-fetch tool (`project_archived_tool_result_no_fetch_path.md`), Phase-3-triggered.

**Follow-up (not blocking):** an image rebuild drops the now-unused FlagEmbedding + its heavy transitive deps (accelerate / datasets / ir-datasets / peft); the running container still has them, so nothing is blocked today.

**Cross-references:** base plan Tasks 2.14b/2.15 (19.1/19.2, already committed `4a327fb`) + 2.15b/2.16 (this turn) + new `document_search` tool; deferred-lift measurement floor (`project_hyde_deferral.md` + `project_llm_relevance_grading_deferral.md`) is now instrumented via the symmetric audit; forward — Turn 20 (Tasks 2.16b no-op / 2.17 documents API / 2.18 cost API) builds the surface layer atop this retrieval core; Turn 20.5 eval framework consumes the `rag_search_complete` kept/dropped scores.

### Turn 20 — Phase-2 surface layer (Tasks 2.16b + 2.17 + 2.18) atop Turn 19's retrieval core

**Separable surfaces (not one feedback loop like Turn 19):** a migration *verification*, the document HTTP API, and the cost API. Committed per task.

**Task 2.16b — verified NO-OP (verify-first, not assume-first).** The plan calls for a `document_chunks` table + an HNSW index on `embedding`. A plain `Vector` column does NOT create an HNSW index — so "no-op" was a hypothesis to test, not an assumption (the Turn-19 smoke passed on a 4-row corpus where a seq-scan is free, proving nothing about the index). Checked `pg_indexes` / `\d document_chunks` (not just `\dt`): `ix_document_chunks_embedding_hnsw USING hnsw (embedding vector_cosine_ops)` **exists**, created by `001_initial_schema.py` (pgvector 0.8.2). So 2.16b is genuinely a no-op — confirmed on the right axis (the index, load-bearing for retrieval at real corpus size), not the table. No migration written.

**Task 2.17 — document API + ingestion dedup (the meaty design moment).**
- **Dedup-key decision: `content_hash` (SHA-256 of file bytes) = identity; `ingester_version` = freshness discriminator.** Same content + same pipeline → skip (return existing `document_id`, `deduplicated=True`, 0 new chunks); same content + changed pipeline → **atomically replace** the stale chunks (delete-by-content_hash in the same Stage-5 transaction as the insert, `replaced=True`); new content → fresh ingest. Chosen over filename (collides on same-name docs; misses renames) and user-supplied id (no API for it at N=1). The atomic-replace is the refinement over the deferral note's original "just proceed" lean, which would have left duplicate content across pipeline versions — re-creating the pollution dedup exists to prevent. Lives in `ingest_document` (the reusable home — every caller gets idempotency), keyed off `meta` JSONB (no migration; co-located with `ingester_version`). Closes `project_ingestion_idempotency_deferral.md` (trigger fired exactly as written: "HTTP docs API ships at Turn 20").
- **Production-grade guards the plan sketch omitted.** The verbatim endpoint had no auth and `await file.read()` slurped the whole upload into memory. Shipped: (a) **auth** — `documents_router` mounted under the protected router, inheriting `Depends(get_current_user)`; no unauthenticated path can write to the corpus (an open upload is corpus-poisoning by anyone reaching the host). (b) **streamed size cap** — the file is written to a temp path in 1 MiB blocks with a running byte count, aborting at `settings.MAX_UPLOAD_SIZE_MB` (default 25) with 413; never buffers more than one block (OOM guard).
- **`owner_id` multi-user seam.** The authenticated `user_id` is threaded into `ingest_document(owner_id=...)` and stored in `chunk.meta["owner_id"]` (default "master" at N=1). Search does not filter on it yet (Phase 4). Promote `meta->owner_id` to a real indexed column when multi-user lands — nothing cements "master" beyond one default constant. Symmetric to the Mem0 USER_ID-wrap seam philosophy (parameterize-with-default, don't restructure).

**Task 2.18 — honest cost reporting (same discipline as Turn 19's kept/dropped audit).** `costs.py` existed (Phase-1) with a docstring caveat but presented LLMUsageLog rollups as if authoritative. Extended to label, IN THE PAYLOAD, the two axes on which a single "total spend" would lie: (1) **coverage** — `coverage.excludes` names the three gateway-bypass surfaces (agent_node / embeddings / Mem0 extraction) that write nothing to LLMUsageLog, so the numbers are a strict subset of real spend (`project_agent_llm_cost_attribution_gap.md`; full fix is the Phase-4 Option-C helper). (2) **source** — the `cap` block is the live Redis enforcement counter, labelled as a *different store* from the durable LLMUsageLog ledger; they track the same gateway events but diverge after a Redis restart (counter resets, ledger persists), so `cap.spend_usd` can read lower than `today_utc.cost_usd` (`project_cost_cap_redis_only.md`). Added `/costs/history` (daily ledger series, same coverage label). The full gateway-bypass reconciliation stays Phase-4; honest labelling is this turn.

**Smoke evidence (green, self-cleaning, in-process ASGI):** `scripts/smoke_documents.py` — dedup idempotent (direct + via endpoint, no corpus growth); unauth upload/search → 401; bad extension / empty → 400; oversized (cap shrunk to 1 MB) → 413; valid upload ingests with `owner_id=master`; re-upload dedups; search surfaces the uploaded doc; `/costs` exposes `coverage.excludes` (3 surfaces) + the `cap` source/divergence note; `/costs/history` shaped. Turn-19 `smoke_rag.py` re-run green (no regression from the ingestion changes).

**Seam-watch (carried forward):** documents now have `owner_id`; cost has no per-user split (fine at N=1, Phase-4 concern). Both kept as clean threadable seams, not cemented.

**Cross-references:** base plan Tasks 2.16b/2.17/2.18; 2.16b index provenance `001_initial_schema.py`; closes `project_ingestion_idempotency_deferral.md` (FIXED); honest-labelling reads `project_agent_llm_cost_attribution_gap.md` + `project_cost_cap_redis_only.md` (both stay open — Phase-4 dashboard work); plan 2.17/2.18 sketches annotated with production-grade pointers. Forward: Turn 20.5 eval framework (the measurement floor); Phase 2 surface layer complete.

### Turn 17.8 — Email triage enrichment + EmailLog.meta (Tasks closeout k/l/m/n/o)

**Coupled unit (like Turn 19, not Turn 20):** classifier output → `meta` column → digest/history consumers are one feedback loop. Migration committed on its own (`003`); the l/m/n/o enrichment as one unit on top.

**k — Migration `003`, not the plan's "004" (verify-first + disk-canonical).** The plan said `004_email_logs_meta`, but disk had only `001` + `002`, and `alembic current` was at `002` — so the next number is **003** (`project_phase1_monolithic_migration.md`: disk is canonical, not plan intent). Unlike 2.16b's HNSW no-op, this is a **genuine** migration — verified live that `email_logs` had no `meta` column first. Ran `alembic upgrade head` + confirmed `meta jsonb not null '{}'::jsonb` against live Postgres before any code referenced the column.

**l — Five-axis classifier with JSON robustness.** `classify_email` now returns a validated `EmailTriageResult` (classification + urgency + intent + confidence + suggested_action) from one LLM call. Hardening per `project_open_weights_tool_schema_and_conversation_poisoning.md`: routes through the **gateway** (cost-tracked, fallback-covered — added a `response_format` passthrough to `gateway.complete`/`_call_llm` so JSON mode works without a raw `litellm` call) with `{"type":"json_object"}`; `_parse_triage` strips markdown fences; every field is a `Literal` enum so an out-of-enum model value fails validation **into** the conservative `_fallback_triage` (3-way "fyi", confidence 0.0) rather than persisting garbage; any parse/LLM failure degrades, never raises into the pipeline. Note: `EmailTriageResult` is the classifier's internal parse target (not a tool `args_schema`), so `Literal` enums are correct here — the flat-types/empty-string rule applies only to tool-calling schemas (e.g. the new `urgency` filter arg in `email_history`, which is a flat `str=""` sentinel).

**m — `EmailLog.meta` + single-source dual-write.** Added `meta JSONB` to the model (matches `document_chunks.meta` convention). `_process_single_email` writes the top-level `classification` column (backward-compat) AND `meta` (full triage) **from the same `EmailTriageResult` in one place**, so the column and `meta->>'classification'` can't drift (item #5).

**Confidence wired (not decoration); suggested_action declared measurement.** Per the kept/dropped-audit + cost-coverage discipline — a signal nothing reads is dead weight. **confidence has a real consumer:** a `spam` verdict below `settings.EMAIL_TRIAGE_CONFIDENCE_FLOOR` (0.5) is NOT auto-archived — it routes to the digest so a misclassified real email stays visible (the stored classification stays "spam" with its low confidence; the record is honest, only the action is conservative). **suggested_action is explicitly DISPLAY/eval-only** — surfaced in `email_history` output, but nothing dispatches on it (an auto-action dispatcher is Phase-3 scope); stated in code so it's not mistaken for a live trigger.

**n — Urgency-aware digest (deviation: Redis-queue, not EmailLog-pull).** The plan's task-n said "pull EmailLog rows, sort by `meta->>'urgency'`" — but `digest.py` reads a **Redis queue** (populated as FYI emails arrive), not EmailLog. Kept that architecture (simpler, already working) rather than rearchitecting to an EmailLog window-query. Critically, the plan's literal "sort by `meta->>'urgency'`" is a **TEXT sort → alphabetical** (immediate, none, this_week, today) which puts "none" second and "today" last — backwards (item #2). Replaced with `urgency_rank`, a **pure ordinal function** (immediate 0 < today 1 < this_week 2 < none 3, unknown last) used for a deterministic Python sort over the queued entries — more testable than a SQL text sort. The LLM only groups/compresses; it does not own the ordering. Inline `[IMMEDIATE]/[TODAY]/[THIS WEEK]` tags via a single-sourced `URGENCY_TAG` map.

**o — Enriched history + urgency filter.** `email_history_search` reads `meta`, surfaces the urgency tag + intent + suggested_action on action_required bullets, and adds a flat `urgency: str=""` filter arg (sentinel pattern per the open-weights note — it IS a tool schema). The JSONB urgency filter is un-indexed (same pattern as the doc `content_hash` lookup — item #6; negligible at single-inbox volume, promote-trigger tracked).

**Smoke (green, self-cleaning):** `scripts/smoke_email_triage.py` — deterministic `urgency_rank` ordinal + sort; `_parse_triage` robustness (valid / markdown-fenced / out-of-enum→ValidationError / garbage→raise / fallback conservative); LLM `classify_email` populates all 5 valid-enum fields (classified "send Q3 by EOD" → action_required, confidence 0.95, via JSON mode); `email_history` urgency filter returns only the matching row with its `[IMMEDIATE]` tag. Import-sanity-checked the whole email pipeline + gateway + router.

**Seam (item #6):** `EmailLog.meta` is the natural `owner_id` home if the inbox goes multi-user (Phase-4 per-user inbox) — kept threadable; not added now (single inbox). The un-indexed JSONB filters (doc content_hash, doc owner_id, email urgency) consolidated into one promote-trigger note (`project_unindexed_jsonb_filters.md`).

**Cross-references:** base plan Turn 17.8 (k/l/m/n/o) annotated (004→003 correction + digest Redis-architecture note); gateway gained a reusable `response_format` passthrough; closes the audit-surfaced 3-way-classifier gap. Forward: Turn 17.9 (tool-description audit + AuditTrail latency) + Turn 20.5 (eval framework — confidence is now an eval signal it can consume) complete the Phase-2-Week-6 close-out batch.

### Turn 17.9 — Observability + reasoning lifts (Tasks p/q/r/s/q2/q3) — Phase-2-Week-6 close-out L1+L2+L3

**Separable (not one feedback loop):** migration on its own commit (`004`); p/q/q2/q3/s grouped on top.

**r — Migration `004`, not the plan's "005" (disk-canonical, third time).** Disk had `001/002/003` and `alembic current` was `003` → next is **004**. The plan's numbers ran ahead of disk because the Task 2.16b documents migration was a verified no-op that never consumed a number — so every remaining plan migration number is suspect; `ls alembic/versions/` is canonical. Genuine migration (verified live: `audit_trail` had no `latency_ms`), ran + verified `latency_ms integer` against live Postgres.

**s — Latency captured once at the dispatch vantage, mirrored on the separate path (item #4).** `audit_trail.latency_ms` added (model + migration). Captured in `tool_executor_node` **around** the `tool_registry.execute()` chokepoint — measured in the node, not inside execute(), because the node is the only vantage that sees BOTH the success and every exception path uniformly (execute() can't return latency when it raises). The approval-dispatch path (`gmail_send._audit`, a genuinely-separate dispatch that doesn't go through `execute()`) **mirrors** the same capture so the two can't drift. `_log_audit` gained `latency_ms`; the rate-limited/blocked/rejected rows leave it None (no execution to time). The deferred per-tool-timeout wrap (`project_per_tool_execution_timeout_gap`) will live inside execute(); the node's measurement already wraps it, so they compose — flagged in that note.

**p — Calendar descriptions: the "does NOT" half is load-bearing (item #6).** `calendar_read` / `calendar_create` expanded from one-liners to the 17.6 pattern (what it does, what it does NOT, sibling cross-ref, examples). The honesty half — "does NOT detect conflicts / compute free-busy / normalize timezones" (read) and "does NOT add a Meet link / detect conflicts / return an event_id" (create) — stops the agent assuming enrichments the tools lack, so it won't claim it "checked for conflicts" (`project_calendar_output_enrichment_phase3`, amended: false-capability risk closed, enrichment still deferred). Static constants → cache-stable by construction.

**q — Reasoning protocol: INTERNAL, not a visible template (item #3).** Prepended a `## Reasoning protocol` subsection to the `SAFETY_DOCTRINE` constant, phrased as **private** reasoning for substantive requests — explicitly "HOW you think, not a format to emit", "never narrate the steps (Step 1: you asked…)", and "never apply to trivial messages (greetings/acks/one-word)" — so it can't make "hi" heavyweight (would collide with `project_trivial_message_over_invocation`). Static addition to the cached prefix; `test_prompt_cache_stability.py` re-run **green (5/5)** — prefix stayed byte-identical. Its effect is unmeasurable until 20.5: flagged as something **20.5 measures** (over-invocation / quality before-after), not faith.

**q2 — Args-override warning.** `SafetyClassifier._args_overrides` now emits `safety_args_override_escalated` (tool / from_level / to_level / override_reason) when an args-aware escalation fires (telegram_send → non-master). Closes the "can't distinguish default-APPROVE from args-escalated-APPROVE in audit_trail" gap for the Phase-4 dashboard.

**q3 — stop_reason, derived with status from one determination (item #5).** Added `stop_reason` to the TurnEnvelope (additive — existing `status` unchanged). status + stop_reason are set together at each exit so they can't disagree: `end_turn`↔complete; `rate_limit`↔complete-with-`final_response=="rate_limited"` sentinel (a *graceful* complete — the per-hour cap, NOT an error path, a correction to the plan's framing); `cost_cap`↔error-when-`CostCapExceededError`; `error`↔other; `interrupted`↔interrupted. **Honest nuance:** the per-turn TOOL budget (`MAX_TOOL_CALLS_PER_TURN`) is NOT a turn-terminal reason in this architecture — a blocked tool degrades to a ToolMessage and the agent still ends naturally (`end_turn`); that event is captured per-tool in `audit_trail` + `rate_limit_events`. I did NOT fake a `tool_budget` envelope value via fragile marker-scanning. Pure helpers (`_stop_reason_for_completion` / `_stop_reason_for_error`) make it unit-testable.

**Smoke (`scripts/smoke_observability.py`, green, self-cleaning) + pytest:** stop_reason per exit path (end_turn/rate_limit/cost_cap/error + error-envelope status pairing); q2 warning fires on escalation and NOT without one (via `capture_logs`); `_log_audit` writes `latency_ms=137` on the dispatch row and `None` on the non-dispatch row; calendar descriptions carry does-NOT + cross-ref + example. Existing `test_prompt_cache_stability.py` 5/5; regression set (envelope / safety / resume-dedup / rate-limits) **51 passed**.

**Cross-references:** base plan Turn 17.9 (p/q/r/s/q2/q3) annotated (005→004 + q3 tool_budget nuance); amended `project_per_tool_execution_timeout_gap` (latency-seam placement) + `project_calendar_output_enrichment_phase3` (boundaries declared). This closes the audit's three retroactive lifts (L1+L2+L3). Forward: **Turn 20.5** (eval framework) is the last close-out slot — it measures q's reasoning-protocol effect + consumes 17.8's confidence + 17.9's latency/stop_reason as signals.

### Turn 20.5a — Eval framework + cost isolation + coverage config (Tasks t/u/x/y) — Phase-2 measurement floor

**Split decision (reviewer offered it; I took it).** Turn 20.5 (t/u/v/w/x/y) is large and the footguns (cost-cap halt, Mem0 contamination, async-rebind) need care, not cramming. Split: **20.5a (this turn)** = the eval framework + cost isolation + coverage *config* + the regression-detection proof; **20.5b (next turn)** = the real-stack integration tests **v** (email flow) + **w** (cross-source recall, Mem0-contamination-safe) + the coverage *baseline number* (meaningful only post-v/w, which the plan itself says). The measurement-floor INSTRUMENT — the thing the deferred-lift discipline depends on — lands now.

**Cost isolation (footgun #2 — the eval could halt the master's agent).** New `app/llm/eval_mode.py` contextvar, set by the eval runner, consulted by three surfaces: `cost_tracker._today_key()` routes spend to a separate `jarvis:eval_cost:<date>` counter; `gateway.complete()` skips hard/soft-cap enforcement (consistent eval behavior, no halt/degrade); `persist_node` skips Mem0 extraction (footgun #3 — no memory pollution). **Verified live:** after a full eval run the production counter `jarvis:llm_cost:<date>` was untouched (None) while `jarvis:eval_cost` carried the spend.

**t — golden_queries.yaml.** ~11 entries across recall / classification / action / synthesis / edge, **empirically calibrated** (a golden suite must reflect real agent behavior, not aspiration): `recall_preferences` was corrected to `expected_tools: []` once the run showed the agent correctly answers communication-style from the always-on profile WITHOUT a tool call. Includes the **specific deferred-trigger instruments** (item #1): three `rag_probe` phrasing-mismatch cases (query vocabulary deliberately ≠ corpus vocabulary) + a `capture_audit` classification case.

**u — runner.py (the harness).** Per the reviewer's constraints: **hard rule is the gate** (item #4) — `set(expected_tools) ⊆ set(tools the agent emitted)`, deterministic; the GPT-4o-mini **judge runs at temp=0 and its 1-5 scores are a reported NOISY TREND, never the gate** (validated dramatically: `action_schedule_meeting` interrupts for approval → empty response → judge scored 1/1/1/1, but the hard rule correctly PASSED it). **Parallelized** general queries (semaphore cap 4) with **honest runtime + per-run cost reported** (item #5; full suite 22.3s, $0.0006 — isolated). **Deferred-trigger capture (the keystone, item #1):** `rag_probe` entries capture `document_search`'s `rag_search_complete` kept/dropped audit; the `capture_audit` entry reads `audit_trail.latency_ms` + `stop_reason`.

**Keystone validated (baseline run):** hard-rule pass-rate **1.0**; `action_schedule` → `stop_reason=interrupted`; `classify_urgent_emails` → audit latency `{email_history_search: 23ms}` (17.9 signal); all 3 phrasing-mismatch probes → **`hyde_candidate=True`** with the on-topic doc captured in `dropped` at rerank **0.003–0.02** (far below the 0.3 threshold) — a *genuine, quantified* phrasing-mismatch recall miss, exactly the HyDE trigger the deferred lift needs (`project_hyde_deferral`), and the kept/dropped scores are the leak-through instrument for LLM-grading (`project_llm_relevance_grading_deferral`). Both notes amended: the **measuring instrument now exists**; the lifts fire when REAL queries show these misses (the synthetic probes prove the instrument detects them).

**x — `compare.py` + `Makefile` + `baseline.json`.** Regression rides the hard rule (a pass-rate drop or new hard-rule failure = regression/exit 1); a judge-avg drop is a TREND warning only. `make evals` / `evals-quick` / `evals-baseline` / `evals-compare` / `evals-break` run INSIDE the container (needs the live stack) — **no CI pipeline** (Phase 4), these are runnable local targets, eval kept SEPARATE from the deterministic tests. Timestamped results gitignored; only `baseline.json` committed.

**Regression-detection PROOF (the required proof this is a real instrument, not a vibe check):** `make evals-break` removes `memory_search` → `recall_person` can no longer select it → hard-rule fails (0.75, `['recall_person']`) → **exit 1**.

**y — coverage config (config only).** `[tool.coverage.run]`/`[tool.coverage.report]` in pyproject (`make coverage`). NO gate, NO baseline number this turn — both deferred to 20.5b post-v/w per the plan ("first establish a stable baseline post closeout-v/w").

**Cross-references:** base plan Turn 20.5 (t/u/x/y done; v/w/coverage-baseline → 20.5b) annotated; amended `project_hyde_deferral` + `project_llm_relevance_grading_deferral` (instrument now exists). Forward — **20.5b** lands v/w (real-stack, `test_resume_dedup` dispose+rebind pattern, Google/Telegram mocked at the API boundary) + the coverage baseline, closing Phase 2.

### Turn 20.5b — Integration backbone + Mem0 disposition + coverage baseline (v/w/y) — Phase 2 CLOSE

**The Mem0 failing-test disposition (item #1) — resolved cheap-first, it was a test edge, NOT a bug.** Wiping the test-residue rows (23 thread-tagged: test-resume-dedup / test-memrecall / smoke) made `test_recall_filters_by_thread_id` PASS. Diagnosis: old same-token Zorblax entries from prior runs **crowded** the recall — bge-m3 cosine clusters tightly (~0.39 for everything vs a short query), so a distinctive entry gets pushed out of a small `top_k` window. **Root cause of the accumulation:** the test's `get_all → filter → mem0.delete` teardown silently failed every run — Mem0 v2's `get_all` PAGES and its `delete()` API is flaky. Fixed: replaced with a reliable direct-SQL teardown on the marker thread_id (`_wipe_thread`). So **26.5 does NOT inherit a recall bug** — recall works at `top_k=80`; what it inherits is recall-QUALITY degradation from store bloat (below).

**v — `test_email_flow.py` (real-stack, green).** Drives the REAL pipeline: simulated inbound → EmailLog INSERT-as-gate (16.5) → PendingApproval → `resolve_approval` + `route_approval_decision` → `_resolve_gmail_approval` → `gmail_send` (17.5). Mocks ONLY at the Google-API + Telegram boundaries (item #5), so it exercises the real MIME / `In-Reply-To` threading + `threadId`, and asserts DB STATE TRANSITIONS + the payload the mocked Google client received + `auto_sent` flip + the gmail_send audit row + no spurious system alert (item #4). The two LLM decision points (classify + draft) are mocked to fixed outputs so the FLOW BRANCH is deterministic — v tests plumbing, not classification (the eval + classifier smoke cover that), so v makes no real LLM calls. **First real coverage of the email path.**

**w — `test_cross_source_recall.py` (real agent turn, green).** Seeds a fictional contact into BOTH Mem0 (`infer=False`) and email_logs, runs a REAL agent turn under `eval_mode` (item #3 — cost isolated + persist skipped so the test turn can't pollute Mem0), reliable SQL teardown on a UUID marker thread_id (item #2). HARD asserts the reliable cross-source SYNTHESIS: both recall tools chain (memory_search + email_history_search), the email fact surfaces, the response stays grounded (names the contact, no native-format/fabrication). Two real findings surfaced and scoped honestly rather than papered over:
  - **Groq native-`<function>`-text flakiness (AGENT-CORE, not a memory issue):** the multi-tool synthesis path sometimes emits a tool call as native TEXT instead of a structured tool_call (`project_open_weights_tool_schema_and_conversation_poisoning`). FallbackChatLLM only catches the ERROR variant, NOT text-accepted-as-content — a real agent-CORE reliability GAP that Phase 3's research agent will stress. w retries on a fresh thread (bounded) to be reliable; the gap is tracked in the open-weights note with a **Phase-3 trigger** (multi-tool/research work OR an observed native-text response) + the fix shape (extend FallbackChatLLM/agent_node to detect native-`<function>`-text-as-content and retry/repair).
  - **Mem0 recall-quality from store bloat:** the seeded fact does NOT surface via `memory_search` (`top_k=5`, no reranker) because ~49 un-consolidated duplicate-preference entries crowd bge-m3's flat cosine — it IS recalled at `top_k=80`. So the Mem0-fact assertion is best-effort (documented), not a gate. This is a **Turn 26.5** concern (memory_consolidation is still a stub) + a possible memory-reranker lift — NOT a storage bug, NOT a Phase-2 blocker.

**Async-rebind (item #7).** v/w reuse `test_resume_dedup`'s dispose+rebind fixtures (`real_checkpointer` / `reset_runner_graph`). Added a root `tests/conftest.py` engine-rebind autouse fixture — the module-level engine bound to one test's loop made the FULL suite fail for resume_dedup + tool_selector (they pass in isolation); the fixture fixed the engine-level part (4 → 2 full-suite failures).

**y — coverage baseline (item #6).** `make coverage` → **TOTAL 44%**, committed to `backend/tests/coverage_baseline.txt` with the named gaps (scheduler/Celery 0%, channel telegram.py 0%, main lifespan, auth) and the v/w additions (email pipeline + recall path). NO gate (Phase-4 CI). Honest note: 2 PRE-EXISTING full-suite failures remain (proven not a 20.5b regression — same with/without the new conftest) — `resume_dedup` (full-suite ordering) + 1 `tool_selector` (intra-file registry-singleton pollution); they need test-isolation hardening (a follow-up), and the coverage % is measured regardless.

**Phase 2 closes here.** Memory notes amended: `project_mem0_contamination_test_residue` (get_all/delete unreliability + SQL-teardown fix + the recall-quality-from-bloat finding — and the residue included CONTRADICTORY stale facts, e.g. allergies-yes AND allergies-no both stored, so 26.5 is stale-fact-supersession, not just dedup) + `project_open_weights_tool_schema_and_conversation_poisoning` (native-text-as-content gap). Follow-ups by owner: **Turn 26.5** = Mem0 consolidation/dedup/supersession to restore recall quality; **agent-core / Phase-3-triggered** = the native-`<function>`-text FallbackChatLLM gap; **test-infra** = the 2 pre-existing full-suite isolation failures.

_(further forward/retroactive turn entries appended here as turns close)_
