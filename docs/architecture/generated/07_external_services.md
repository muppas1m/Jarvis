<!-- AUTO-GENERATED — do not edit by hand.
     Regenerate with `make architecture` (or scripts/gen_architecture.py).
     Source of truth is the code; edit the code, then regenerate. -->

# External Services & Dependencies

Every external / infrastructure dependency the system talks to. Interconnection FLOWS are the Phase-2 DFD; this is the mechanical inventory.

## Infrastructure (docker-compose services)

| Service | Image / build |
|---|---|
| `backend` | build: ./backend |
| `celery-beat` | build: ./backend |
| `celery-worker` | build: ./backend |
| `langfuse-clickhouse` | clickhouse/clickhouse-server:24 |
| `langfuse-db` | postgres:16-alpine |
| `langfuse-minio` | minio/minio:latest |
| `langfuse-minio-init` | minio/mc:latest |
| `langfuse-redis` | redis:7-alpine |
| `langfuse-web` | langfuse/langfuse:3 |
| `langfuse-worker` | langfuse/langfuse-worker:3 |
| `postgres` | pgvector/pgvector:pg16 |
| `redis` | redis:7-alpine |


## LLM providers (reached via the gateway slots — see `06_llm_gateway.md`)

| Provider |
|---|
| google |
| groq |
| openai |


## APIs, datastores & observability (curated roles — from config, secrets omitted)

| Dependency | Role | Configured via |
|---|---|---|
| Ollama (local model server) | embeddings + reranker | `OLLAMA_BASE_URL` · embed `ollama/bge-m3` · rerank `BAAI/bge-reranker-v2-m3` |
| Postgres + pgvector | datastore + vector store | `DATABASE_URL` — LangGraph checkpoints, app tables, mem0 + tool + document vectors |
| Redis | cache / counters / Celery broker | `REDIS_URL` — cost cap, rate limits, Celery |
| Telegram Bot API | chat channel (long-poll / webhook) | `TELEGRAM_BOT_TOKEN` |
| Google / Gmail | email + calendar + Pub/Sub push | `GOOGLE_*` OAuth · `GMAIL_PUBSUB_TOPIC` / `GMAIL_PUBSUB_SUBSCRIPTION` |
| Langfuse | LLM observability / tracing | `LANGFUSE_HOST` |


## Detected config endpoints (auto-scanned — self-surfaces new deps)

Setting names ending in `_URL` / `_HOST` / `_BASE_URL` / `_TOPIC`. A new endpoint-shaped setting appears here automatically; give it a curated role in the table above.

- `BASE_URL`
- `DATABASE_URL`
- `GMAIL_PUBSUB_TOPIC`
- `LANGFUSE_HOST`
- `OLLAMA_BASE_URL`
- `REDIS_URL`
- `TEST_DATABASE_URL`
- `TUNNEL_PUBLIC_URL`
