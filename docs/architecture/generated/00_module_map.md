<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# Module Map

The `app/` package — 86 modules, one-line role from each module's docstring.

```
app/
├── agent/
│   ├── tools/
│   │   ├── __init__.py — Tool registration entry point.
│   │   ├── builtin_memory.py — memory_search — built-in tool, always loaded.
│   │   ├── calendar_tool.py — Google Calendar tool — read, create, update, delete events (+ conflict check).
│   │   ├── document_search.py — document_search — agent-facing RAG tool over ingested documents.
│   │   ├── email_history.py — Email history search — query email_logs + pending_approvals for recall.
│   │   ├── gmail_send.py — Gmail send tool — outbound email via the OAuth-authenticated Gmail account.
│   │   └── registry.py — Tool registry with dynamic embedding-based selection.
│   ├── __init__.py — —
│   ├── context.py — Per-turn context builder — thin facade over MemoryManager.
│   ├── graph.py — StateGraph wiring + AsyncPostgresSaver checkpointer.
│   ├── message_repair.py — Message-history repair — orphaned tool_call → synthetic ToolMessage.
│   ├── nodes.py — Graph nodes — the four steps of an agent turn.
│   ├── prompts.py — System-prompt construction.
│   ├── rate_limits.py — Per-turn / per-conversation rate limiting for the agent loop.
│   ├── runner.py — Public agent entry point.
│   ├── safety.py — Action Safety Classifier — every tool call is intercepted before execution.
│   ├── sanitizer.py — Tool-result sandboxing.
│   └── state.py — AgentState — the dict that flows through every graph node.
├── api/
│   ├── webhooks/
│   │   ├── __init__.py — Channel webhook receivers — Telegram in Phase 1, Gmail Phase 2, WhatsApp Phase 4.
│   │   ├── gmail.py — Gmail Pub/Sub push notification receiver.
│   │   └── telegram.py — Telegram webhook receiver — production inbound path.
│   ├── __init__.py — —
│   ├── approvals.py — Approvals API + helpers.
│   ├── chat.py — POST /api/chat — synchronous, non-streaming agent turn over HTTP.
│   ├── costs.py — GET /api/costs — LLM spend snapshot, honestly labelled.
│   ├── documents.py — Document RAG API — upload + search over the master's ingested corpus.
│   ├── health.py — Public liveness/readiness endpoint.
│   ├── memory.py — Read-only memory inspector endpoints.
│   └── router.py — API router aggregator.
├── db/
│   ├── __init__.py — —
│   ├── engine.py — Database engine + session factory.
│   └── models.py — ORM models — every table the application owns.
├── documents/
│   ├── __init__.py — Document ingestion: extract → chunk → (Turn 19: contextualize → embed → store).
│   ├── chunker.py — Semantic chunking with token-budget ceiling.
│   ├── contextualizer.py — Anthropic Contextual Retrieval — per-chunk context summaries.
│   ├── extractors.py — Structure-preserving text extraction.
│   ├── ingestion.py — Document ingestion pipeline — extract → chunk → contextualize → embed → store.
│   ├── reranker.py — bge-reranker-v2-m3 cross-encoder reranking — a pure scoring function.
│   └── search.py — Hybrid document retrieval — vector + BM25 → RRF fusion → cross-encoder rerank.
├── email/
│   ├── __init__.py — Email integration — Gmail watch + Pub/Sub handler + classifier (Phase 2).
│   ├── classifier.py — Multi-dimensional email triage (Turn 17.8).
│   ├── digest.py — Daily email digest — accumulates FYI emails and delivers at 8am.
│   ├── gmail_pubsub.py — Handle incoming Gmail Pub/Sub push notifications.
│   ├── gmail_watch.py — Gmail watch setup and renewal.
│   └── responder.py — —
├── llm/
│   ├── __init__.py — —
│   ├── bootstrap.py — LiteLLM provider wiring — idempotent.
│   ├── cost_tracker.py — Daily LLM-spend tracker.
│   ├── eval_mode.py — Eval-mode flag — isolates eval runs from the PRODUCTION cost-cap and Mem0.
│   ├── fallback_llm.py — FallbackChatLLM — agent_node resilience wrapper for primary → fallback dispatch.
│   ├── gateway.py — LLM gateway — every model call in the codebase goes through here.
│   ├── models.py — Model registry — single source of truth for which LLMs we route to.
│   └── observability.py — Langfuse hooks.
├── memory/
│   ├── __init__.py — —
│   ├── manager.py — MemoryManager — the single entry point the rest of the codebase uses to read
│   ├── mem0_client.py — Mem0 self-hosted wrapper.
│   ├── session.py — Tier 2 — Session analytics view.
│   └── user_profile.py — Tier 5 — Master's profile.
├── messaging/
│   ├── channels/
│   │   ├── __init__.py — —
│   │   └── telegram.py — Telegram channel — Phase 1 primary.
│   ├── __init__.py — —
│   ├── channel.py — Channel abstraction.
│   ├── channel_registry.py — Channel registry.
│   ├── failure_alerter.py — Channel-routed system alerts.
│   └── router.py — Inbound + resume routing.
├── scheduler/
│   ├── tasks/
│   │   ├── __init__.py — Scheduled Celery tasks — autodiscovered by app.scheduler.celery_app.
│   │   ├── approval_expiry.py — Hourly sweeper — auto-rejects approvals whose expires_at has passed.
│   │   ├── gmail_check.py — 15-min Gmail safety-net poll.
│   │   ├── gmail_renew.py — Renew the Gmail Pub/Sub watch twice weekly + sweep the recent inbox.
│   │   ├── inbound_health.py — Inbound-email health canary.
│   │   ├── memory_consolidation.py — Memory consolidation — Turn 17 stub.
│   │   └── morning_brief.py — 8am daily morning brief — email digest + (future) news section.
│   ├── __init__.py — Celery scheduler package — Celery app, beat schedule, periodic tasks.
│   ├── beat_schedule.py — Celery beat schedule — periodic task definitions.
│   ├── celery_app.py — Celery app instance + per-worker-process initialization.
│   ├── task_helpers.py — Per-task async state reset.
│   └── task_wrapper.py — @critical_task decorator — alerts master after 3 consecutive failures.
├── security/
│   ├── __init__.py — Auth + crypto helpers. Wider security primitives land here as they're needed.
│   ├── auth.py — Auth dependency — dual path, single FastAPI dependency.
│   └── webhook_verify.py — Webhook signature / JWT verification.
├── utils/
│   ├── __init__.py — —
│   ├── exceptions.py — Custom exception hierarchy.
│   └── logging.py — Structured logging helper — single import point for the rest of the codebase.
├── __init__.py — —
├── config.py — Settings — single source of truth for runtime configuration.
└── main.py — FastAPI app factory + lifespan.
```
