"""Anthropic Contextual Retrieval — per-chunk context summaries.

Each chunk gets a 50-100 token LLM-generated preface that situates it
within the full document (e.g., "This chunk is from Section 3 of the
Q3 2024 earnings report and discusses cloud-segment revenue."). Embedding
the chunk PLUS this preface — rather than the raw chunk alone — gives a
measurable retrieval precision lift on real-world RAG tasks (Anthropic's
published ~5-15% on BEIR-style benchmarks).

Public API: one batch-friendly async function — concurrent dispatch via
``asyncio.gather`` + a bounded ``Semaphore`` (``CONTEXTUALIZE_CONCURRENCY``),
routed to the paid Gemini ``contextualizer`` slot OFF the agent's Groq. The
batch interface meant adding this didn't ripple into callers (plan Task 2.14b).

Failure model: never raises at batch level. Per-chunk failures degrade to
empty strings in the output, with distinct structlog events for diagnosis:

  - ``contextualize_failed``         — LLM call raised (network, rate limit,
                                       auth, malformed response shape)
  - ``contextualize_empty_response`` — LLM returned empty content (prompt
                                       rejection, content filter, post-
                                       processed garbage)
  - (empty input ``chunk.content``)  — silent, deliberate skip

Downstream callers (Turn 19.2 ``ingestion.py``) treat empty summary as
"fall back to raw-chunk embedding without contextual preface" — feature-
degraded but not feature-broken.
"""
from __future__ import annotations

import asyncio

from app.config import settings
from app.documents.chunker import Chunk
from app.llm.gateway import llm_gateway
from app.utils.logging import get_logger

logger = get_logger(__name__)


CONTEXT_PROMPT = """<document>
{full_doc_excerpt}
</document>

Here is the chunk we want to situate within the whole document:
<chunk>
{chunk_text}
</chunk>

Please give a short, succinct context (50-100 tokens) to situate this chunk within
the overall document for the purposes of improving search retrieval of the chunk.
Answer ONLY with the succinct context and nothing else.
"""


async def contextualize_chunks(
    chunks: list[Chunk],
    full_doc_excerpt: str,
) -> list[str]:
    """Generate one context summary per chunk, in input order.

    Returns ``list[str]`` with length == ``len(chunks)``. Empty input → ``[]``
    (no LLM calls made). Never raises at batch level; per-chunk failures
    degrade to ``""`` in the output position with distinct log signals
    (``contextualize_failed`` for exceptions, ``contextualize_empty_response``
    for empty content).

    **Caller is responsible for sizing ``full_doc_excerpt`` appropriately.**
    This function takes what it's given and does not truncate. The caller
    knows the document size and the prompt-budget tradeoff (typical excerpt:
    first 8000 chars of the document); the contextualizer's contract stays
    clean — "I take what I'm given." If memory becomes a concern on very
    large documents, the fix is at the caller, not here.
    """
    if not chunks:
        return []

    # Concurrent dispatch with a bounded semaphore — the batch interface was
    # built for exactly this. Routed to the `contextualizer` slot (paid Gemini),
    # off the agent's Groq, so a 74-chunk doc doesn't saturate Groq and starve
    # chat. asyncio.gather preserves input order. Per-call timeout + per-chunk
    # failure → "" (caller falls back to raw-chunk embedding).
    sem = asyncio.Semaphore(settings.CONTEXTUALIZE_CONCURRENCY)

    async def _one(chunk: Chunk) -> str:
        chunk_text = chunk.content.strip()
        if not chunk_text:
            return ""
        prompt = CONTEXT_PROMPT.format(
            full_doc_excerpt=full_doc_excerpt,
            chunk_text=chunk_text,
        )
        async with sem:
            try:
                response = await asyncio.wait_for(
                    llm_gateway.complete(
                        messages=[{"role": "user", "content": prompt}],
                        task_type="summarization",
                        force_model="contextualizer",
                        temperature=0.0,
                    ),
                    timeout=settings.CONTEXTUALIZE_TIMEOUT_S,
                )
            except asyncio.TimeoutError:
                logger.warning("contextualize_timeout", chunk_index=chunk.chunk_index)
                return ""
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "contextualize_failed",
                    chunk_index=chunk.chunk_index,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return ""
        content = (response["choices"][0]["message"].get("content") or "").strip()
        if not content:
            logger.warning(
                "contextualize_empty_response",
                chunk_index=chunk.chunk_index,
                response_snapshot=str(response)[:500],
            )
        return content

    return list(await asyncio.gather(*(_one(c) for c in chunks)))
