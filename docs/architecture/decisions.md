# Jarvis — Design Decisions, Seams & Deferred Work

The *why* behind the architecture (see [README.md](README.md) for the *what* and the flows). This is
hand-authored intent — keep it current when a change shifts the system's shape.

---

## Design narrative

**Single-master (N=1) by design.** Jarvis serves one person ("master"). This is a load-bearing
assumption, not an accident — it justifies skipping multi-tenant isolation, per-user quotas, and most
horizontal-scaling concerns. Where multi-user would later matter, the code threads a clean seam (see
*Seams*) rather than building the machinery now.

**LangGraph `StateGraph` + a Postgres checkpointer is the agent core.** The four-node graph
(`memory_load → agent → tool_executor ↔ → persist`, `agent/graph.py`) is deliberately linear and
small. The reason it's LangGraph and not a hand-rolled loop is the **durable interrupt/resume**: an
APPROVE-tier tool calls `interrupt()`, the `AsyncPostgresSaver` checkpoints the paused state, and a
human decision (possibly minutes later, possibly after a restart) resumes it via `Command(resume=…)`.
Consequence the design must respect everywhere: **the node re-runs from the top on resume**, so
side-effecting steps are made idempotent (single-tool-per-invocation; the P3 approval-dedup guard;
the P1 orphaned-tool_call repair).

**Every tool call passes a safety classifier** (`agent/safety.py`): SAFE (silent) · NOTIFY
(run+inform) · APPROVE (pause for the master) · BLOCKED (never). Unknown tools default to APPROVE —
fail-safe. This is the spine of "the agent can act, but irreversible/outward actions need a yes."

**One LLM gateway, centralized** (`llm/gateway.py`, [routing doc](generated/06_llm_gateway.md)).
Task-type routing, a daily hard/soft spend cap, and a single cross-provider fallback hop all live in
one place so cost and observability aren't scattered. Two deliberate bypasses: the agent's chat uses
`FallbackChatLLM` (a wrapper, not the gateway, so LangGraph `bind_tools` works) and embeddings call
litellm directly (local + free) — both tracked as a known attribution gap.

**Open-weights reality shapes the tool schemas.** The primary model is Groq Llama — cheap and fast,
but it chokes on `anyOf:[…, null]` JSON Schema and sometimes emits tool calls as text. So tool args
use flat types + empty-string sentinels, and there's an orphaned-tool_call repair + a fallback
wrapper. Anything model-quality-sensitive (contextualization) is routed to the **paid Gemini slot**,
off Groq, because Groq free-tier saturates TPM after a small burst.

**Memory is Mem0 over pgvector, tiered.** Profile (always-on / on-demand) + episodic/semantic facts.
Persist runs at end of turn, gated to skip trivial turns. Recall is best-effort — and the honest
current limitation is that **Mem0's semantic search under-discriminates** (the shared root of both
the per-session bloat and recall misses), which is why dedup-on-write ships *disabled* and real
consolidation is Turn 26.5.

**RAG is hybrid + contextual.** Vector (pgvector) + BM25 → Reciprocal Rank Fusion → a bge cross-encoder
reranker → threshold (`documents/search.py`). Chunks are embedded with an LLM-generated context
preface (Anthropic contextual retrieval). The reranker runs off the event loop (`asyncio.to_thread`)
because its first call lazy-loads a ~30s model.

**Channels are abstracted** (`messaging/channel.py`): Telegram is the only one wired (long-poll in
dev), but the router + approval flow speak to a `Channel` interface so a second surface (webhook,
WhatsApp) drops in without touching the agent.

**Ingestion is offloaded.** A document upload acks immediately and ingests on a detached task with
its sync stages (`extract`, `chunk`) pushed off-thread and contextualization fanned out concurrently
on Gemini — because awaiting it inline froze the whole Telegram poller.

---

## Architectural seams (threaded, not yet active)

| Seam | Where it's threaded | What activates it |
|---|---|---|
| **Multi-user** | `owner_id` in `document_chunks.meta`; `USER_ID="master"` in Mem0 (`memory/mem0_client.py`); `user_id` in `security/auth.py`/`UserContext`; ingestion takes `owner_id` | Real second user OR Phase-4 dashboard. The lift (Phase 1.5b) threads `user_id` through recall/search filters + promotes the JSONB `owner_id` to an indexed column. Forward work stays multi-user-*friendly* so the retrofit is mechanical. |
| **MCP** | The tool registry is MCP-shaped already — name + description + args_schema + handler (`agent/tools/registry.py`), wrapped as LangChain `StructuredTool` | A real MCP client/server (Phase 1.5a, lands with Phase-3 external tools). Today's tools are in-process Python; the registry contract doesn't change when they become MCP-served. |
| **N-provider fallback** | Gateway has a 3-slot hardcoded fallback (primary/fast/fallback) + the contextualizer slot | A research-agent quality cascade (Groq→Anthropic→OpenAI→Gemini) OR an observed multi-provider outage. |
| **Subgraph topology** | Single linear graph today | Phase-3 research/news/booking work showing code-shape smells (type-specific `AgentState` fields, `agent_node` branching by intent) → router-first topology with per-type subgraphs. |

