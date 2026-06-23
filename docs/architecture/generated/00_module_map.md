<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# Module Map

The running system (`app/`) plus operational entry points (`scripts/`). One-line role from each module's docstring. (`tests/` and `alembic/` are excluded as support tooling.)

## `app/` — the system (99 modules)

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
│   ├── decision_resolver.py — Natural-language resolution of a pending decision (A2 Piece 2).
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
│   ├── activity.py — Authenticated 24h activity feed (4.C.3) — a dignified, master-facing view of
│   ├── approvals.py — Approvals API + helpers.
│   ├── chat.py — POST /api/chat — synchronous, non-streaming agent turn over HTTP.
│   ├── costs.py — GET /api/costs — LLM spend snapshot, honestly labelled.
│   ├── documents.py — Document RAG API — upload + search over the master's ingested corpus.
│   ├── health.py — Public liveness/readiness endpoint.
│   ├── memory.py — Read-only memory inspector endpoints.
│   ├── router.py — API router aggregator.
│   ├── system.py — Authenticated dashboard telemetry (4.C.2).
│   ├── voice.py — POST /api/voice/stream — SSE token-streamed + spoken agent turn (Phase 4 4.1).
│   └── weather.py — Authenticated weather (4.C.3) — Open-Meteo, no API key. Config-backed location
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
│   ├── observability.py — Langfuse hooks.
│   └── stream_mode.py — Token-stream flag — turns on internal LLM streaming for the agent's chat
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
│   ├── llm_health.py — Passive LLM-call health (4.C.3) — zero token cost.
│   ├── logging.py — Structured logging helper — single import point for the rest of the codebase.
│   └── runtime_stats.py — In-process runtime stats for the dashboard (4.C.2): process uptime + a real
├── voice/
│   ├── __init__.py — Voice layer (Phase 4) — streaming TTS + the voice-turn orchestration helpers.
│   ├── chunker.py — Sentence chunker — slices a streamed token feed into speakable sentences.
│   ├── markdown_strip.py — Strip markdown SYNTAX from a sentence so it speaks (and captions) as clean words.
│   ├── transcribe.py — Local command STT — faster-whisper (Phase 4.3b, replaces the browser Web Speech API).
│   ├── tts.py — Streaming TTS — provider-pluggable, sentence-at-a-time.
│   └── wakeword.py — Server-side wake-word — openWakeWord "hey jarvis" (Phase 4.2).
├── __init__.py — —
├── config.py — Settings — single source of truth for runtime configuration.
└── main.py — FastAPI app factory + lifespan.
```

## `scripts/` — operational entry points

```
scripts/
├── gen_architecture.py — Architecture-doc generator — introspects the LIVE code and emits Markdown +
├── google_oauth.py — One-time Google OAuth refresh-token bootstrap.
├── issue_jwt.py — Mint an HS256 JWT for the master so we can curl protected endpoints
├── reset_thread.py — Reset (delete) a conversation thread's checkpoint state.
├── seed_profile.py — Seed (or re-seed) the master's profile row.
├── setup_gmail_watch.py — One-shot Gmail watch registration. Phase 2 Task 2.2 closer.
├── smoke_agent.py — Turn 9 smoke test — one full agent turn end-to-end.
├── smoke_documents.py — Turn 20 smoke — document API (upload/search) + ingestion dedup + cost honesty.
├── smoke_email_triage.py — Turn 17.8 smoke — email triage enrichment (classifier → meta → consumers).
├── smoke_extractors.py — Turn 18 smoke test — document extractors + semantic chunker round-trip.
├── smoke_fallback_chain.py — Turn 11a Smoke 3 — fallback chain fires when PRIMARY provider returns an error.
├── smoke_langfuse_nodes.py — Turn 11a Smoke 2 — verify all four graph nodes appear as discrete spans
├── smoke_llm.py — Turn 5 smoke test — one round-trip through the gateway, then verify
├── smoke_mem0_rpm.py — Turn 11a Smoke 1 — Mem0 sustained throughput on Gemini 2.0-flash.
├── smoke_memory.py — Turn 6 smoke test — the memory system end-to-end.
├── smoke_observability.py — Turn 17.9 smoke — observability + reasoning lifts (p/q/q2/q3/s).
├── smoke_rag.py — Turn 19.6 smoke — RAG retrieval pipeline correctness (NOT retrieval quality).
├── smoke_telegram_route.py — Turn 11b — deterministic Telegram channel smoke.
└── smoke_tools.py — Turn 10 smoke test — tool registry end-to-end.
```
