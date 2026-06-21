"""
Mem0 self-hosted wrapper.

Everything stays in our own pgvector instance — no third-party servers see
any conversation excerpt, preference, or behavioral pattern.

Mem0 v2 deviations from the implementation plan:
  - Plan uses sync `Memory` + asyncio.to_thread. v2 ships a real `AsyncMemory`
    class that we use directly (no thread-pool punt needed).
  - Plan's embedder config used `"provider": "litellm"`. v2 has no litellm
    embedder — embeddings must go through a direct provider. We use the
    `ollama` provider talking to the host's Ollama daemon for BGE-M3.
  - Plan's LLM config used `"provider": "litellm"`. v2 still has this and
    we keep it so swapping models in `.env` flows through Mem0 too.
"""
import asyncio
from typing import Any
from urllib.parse import urlparse

from mem0 import AsyncMemory

from app.config import settings
from app.llm.bootstrap import wire_litellm_providers
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Columns Mem0 writes into every pgvector row's payload alongside OUR metadata.
# Everything in a payload that ISN'T one of these is a key we set (thread_id,
# kind, key, …) and belongs in the caller-facing `metadata` dict.
_MEM0_SYSTEM_PAYLOAD_KEYS = frozenset({
    "data", "hash", "created_at", "updated_at",
    "user_id", "agent_id", "run_id", "actor_id", "role", "text_lemmatized",
})


def _shape_vector_hit(row: Any) -> dict[str, Any]:
    """Vector-store ``OutputData`` → our ``{id, content, score, metadata}`` shape.

    ``content`` is the memory text (``payload['data']``); ``metadata`` is the
    payload minus Mem0's system columns; ``score`` is the raw cosine similarity
    (``1 - <=> distance``) the store already computed.
    """
    payload = dict(getattr(row, "payload", None) or {})
    content = payload.get("data") or payload.get("memory")
    metadata = {k: v for k, v in payload.items() if k not in _MEM0_SYSTEM_PAYLOAD_KEYS}
    return {
        "id": str(getattr(row, "id", "") or ""),
        "content": content,
        "score": float(getattr(row, "score", 0.0) or 0.0),
        "metadata": metadata,
    }


# Mem0 v2 routes its extraction LLM through LiteLLM, which reads provider keys
# from os.environ at call time. Without this call, GEMINI_API_KEY (mapped from
# settings.GOOGLE_GEMINI_API_KEY) never makes it into the environment because
# Mem0 import path doesn't go through gateway.py. Idempotent — safe to call
# from every LiteLLM-using module.
wire_litellm_providers()


# Highest-priority rules injected into Mem0's extraction LLM (see Mem0
# ADDITIVE_EXTRACTION_PROMPT — custom_instructions are "User-defined rules,
# highest priority"). Steers auto-save toward DURABLE personal facts and away
# from the transient/task/agent chatter the default prompt over-extracts. We
# pass the turn as a single "User: …/Assistant: …" string (persist_turn), so
# Mem0 can't natively scope to user-role messages — these rules carry the
# "Assistant line is context only" guard explicitly. Measured 4.B.2: 7→3
# facts/turn on a representative mix, with every dropped fact being noise
# (agent commentary, one-off task requests). See project_mem0_search_quality_root.
JARVIS_EXTRACTION_INSTRUCTIONS = """You are extracting DURABLE long-term memories for a personal AI assistant whose single user is its owner. Each input is ONE conversation turn formatted as "User: ... / Assistant: ...". The "Assistant:" portion is CONTEXT ONLY — never store the assistant's actions, confirmations, or statements as facts.

ONLY extract facts that are about the USER as a person AND will still matter weeks from now:
- Stable preferences (likes/dislikes, communication style, food, tools, brands).
- Durable personal details (name, relationships, important recurring dates, home location, profession).
- Health & dietary facts (allergies, restrictions, fitness routines).
- Lasting goals and standing commitments (recurring plans, ongoing projects).

Do NOT extract (transient, or not a durable user fact):
- One-off task requests or commands ("send an email to X", "what's the distance to Orlando", "summarize this", "remind me to call now").
- The status/outcome of a task ("the email was sent", "both tools completed").
- Anything the Assistant said or did.
- Ephemeral conversational mechanics, acknowledgements, or pleasantries.
- A question the user asked that reveals no durable fact about them.

When uncertain whether a fact is durable, DO NOT store it. Prefer precision over recall."""


def _mem0_config() -> dict[str, Any]:
    """Build the Mem0 config dict from app settings.

    pgvector → our own `jarvis` database, isolated by collection_name so
    Mem0's table doesn't collide with our custom tables.
    """
    parsed = urlparse(settings.DATABASE_URL.replace("+asyncpg", ""))

    return {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "dbname": (parsed.path or "/jarvis").lstrip("/"),
                "user": parsed.username or "jarvis_app",
                "password": parsed.password or "",
                "collection_name": "mem0_memories",
                "embedding_model_dims": settings.EMBEDDING_DIMS,   # 1024 for BGE-M3
            },
        },
        "llm": {
            # Goes through LiteLLM so model swapping in .env flows here too.
            # Mem0 uses this LLM to *extract* facts from raw turns via function
            # calling. We have a DEDICATED MEMORY_EXTRACTION_MODEL setting
            # (defaulting to gemini/gemini-2.0-flash) rather than reusing
            # PRIMARY_MODEL, because per-write token burn is 5-9k and Groq
            # free tier's 12k TPM cannot sustain that on top of normal chat.
            # See memory note `project_mem0_extraction_gemini_swap.md` for
            # the decision rationale.
            "provider": "litellm",
            "config": {
                "model": settings.MEMORY_EXTRACTION_MODEL,
                "temperature": 0.0,
                "max_tokens": 1500,
            },
        },
        "embedder": {
            # Direct ollama provider — Mem0 v2 has no litellm embedder.
            # Strip the "ollama/" prefix because the direct provider expects
            # a bare model name like "bge-m3", not LiteLLM-style "ollama/bge-m3".
            "provider": "ollama",
            "config": {
                "model": settings.EMBEDDING_MODEL.removeprefix("ollama/"),
                "ollama_base_url": settings.OLLAMA_BASE_URL,
                "embedding_dims": settings.EMBEDDING_DIMS,
            },
        },
        # Scope auto-save to durable personal facts (4.B.2). Mem0 injects this as
        # the highest-priority block of its extraction prompt.
        "custom_instructions": JARVIS_EXTRACTION_INSTRUCTIONS,
    }


