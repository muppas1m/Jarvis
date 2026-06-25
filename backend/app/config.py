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

    # --- Mem0 FACT-LEVEL dedup-on-write --------------------------------------
    # Skip a write when an existing memory is near-identical to the FACT being
    # written (true cosine >= threshold). The dedup now runs in add_fact() against
    # a single extracted fact (not the old turn-blob, which never matched a stored
    # fact → 0 skips/48h while identical facts piled up). Threshold biased HIGH
    # because the cost is asymmetric — wrongly skipping a DISTINCT/updated fact
    # loses information, wrongly keeping a paraphrase is only minor bloat.
    # Re-measured 2026-06-25 on real bge-m3 cosines. "Same fact, restated" spans a
    # wide band by phrasing distance; the gate skips its >=0.97 tail:
    #   exact re-write + TIGHTEST paraphrase (SKIPPED): 0.97 – 1.0   (e.g. "allergic to shellfish" ×2 = 0.99; "allergic to shellfish"→"shellfish allergy" = 0.97)
    #   looser paraphrase (NOT skipped):                0.60 – 0.96  (teetotaller variants 0.89–0.95; "does not drink" vs "is teetotal" ~0.60)
    #   contradiction ("morning" vs "afternoon"):       up to 0.962  ← must NOT skip
    #   negation ("allergic" vs "not allergic"):        <= 0.878      ← must NOT skip
    #   distinct facts (shellfish vs peanuts):          <= 0.844
    # The looser-paraphrase band (<=0.96) and the contradiction band (up to 0.962)
    # OVERLAP — cosine cannot separate "restate" from "update", so lowering the gate
    # to catch those paraphrases would start suppressing contradictions. So this gate
    # is a NARROW safety-net, not the bloat fix: the bloat fix is extraction precision
    # (the owned extractor cut ~6 -> ~0.5 facts/turn). 0.97 is the safe floor — above
    # the 0.962 contradiction ceiling (never suppresses an update); it skips exact
    # re-writes + the tightest paraphrases (>=0.97), but the observed teetotaller
    # pile-up at 0.89–0.95 is NOT caught here — that cross-turn paraphrase merging is
    # the deferred consolidation engine's job, truth-guards not a threshold.
    # Trivial-turn gating (manager._is_trivial_turn) still runs upstream.
    MEM0_DEDUP_ENABLED: bool = True
    MEM0_DEDUP_THRESHOLD: float = 0.97

    # Upper bound for Mem0Client.get_all(). Mem0's get_all/list default to
    # top_k=20 and SILENTLY truncate — a 1.4k-row corpus came back as 20, which
    # would make any batch job over the corpus process a 20-row subset. We pass
    # this explicit high limit so the FULL corpus returns; get_all logs a canary
    # if the row count ever reaches it (corpus outgrew the bound → raise it).
    MEM0_GET_ALL_LIMIT: int = 50_000

    # --- Recall relevance gate (4.B.1) ---------------------------------------
    # Minimum TRUE-cosine score for a memory to be injected into the agent's
    # <memories> context. mem0_client.search now returns the raw cosine (it
    # bypasses Mem0 v2's hybrid fusion, which halved + compressed every score
    # into an indistinguishable ~0.29-0.48 band — see
    # project_mem0_search_quality_root), so a threshold is finally meaningful:
    # measured unrelated query↔memory cosines sit ~0.40 and genuinely relevant
    # ones ~0.57-0.85, so 0.5 cleanly drops the noise the old always-top-10 path
    # injected as "relevant." Tunable.
    MEM0_RECALL_THRESHOLD: float = 0.5

    # --- Conversation compaction (4.B.3) -------------------------------------
    # At a turn boundary, if the verbatim history exceeds THRESHOLD tokens, the
    # oldest messages are LLM-summarized into a rolling summary and dropped,
    # keeping ~KEEP_RECENT tokens verbatim. Durable facts live in Mem0, so the
    # summary may be lossy on facts but preserves the conversational thread.
    # Token counts use tiktoken (cl100k) as an APPROXIMATION of llama tokens —
    # fine for a meter + a tunable threshold (the agent runs on llama/Groq).
    COMPACT_ENABLED: bool = True
    COMPACT_THRESHOLD_TOKENS: int = 6000
    COMPACT_KEEP_RECENT_TOKENS: int = 2500
    # Summarizer runs on the gateway FALLBACK slot (gpt-4o-mini), NOT the
    # rate-limited Groq fast tier — so compaction can't persistently fail under
    # Groq rate-limits and let history grow unbounded.
    COMPACT_MODEL_SLOT: str = "fallback"
    COMPACT_TIMEOUT_S: float = 30.0

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
    RAG_CANDIDATE_POOL: int = 12            # per-retriever candidate cap fed to fusion — bounded so the
    #                                         CPU cross-encoder actually COMPLETES the rerank within
    #                                         RERANK_TIMEOUT_S and the memory budget on the single-worker
    #                                         box (was 50 → ~21s + a ~2GB balloon that OOM'd the worker;
    #                                         24 still timed out → degrade-every-time; 12 completes fast).
    #                                         Raise on a bigger box / larger corpus (it's the recall pool).
    RAG_TOP_K: int = 5                      # final passages returned after rerank+threshold
    RAG_RERANK_THRESHOLD: float = 0.3       # permissive; drops below-score chunks (logged)
    RAG_RRF_K: int = 60                     # Reciprocal Rank Fusion smoothing constant
    # Bound the cross-encoder rerank. A slow/unavailable reranker — notably a
    # first-load model download that stalls — DEGRADES the search to the fusion
    # ranking instead of hanging the turn. An unbounded rerank once wedged the
    # WHOLE backend (health included): the stalled download pinned the search
    # turn, and the cascade exhausted the pool. Reranker is warmed at startup, so
    # in steady state predict is sub-second; this only bites on an anomaly.
    RERANK_TIMEOUT_S: int = 20
    # Cross-encoder predict() batch size — bounds the PEAK memory of one forward pass. A large batch on
    # bge-reranker-v2-m3 transiently allocates ~2GB of activations; on the single-worker box (no
    # per-service mem limit, a ~7.6GB VM shared with the 8-service langfuse stack) that balloon OOM/swaps
    # the worker MID-rerank — before wait_for(RERANK_TIMEOUT_S) can degrade, because wait_for bounds the
    # await, not the to_thread compute. Small batches cap the high-water mark so a single search can
    # never wedge the worker on memory. See project_rerank_sync_on_async_loop.
    RERANK_BATCH_SIZE: int = 16
    # Cross-encoder input truncation (tokens). Attention cost is O(seq_len²), so this bounds BOTH the
    # rerank's CPU time AND its activation memory far more than batch/pool alone (which barely moved the
    # ~1.4GB forward-pass working set). bge-reranker-v2-m3's max is 512; long legal-PDF chunks near that
    # made a 12-pair rerank take ~18s on the single-worker CPU box. 256 keeps the relevance signal (it's
    # in the lead tokens) while cutting time + memory ~4×. Raise toward 512 on a faster box.
    RERANK_MAX_LENGTH: int = 256
    # Hard OOM-wedge guard: skip the rerank (degrade to fusion) when the VM's free
    # memory is below this, since one forward pass balloons ~1.4GB and wait_for
    # bounds the AWAIT not the to_thread compute — so under low headroom the
    # rerank can OOM/swap-freeze the single worker (health 000) before it can
    # degrade. With this, a search can never wedge the worker on memory: tight box
    # → fusion ranking; healthy box → full rerank. See project_rerank_sync_on_async_loop.
    RERANK_MIN_FREE_MB: int = 2000

    # --- Telegram (Phase 1) --------------------------------------------------
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_MASTER_CHAT_ID: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_USE_POLLING: bool = True   # long-poll in dev, webhook in prod

    # --- Cloudflare Tunnel ---------------------------------------------------
    TUNNEL_PUBLIC_URL: str = ""
    CLOUDFLARE_TUNNEL_ID: str = ""

    # --- Email provider selection --------------------------------------------
    # Which EmailProvider adapter Jarvis uses for ALL email (send / receive /
    # search / watch). "gmail" today; "outlook" plugs in as a second adapter with
    # no agent/approval/safety changes. Switching providers is THIS config value.
    EMAIL_PROVIDER: str = "gmail"

    # --- Email provider runtime (non-blocking + resilient) -------------------
    # The Gmail SDK is synchronous; the adapter runs each call OFF the event loop
    # (asyncio.to_thread) and BOUNDS it (asyncio.wait_for) so a hung round-trip
    # can't wedge the agent — the same to_thread/wait_for idiom the reranker uses.
    EMAIL_PROVIDER_TIMEOUT_S: float = 15.0   # per Gmail round-trip
    # The Google Calendar SDK is synchronous too — the read paths run off-loop +
    # bounded via the same to_thread/wait_for idiom (calendar_tool._blocking).
    CALENDAR_TIMEOUT_S: float = 15.0         # per Google Calendar round-trip
    # Readiness period reads resolve the master's TZ from the profile; this is the
    # FLAGGED fallback when always_on["timezone"] is unset — never a SILENT UTC
    # (a wrong TZ lands events in the wrong period). Override per deployment.
    DEFAULT_TIMEZONE: str = "UTC"
    # Readiness look-ahead (4.3): surface a task due BEYOND the asked period only if
    # its priority's horizon reaches it — high warns weeks out, low never. Days past
    # the period end. The priority-scaled bar that keeps a licence-renewal (high) weeks
    # ahead in view while a weekend errand (low) stays out.
    READINESS_LOOKAHEAD_HIGH_DAYS: int = 30
    READINESS_LOOKAHEAD_MEDIUM_DAYS: int = 7
    READINESS_LOOKAHEAD_LOW_DAYS: int = 0
    # Briefing 7am push (5.3): the push windows (HWM, now] but caps the start at
    # now − this, so an unread HWM can't grow the digest unbounded. The push never
    # advances the HWM (a missed push must still surface under "what's the latest").
    BRIEFING_PUSH_CAP_DAYS: int = 7
    # The 7am brief is also persisted (morning_briefs) so the HUD can poll + show it
    # (persist-then-poll). The HUD shows the latest brief created within this freshness
    # window, then it ages off (the next daily run replaces it). 20h < 24h so the
    # prior day's brief is gone before the next one lands (no two-brief overlap).
    BRIEFING_HUD_TTL_HOURS: int = 20
    # Send resilience: retry ONLY definitely-didn't-send failures (HTTP 429/503 —
    # rejected at the gateway before the send ran). Timeouts / 5xx / 4xx are
    # surfaced, never blind-retried (a read-timeout may have already delivered).
    EMAIL_SEND_RETRIES: int = 2              # extra attempts beyond the first
    EMAIL_SEND_RETRY_BASE_S: float = 0.5     # exponential backoff base (×2 per attempt)

    # --- Google (Phase 2) ----------------------------------------------------
    GOOGLE_PROJECT_ID: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REFRESH_TOKEN: str = ""
    GMAIL_PUBSUB_TOPIC: str = ""
    GMAIL_PUBSUB_SUBSCRIPTION: str = ""
    GOOGLE_CREDENTIALS_PATH: str = "backend/secrets/google_credentials.json"
    WEBHOOK_SECRET_GMAIL: str = ""
    # Gmail webhook OIDC enforcement (Phase 4.5). SHADOW by default: the real
    # verifier runs + logs its verdict on every push, but a FAILED verdict does
    # NOT 403 — so flipping the Phase-2 always-True stub to the real verifier
    # can't 403 the whole inbox before the live Pub/Sub subscription's
    # oidcToken.audience is confirmed to match WEBHOOK_SECRET_GMAIL. Flip to True
    # to ENFORCE once a real push has been observed passing (look for the
    # `gmail_webhook_verified` log line).
    GMAIL_WEBHOOK_ENFORCE: bool = False

    # --- Inbound-email health canary (P2) ------------------------------------
    # email_check writes a heartbeat on every clean poll; the canary alerts the
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
    # Default OFF: the self-hosted langfuse stack is heavy (~2.6GB) + now profile-gated
    # in docker-compose. Containers force this via compose's JARVIS_TRACING var; flip on
    # only with the `observability` profile up. Both callback paths (LiteLLM + LangGraph)
    # are gated on this, so OFF = traces dropped, never a request error (fail-open).
    LANGFUSE_ENABLED: bool = False

    # --- Security ------------------------------------------------------------
    ENCRYPTION_KEY: str = ""
    API_SECRET_KEY: str = ""
    # AUTH_SECRET MUST match the frontend's AUTH_SECRET: the wake-word WS ticket
    # is signed by the frontend BFF and verified here (_verify_jwt) with this key.
    # Rotate BOTH sides together or the wake-word breaks.
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
    # Streaming TTS provider: "piper" (local jgkawell/jarvis "JARVIS" voice baked
    # into the image — the default, $0 + the real timbre), or "edge" (free cloud
    # British male, the fallback). ElevenLabs is intentionally not wired.
    TTS_PROVIDER: str = "piper"
    PIPER_VOICE_PATH: str = "/opt/piper/en/en_GB/jarvis/medium/jarvis-medium.onnx"
    # Piper synthesis tuning — tune by ear. length_scale < 1.0 = faster pace;
    # noise_scale / noise_w default to the model's own values (None) — lowering
    # noise_scale slightly can reduce the medium model's buzz.
    PIPER_LENGTH_SCALE: float = 0.97
    PIPER_NOISE_SCALE: float | None = None
    PIPER_NOISE_W: float | None = None
    # Piper's default normalize_audio=True peak-normalises Jarvis's quiet output
    # up to full scale (~5x) and clips → the "buzz". False keeps it clean (~-14
    # dBFS); the browser playback gain (useJarvis) compensates the level.
    PIPER_NORMALIZE_AUDIO: bool = False
    EDGE_TTS_VOICE: str = "en-GB-RyanNeural"
    # Metered-voice daily cap (only bites when a cloud TTS like ElevenLabs is on).
    VOICE_DAILY_COST_CAP_USD: float = 1.00
    # Bound ONE sentence's synthesis (parity with WHISPER_TIMEOUT_S on transcribe):
    # tts.synthesize wraps the provider call in asyncio.wait_for so a stuck/slow synth
    # degrades to b"" (that sentence is skipped) instead of stalling the read-out.
    # Piper is normally sub-300ms/sentence, so this only bites on an anomaly.
    TTS_TIMEOUT_S: int = 15

    # Wake-word (Phase 4.2 — server-side openWakeWord "hey jarvis"). Fire the
    # "wake" event when the score exceeds WAKE_THRESHOLD — lowered for fewer
    # misses; raise toward 0.5 if false-positives appear. WAKE_VAD_THRESHOLD is a
    # SEPARATE Silero-VAD gate (decoupled from the fire score): low, just enough
    # to drop pure silence without gating out quiet speech.
    WAKE_THRESHOLD: float = 0.35
    WAKE_VAD_THRESHOLD: float = 0.2

    # Local command STT (Phase 4.3b — faster-whisper, replaces browser Web Speech).
    # The same mic→WS stream feeds a server-side whisper in "capture" mode. A small
    # CPU model keeps latency low; int8 compute is the fast CPU path. The model
    # downloads to the HF cache (persisted in the hf_cache volume) and is warmed at
    # startup (background), so the first capture never pays the load.
    WHISPER_MODEL: str = "base.en"          # base.en/small.en; base.en = lower CPU latency
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"      # int8 = fastest on CPU; float32 = most accurate
    WHISPER_BEAM_SIZE: int = 5              # small beam — better accented proper-noun decode than greedy(1)
    # Bound CTranslate2's intra-op threads so one transcription can't grab every
    # core and starve the event loop (or contend with the reranker's torch threads).
    WHISPER_CPU_THREADS: int = 4
    # Bound transcription so a slow/stuck model DEGRADES the turn ("I didn't catch
    # that, Sir") instead of hanging it — same lesson as RERANK_TIMEOUT_S. Covers the
    # 45s CAPTURE_MAX_MS at beam5: measured worst-case transcribe ≈0.45× real-time
    # (temperature-fallback) → ~20s for 45s, so 40s is ~2× margin; typical ≈1-3s.
    WHISPER_TIMEOUT_S: int = 40

    # --- STT quality (Phase 4.5; all additive + reversible-by-env) -----------
    # Bias the decoder toward the master's name (accented "Jarvis" → "Jovis"/"Gavis"
    # otherwise). faster-whisper 1.2.1 supports `hotwords`. Empty string = no bias.
    WHISPER_HOTWORDS: str = "Jarvis"
    # Break the "okay okay all right all right" repetition loop the small model falls
    # into on noise — the standard command-STT fix. True restores the old looping.
    WHISPER_CONDITION_ON_PREVIOUS_TEXT: bool = False
    # whisper's OWN native non-speech / hallucination gates (its defaults, exposed
    # so they're tunable). A segment over no_speech_threshold with logprob under
    # log_prob_threshold is treated as silence; compression_ratio over its threshold
    # flags repetitive hallucination.
    WHISPER_NO_SPEECH_THRESHOLD: float = 0.6
    WHISPER_LOG_PROB_THRESHOLD: float = -1.0
    WHISPER_COMPRESSION_RATIO_THRESHOLD: float = 2.4
    # Post-transcribe non-speech rejection (return "" → no phantom turn). CONSERVATIVE
    # by design — dropping real quiet/short speech is worse than the rare junk turn,
    # so reject only CLEAR non-speech. Set WHISPER_REJECT_NONSPEECH=false to disable
    # the whole post-filter by env. Thresholds tuned from measured noise-vs-speech gap.
    WHISPER_REJECT_NONSPEECH: bool = True
    WHISPER_REJECT_AVG_LOGPROB: float = -1.2   # mean avg_logprob at/under this → reject (very low confidence)
    WHISPER_REJECT_NO_SPEECH_PROB: float = 0.9  # mean no_speech_prob at/over this → reject (near-certain silence)
    WHISPER_REJECT_MIN_WORDS: int = 6           # repetition guard only kicks in past this many words
    WHISPER_REJECT_UNIQUE_RATIO: float = 0.4    # unique/total words at/under this (and ≥ min words) …
    WHISPER_REJECT_REPEAT_LOGPROB: float = -0.8  # … AND mean logprob at/under this → reject. The
    #     confidence gate keeps a CONFIDENT but repetitive real command (logprob well above this)
    #     from being dropped — only the low-confidence repetition of a hallucination is rejected.
    # Capture endpointing (Silero VAD owns the listening window — no more Web
    # Speech premature no-speech idle-drop). Speech ends after this much trailing
    # silence; a hard cap bounds a runaway utterance; the pre-roll buffer keeps the
    # onset (the first word of a barge-in command) from being clipped.
    CAPTURE_VAD_THRESHOLD: float = 0.3      # frame VAD score above this = speech
    # Trailing silence that finalizes a capture. The master's tuned-by-feel value:
    # 1600ms felt laggy on every turn, so 1200ms (=15 frames @ 80ms) — covers a
    # natural MID-SENTENCE pause up to ~1.2s. TRADEOFF (accepted by the master): a
    # rare full ~1.5s pause may still finalize, traded for a snappier end-of-turn
    # since this same delay is added to the end of EVERY turn before Jarvis
    # responds. Dial by feel via env.
    CAPTURE_SILENCE_HANGOVER_MS: int = 1200
    CAPTURE_MAX_MS: int = 45000             # hard cap on one utterance (~45s; long monologue, pauses ride)
    CAPTURE_PREROLL_MS: int = 400           # rolling onset buffer prepended to the capture
    # No-speech timeout: if NO speech onset arrives within this of a capture
    # starting, emit an empty transcript so the client idles back to wake-word.
    # The backend owns this (not a frontend wall-clock that's blind to mid-speech)
    # — once speech HAS started, the hangover + CAPTURE_MAX_MS own finalization, so
    # a long command is captured, never dropped. The frontend window is only a
    # generous safety backstop above CAPTURE_MAX_MS.
    CAPTURE_NO_SPEECH_MS: int = 7000

    # --- Weather widget (dashboard 4.C.3) ------------------------------------
    # Open-Meteo (no API key). Default location Pompano Beach, FL + °F, all
    # config-backed so a future settings UI can edit them — the seam is here, the
    # UI isn't built yet. Override via env (WEATHER_LAT, WEATHER_LON, …).
    WEATHER_LAT: float = 26.2379
    WEATHER_LON: float = -80.1248
    WEATHER_LABEL: str = "Pompano Beach"
    WEATHER_TEMP_UNIT: str = "fahrenheit"   # "fahrenheit" | "celsius"
    WEATHER_WIND_UNIT: str = "mph"          # "mph" | "kmh" | "ms" | "kn"

    # --- Approval flow -------------------------------------------------------
    APPROVAL_EXPIRY_HOURS: int = 72
    AUTO_APPROVE_REPLY_MAX_WORDS: int = 80

    # --- Email triage (Turn 17.8) --------------------------------------------
    # Below this classifier confidence, a "spam" verdict is NOT auto-archived —
    # it routes to the digest instead, so a misclassified real email stays
    # visible rather than silently vanishing from the inbox.
    EMAIL_TRIAGE_CONFIDENCE_FLOOR: float = 0.5


settings = Settings()