---

## Deferred, with triggers

The discipline: defer with a **concrete trigger**, not "someday." Source of truth is the project
memory notes; this table is the navigable index.

| Item | Status / why deferred | Trigger to revisit |
|---|---|---|
| **Mem0 search/embedding quality** | Near-identical content scores ~0.45, no discrimination — root of bloat + recall | **Turn 26.5 — lead here.** Upstream of consolidation, dedup, recall. |
| Mem0 consolidation / dedup / stale-fact supersession | Nightly job is a stub; dedup-on-write disabled (can't fire on degraded search) | Turn 26.5 (after the search fix). |
| Extraction volume (~7 facts/turn) | Separate bloat contributor from search quality | Turn 26.5 (alongside, not conflated). |
| HyDE / query rewriting | Latency cost concrete, recall lift speculative on a personal corpus | Eval framework shows phrasing-mismatch recall failures. |
| LLM relevance grading | Duplicative with the cross-encoder reranker | Eval data shows irrelevant chunks slipping past the reranker threshold. |
| Per-tool execution timeout | Current tools are fast / have internal HTTP timeouts | Phase-3 browser/firecrawl/research tools with real hang risk. |
| Archived tool_result fetch path | Sanitizer truncates+archives; no agent-callable reader | Phase-3 large web-scrape results OR a truncation complaint. |
| Un-indexed JSONB filters (4 sites) | `meta->>'key'` seq-scans; negligible at N=1 | Corpus/inbox growth OR multi-user (one coordinated migration). |
| Concurrent-identical-upload dedup (TOCTOU) | Content-hash dedup is sequential-only | Concurrent uploads OR multi-user (needs a UNIQUE constraint). |
| Gmail-handler decoupling | `_resolve_gmail_approval` is Gmail code in the channel router | A 2nd channel-origin approval handler (calendar invite, booking). |
| LLM-gateway bypass surfaces (agent_node, embeddings, Mem0) | Cost attribution gap; $0–trivial today | Phase-4 dashboard surfacing cost-by-surface OR embeddings move to a paid API. |
| Calendar conflict on UPDATE | Conflict check is create-only | Wanted reschedule-into-conflict warning — needs self-exclusion (don't flag the event's own slot). |
| OCR / photographed documents | Photo handler acknowledges, doesn't read | A real OCR need (currently: "send it as a file"). |
| Persistent Cloudflare tunnel | Live state is ad-hoc per-session | Production-readiness OR sustained webhook-mode usage. |
| Langfuse v3 stack weight (8 services) | Heavy for single-master, but frontier-correct observability | Constrained-RAM deployment OR a lighter v3+ SDK. |
| OAuth scope minimization + revocation alerting | `gmail.modify` + full calendar scope are broad | Master-uses-daily OR Phase-4 multi-user OR shared-host deploy. |
| Conversational "send it" (email) | Explicitly deferred — Approve/Reject button covers it | Indefinite; the button surface may suffice forever. |
| Groq error-string-match fragility (fallback predicate) | String-matches `tool_use_failed` | Groq renames the error → monitor `agent_llm_fallback` rate as the canary. |
| Native-`<function>`-text glitch (open-weights) | Intermittent text-as-tool-call; fallback catches only the error variant | Phase-3 agent-core hardening. |
| Drift-gate validates the working tree, not the staged index | The hook regenerates from the live container (= working tree), so it false-fails on unstaged structural WIP, and "regenerated-but-forgot-to-stage-the-docs" downgrades to the nudge rather than the hard-fail | Multi-dev, OR the false-fail becomes a recurring annoyance. Fix: regenerate against a `git checkout-index` of the staged tree. |

> **Recently closed** (this fix pass): inbound email + Celery (stale-token), approval double-prompt,
> orphaned-tool_call crash, doc-upload freeze (offload + concurrent Gemini contextualize + timeouts),
> RAG re-hunt (rerank off-loop + cap + stop-prompt), attribution conflation, the contextualizer
> concurrent-dispatch and rerank-sync-on-loop deferrals.

---

## Keeping this current
Phase 3 installs a drift-gate that re-generates the mechanical docs and nudges when a structural file
changes without `docs/architecture/` being touched. The gate enforces the *mechanical* half; **this
file and the README are the intent half — update them in the same commit when a change moves a box on
the DFD or adds/retires a decision or a deferred item.**