class Mem0Client:
    """Thin async wrapper over Mem0's AsyncMemory."""

    USER_ID = "master"   # single-user system

    def __init__(self) -> None:
        self.client: AsyncMemory = AsyncMemory.from_config(_mem0_config())
        logger.info(
            "mem0_client_init",
            embedder=settings.EMBEDDING_MODEL,
            extraction_llm=settings.MEMORY_EXTRACTION_MODEL,
            vector_store="pgvector(jarvis.mem0_memories)",
        )

    async def add(
        self,
        content: str,
        thread_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        dedup: bool = True,
    ) -> Any:
        """Extract and store memories from a turn or fact statement.

        Dedup-on-write (P5c interim, slows the per-session bloat): if an existing
        memory is near-identical to ``content`` (cosine score >= MEM0_DEDUP_THRESHOLD),
        skip the write entirely. High threshold by default so only true duplicates
        are dropped, never a distinct fact — full semantic consolidation/supersession
        is Turn 26.5. Best-effort: a dedup-check failure never blocks the write."""
        if dedup and settings.MEM0_DEDUP_ENABLED:
            try:
                hits = await self.search(query=content, top_k=1)
                if hits and hits[0].get("score", 0.0) >= settings.MEM0_DEDUP_THRESHOLD:
                    logger.info(
                        "mem0_add_skipped_duplicate",
                        score=round(float(hits[0]["score"]), 4),
                        existing_preview=(hits[0].get("content") or "")[:80],
                        new_preview=content[:80],
                    )
                    return {"results": [], "skipped_duplicate": True}
            except Exception as exc:  # noqa: BLE001 — dedup is best-effort
                logger.warning("mem0_dedup_check_failed", error=str(exc))

        meta = dict(metadata or {})
        if thread_id:
            meta["thread_id"] = thread_id
        return await self.client.add(
            messages=[{"role": "user", "content": content}],
            user_id=self.USER_ID,
            metadata=meta,
        )

    async def search(self, query: str, top_k: int = 10) -> list[dict[str, Any]]:
        """Pure-semantic search over all stored memories — TRUE cosine, best first.

        We deliberately BYPASS Mem0 v2's high-level ``client.search``. That path
        does HYBRID retrieval and fuses the scores:
        ``combined = (semantic + bm25 + entity) / max_possible`` with
        ``max_possible = 2`` whenever BM25 is active — which HALVES and compresses
        the cosine into an indistinguishable ~0.29-0.48 band (a 1.0 match reports
        0.51, a 0.81 match reports 0.42), so recall cannot tell a relevant memory
        from an unrelated one. That fusion is the root cause diagnosed in 4.B.1
        (see project_mem0_search_quality_root) and there is no config switch to
        disable it.

        Instead we embed the query with the SAME ollama embedder and hit the SAME
        pgvector store directly for the raw cosine (``score = 1 - <=> distance``)
        and true semantic ordering (``ORDER BY distance``). Entity scope still
        lives in ``filters`` (Mem0 v2 dropped the top-level scope kwargs). Both
        underlying calls are sync (CPU/IO-bound) → run off the event loop via
        ``to_thread``, mirroring Mem0's own AsyncMemory internals.
        """
        query_vec = await asyncio.to_thread(
            self.client.embedding_model.embed, query, "search"
        )
        rows = await asyncio.to_thread(
            self.client.vector_store.search,
            query,
            query_vec,
            top_k,
            {"user_id": self.USER_ID},
        )
        return [_shape_vector_hit(r) for r in rows]

    async def get_all(self) -> list[dict[str, Any]]:
        """EVERY stored memory — used by corpus-maintenance + inspection jobs.

        Mem0's ``get_all``/``list`` default to ``top_k=20`` and silently truncate
        (a ~1.4k-row corpus came back as 20). A job that scans the corpus MUST see
        all of it or it operates on a 20-row subset, so we pass an explicit high
        limit. ``pgvector.list`` supports only ``LIMIT`` (no ``OFFSET``), so true
        page-looping isn't available at the store layer — the bound + canary is the
        robust option at this scale. If the count ever reaches the bound we log
        loudly rather than truncate silently (raise ``MEM0_GET_ALL_LIMIT``)."""
        limit = settings.MEM0_GET_ALL_LIMIT
        results = await self.client.get_all(
            filters={"user_id": self.USER_ID},
            top_k=limit,
        )
        rows = list(results.get("results") or [])
        if len(rows) >= limit:
            logger.warning(
                "mem0_get_all_hit_limit",
                returned=len(rows),
                limit=limit,
                message="corpus reached MEM0_GET_ALL_LIMIT — raise it so corpus scans aren't truncated",
            )
        return rows

    async def delete(self, memory_id: str) -> Any:
        """Remove a memory (used by the conflict resolver)."""
        return await self.client.delete(memory_id=memory_id)
