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
from typing import Any
from urllib.parse import urlparse

from mem0 import AsyncMemory

from app.config import settings
from app.llm.bootstrap import wire_litellm_providers
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Mem0 v2 routes its extraction LLM through LiteLLM, which reads provider keys
# from os.environ at call time. Without this call, GEMINI_API_KEY (mapped from
# settings.GOOGLE_GEMINI_API_KEY) never makes it into the environment because
# Mem0 import path doesn't go through gateway.py. Idempotent — safe to call
# from every LiteLLM-using module.
wire_litellm_providers()


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
        """Semantic search over all stored memories.

        Mem0 v2 dropped top-level scope kwargs on search/get_all — entity scope
        (`user_id`, `agent_id`, `run_id`) now lives in the `filters` dict. The
        old call signature raises a hard ValueError.
        """
        results = await self.client.search(
            query=query,
            top_k=top_k,
            filters={"user_id": self.USER_ID},
        )
        return [
            {
                "id": m.get("id"),
                "content": m.get("memory"),
                "score": m.get("score", 0.0),
                "metadata": m.get("metadata") or {},
            }
            for m in (results.get("results") or [])
        ]

    async def get_all(self) -> list[dict[str, Any]]:
        """All memories — used by consolidation + conflict-detection jobs."""
        results = await self.client.get_all(filters={"user_id": self.USER_ID})
        return list(results.get("results") or [])

    async def delete(self, memory_id: str) -> Any:
        """Remove a memory (used by the conflict resolver)."""
        return await self.client.delete(memory_id=memory_id)
