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

    # --- Embedding model (LOCKED at BGE-M3, schema depends on dim) -----------
    EMBEDDING_MODEL: str = "ollama/bge-m3"
    EMBEDDING_DIMS: int = 1024

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

    # --- Approval flow -------------------------------------------------------
    APPROVAL_EXPIRY_HOURS: int = 72
    AUTO_APPROVE_REPLY_MAX_WORDS: int = 80


settings = Settings()
