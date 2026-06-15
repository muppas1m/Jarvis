"""
Settings — single source of truth for runtime configuration.

Loaded from `.env` at the project root. Pydantic v2 Settings does the parsing,
type coercion, and value validation. Anything that other modules need at runtime
should live here, not be re-read from os.environ scattered around the codebase.

The class is instantiated once at import time as `settings`. That singleton
pattern is fine for our process-per-container architecture; if we ever go
multi-process or want hot-reload of config, swap to a `get_settings()` function
with `@lru_cache`.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",  # tolerate stray env vars docker-compose passes through
    )

    # --- Database -------------------------------------------------------------
    DATABASE_URL: str            # async (asyncpg) — used by FastAPI / SQLAlchemy
    DATABASE_URL_SYNC: str       # sync (psycopg2) — used by Alembic migrations
    POSTGRES_ADMIN_PASSWORD: str = "jarvis_dev_admin"

    # --- Redis ----------------------------------------------------------------
    REDIS_URL: str

    # --- LLM providers (all optional — fill the ones you actually use) -------
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OLLAMA_BASE_URL: str = "http://localhost:11434"   # Required — runs BGE-M3 embeddings
    GOOGLE_GEMINI_API_KEY: str = ""

    # --- Active model selection (swap by env var, no code change) ------------
    PRIMARY_MODEL: str = "groq/llama-3.3-70b-versatile"
    FAST_MODEL: str = "groq/llama-3.1-8b-instant"
    # Different provider on purpose so single-provider outages don't kill the agent.
    FALLBACK_MODEL: str = "openai/gpt-4o-mini"
    # Dedicated extraction LLM for Mem0 — see project_mem0_extraction_gemini_swap.
    # PRIMARY_MODEL on Groq free tier saturates TPM after ~1 memory write.
    MEMORY_EXTRACTION_MODEL: str = "gemini/gemini-2.5-flash-lite"

    # --- Mem0 interim bloat controls (P5c) -----------------------------------
    # Dedup-on-write: skip a write when an existing memory is near-identical
    # (cosine score >= threshold). DISABLED by default — P5c calibration showed
    # today's Mem0 search scores near-identical content at only ~0.45 (raw-turn
    # query vs condensed-fact store + degraded recall), so it can never fire at a
    # safe threshold and would just burn one dead search per write. Flip ON +
    # tune the threshold once Turn 26.5 fixes search/recall quality (the same
    # degraded search is why Mem0's own infer-dedup fails and the bloat grows).
    # The ACTIVE interim lever is trivial-turn gating (manager._is_trivial_turn).
    MEM0_DEDUP_ENABLED: bool = False
    MEM0_DEDUP_THRESHOLD: float = 0.92

    # --- Embedding model (LOCKED at BGE-M3, schema depends on dim) -----------
    EMBEDDING_MODEL: str = "ollama/bge-m3"
    EMBEDDING_DIMS: int = 1024

    # --- Document ingestion robustness (regression fix) ----------------------
    # Contextualization runs on the PAID Gemini, NOT Groq: a per-chunk fan-out
    # on Groq free-tier saturates TPM (same reason MEMORY_EXTRACTION_MODEL is on
    # Gemini) and starves the agent's chat. Concurrent dispatch + bounded fan-out
    # turns a sequential 166s/74-chunk crawl into seconds. Per-call timeouts so a
    # hung Ollama embed / slow LLM degrades (skip) instead of freezing ingestion.
    CONTEXTUALIZER_MODEL: str = "gemini/gemini-2.5-flash-lite"
    CONTEXTUALIZE_CONCURRENCY: int = 5
    CONTEXTUALIZE_TIMEOUT_S: int = 30
    EMBED_TIMEOUT_S: int = 30

    # --- RAG retrieval (Phase 2, Turn 19) ------------------------------------
    # Hybrid search (vector + BM25) → RRF fusion → bge-reranker-v2-m3 → threshold.
    RERANK_MODEL: str = "BAAI/bge-reranker-v2-m3"
    RERANK_USE_FP16: bool = False           # CPU deployment; set True only on GPU
    RAG_CANDIDATE_POOL: int = 50            # per-retriever candidate cap fed to fusion
    RAG_TOP_K: int = 5                      # final passages returned after rerank+threshold
    RAG_RERANK_THRESHOLD: float = 0.3       # permissive; drops below-score chunks (logged)
    RAG_RRF_K: int = 60                     # Reciprocal Rank Fusion smoothing constant

    # --- Telegram (Phase 1) --------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_MASTER_CHAT_ID: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_USE_POLLING: bool = True   # long-poll in dev, webhook in prod

    # --- Cloudflare Tunnel ---------------------------------------------------
    TUNNEL_PUBLIC_URL: str = ""
    CLOUDFLARE_TUNNEL_ID: str = ""

    # --- Google (Phase 2) ----------------------------------------------------
    GOOGLE_PROJECT_ID: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GMAIL_PUBSUB_TOPIC: str = ""
    GMAIL_PUBSUB_SUBSCRIPTION: str = ""
    GOOGLE_CREDENTIALS_PATH: str = "backend/secrets/google_credentials.json"
    WEBHOOK_SECRET_GMAIL: str = ""

    # --- Inbound-email health canary (P2) ------------------------------------
    # gmail_check writes a heartbeat on every clean poll; the canary alerts the
    # master in plain language when no poll has succeeded within MAX_STALE_HOURS
    # (the Jun-11 outage was silent ~2 weeks). REALERT_HOURS bounds re-pinging
    # during a sustained outage; recovery clears the alert flag immediately.
    INBOUND_HEALTH_MAX_STALE_HOURS: int = 3
    INBOUND_HEALTH_REALERT_HOURS: int = 12

    # --- Search / Crawl (Phase 3) -------------------------------------------
    # Tavily is the active research provider — Brave is kept declared for
    # future swap if/when their free tier returns. See memory:
    # project_phase3_search_provider.md.
    TAVILY_API_KEY: str = ""
    BRAVE_SEARCH_API_KEY: str = ""
    FIRECRAWL_API_KEY: str = ""

    # --- WhatsApp (Phase 4) --------------------------------------------------
    WHATSAPP_PHONE_NUMBER_ID: str = ""
    WHATSAPP_BUSINESS_ACCOUNT_ID: str = ""
    WHATSAPP_ACCESS_TOKEN: str = ""
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_MASTER_PHONE: str = ""
    WHATSAPP_API_VERSION: str = "v21.0"
    WHATSAPP_FOLLOWUP_TEMPLATE_NAME: str = "jarvis_followup"
    WHATSAPP_FOLLOWUP_TEMPLATE_LANG: str = "en"

    # --- Langfuse (observability — self-hosted) ------------------------------
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "http://localhost:3002"   # 3000/3001 occupied on this dev box
    LANGFUSE_ENABLED: bool = True

    # --- Security ------------------------------------------------------------
    ENCRYPTION_KEY: str = ""
    API_SECRET_KEY: str = ""
    AUTH_SECRET: str = ""
    MASTER_PASSKEY: str = ""

    # --- App ------------------------------------------------------------------
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "DEBUG"
    BASE_URL: str = "http://localhost:8000"

    # --- Cost & rate limits --------------------------------------------------
    DAILY_LLM_SPEND_CAP_USD: float = 5.00
    DAILY_LLM_SOFT_CAP_PCT: float = 0.80    # at 80% of hard cap, force FAST_MODEL
    MAX_TOOL_CALLS_PER_TURN: int = 8
    MAX_AGENT_TURNS_PER_HOUR: int = 100
    TOOL_RESULT_MAX_CHARS: int = 2000       # results bigger than this are archived
    MAX_UPLOAD_SIZE_MB: int = 25            # /documents/upload hard cap — streamed, never buffered whole

    # --- Voice (Phase 4 — "Jarvis speaks") -----------------------------------
    # Persona honorific — how Jarvis addresses the master (gender-derived
    # default; "Sir" for male, "Ma'am" for female). Lives in the system prompt.
    MASTER_HONORIFIC: str = "Sir"
    # Two-speed cascade (§B): voice turns route the agent's reasoning LLM to the
    # FAST slot for sub-second first-token, escalating to the frontier model
    # once tools have run. The brain (tools/memory/safety/approval) is unchanged.
    VOICE_FAST_TIER: bool = True
    # Instant filler masks heavy-tier latency — if first-token hasn't arrived
    # within this budget, Jarvis speaks a short "One moment, Sir…" line.
    VOICE_FILLER_DELAY_MS: int = 900
    # Streaming TTS provider: "edge" (free, no key, British male — the default),
    # "piper" (local community "JARVIS" voice; set PIPER_VOICE_PATH), or
    # "elevenlabs" (flash; set ELEVENLABS_API_KEY + ELEVENLABS_VOICE_ID).
    TTS_PROVIDER: str = "edge"
    EDGE_TTS_VOICE: str = "en-GB-RyanNeural"
    PIPER_VOICE_PATH: str = ""               # path to the .onnx voice inside the container
    ELEVENLABS_API_KEY: str = ""
    ELEVENLABS_VOICE_ID: str = ""
    ELEVENLABS_MODEL: str = "eleven_flash_v2_5"
    # Metered-voice daily cap (only bites when a cloud TTS like ElevenLabs is on).
    VOICE_DAILY_COST_CAP_USD: float = 1.00

    # --- Approval flow -------------------------------------------------------
    APPROVAL_EXPIRY_HOURS: int = 72
    AUTO_APPROVE_REPLY_MAX_WORDS: int = 80

    # --- Email triage (Turn 17.8) --------------------------------------------
    # Below this classifier confidence, a "spam" verdict is NOT auto-archived —
    # it routes to the digest instead, so a misclassified real email stays
    # visible rather than silently vanishing from the inbox.
    EMAIL_TRIAGE_CONFIDENCE_FLOOR: float = 0.5


settings = Settings()
