"""document_search — agent-facing RAG tool over ingested documents.

Wraps :func:`app.documents.search.search_documents` (hybrid vector+BM25 → RRF →
rerank → threshold) and renders the kept passages as a citation-prefixed string
the agent can answer from. ``search_documents`` owns retrieval; this tool owns
*presentation*: it builds the ``[file, p.page, §section]`` citation from each
chunk's ``meta`` and bounds the rendered content so the whole result stays under
the tool-result archival cap (``settings.TOOL_RESULT_MAX_CHARS``) — otherwise the
sanitizer truncates+archives the tail and the agent loses passages it can't yet
fetch back (the ``project_archived_tool_result_no_fetch_path.md`` gap; full-chunk
recall is the Phase-3 lift).

Citation guidance lives in the tool *description*, not SAFETY_DOCTRINE — per the
locked decision (``feedback_tool_specific_guidance_in_descriptions.md``), keeping
global doctrine narrow as the tool surface grows; future web_search / news tools
carry their own citation patterns in their own descriptions.

Safety classification: SAFE (read-only retrieval, no side effects). Set in
``app.agent.safety.TOOL_SAFETY_MAP``.
"""
from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.config import settings
from app.documents.search import search_documents
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Slack subtracted from the cap before dividing it into per-passage budgets, to
# absorb the inter-line newlines and per-excerpt ellipsis so the rendered result
# stays strictly under TOOL_RESULT_MAX_CHARS for any top_k in 1-10.
_RENDER_MARGIN = 32

_WHITESPACE = re.compile(r"\s+")


class DocumentSearchArgs(BaseModel):
    """Plain-types-only schema (no Optional/Literal) so open-weights models that
    choke on ``anyOf:[..., null]`` JSON Schema still emit structured tool_calls —
    see ``project_open_weights_tool_schema_and_conversation_poisoning.md``."""

    query: str = Field(
        ...,
        description="What to look for in the master's documents — a question or topic.",
    )
    top_k: int = Field(
        default=settings.RAG_TOP_K,
        description=f"Max passages to return (1-10, default {settings.RAG_TOP_K}).",
    )


async def document_search(query: str, top_k: int = settings.RAG_TOP_K) -> str:
    """Retrieve the most relevant document passages for ``query``, citation-formatted."""
    top_k = max(1, min(int(top_k), 10))

    results = await search_documents(query=query, top_k=top_k)
    if not results:
        return (
            f"No relevant passages found in the master's documents for: {query!r}. "
            "Nothing was ingested that matches, or matches fell below the relevance "
            "threshold."
        )
    return _render_results(results)


def _render_results(results: list[dict[str, Any]]) -> str:
    """Render kept passages as a citation-prefixed string, bounded strictly under
    ``settings.TOOL_RESULT_MAX_CHARS`` for any ``1 <= len(results) <= 10``.

    Pure function (no I/O) so the no-archive invariant is unit-testable. The
    per-result block budget is derived from the cap and the ACTUAL result count,
    not a constant sized for one top_k — above the cap the sanitizer
    truncates+archives the tail and the agent can't fetch archived passages back
    (the deferred archived-fetch gap), so the bound has to actually hold.
    """
    n = len(results)
    header = f"Found {n} relevant passage(s):"
    per_block = max(0, settings.TOOL_RESULT_MAX_CHARS - len(header) - _RENDER_MARGIN) // n

    blocks = [header, ""]
    for r in results:
        citation = _format_citation(r.get("filename", "(unknown)"), r.get("meta") or {})
        score = r.get("rerank_score")
        score_str = f" (relevance {score:.2f})" if score is not None else ""
        cite_line = f"{citation}{score_str}"
        # Citation is load-bearing provenance — keep it whole; the excerpt takes
        # whatever the block budget leaves after the line's two newlines.
        excerpt_budget = max(0, per_block - len(cite_line) - 2)
        blocks.append(cite_line)
        blocks.append(_excerpt(r.get("content", ""), excerpt_budget))
        blocks.append("")

    return "\n".join(blocks).rstrip()


def _format_citation(filename: str, meta: dict[str, Any]) -> str:
    """Build ``[source_file, p.<page>, §<section>]`` from chunk meta.

    Omits the page component for page-less formats (txt/md/docx/xlsx) and the
    section component when no heading was detected — never emits empty fields.
    """
    source = meta.get("source_file") or filename
    parts = [source]

    page_start = meta.get("page_start")
    page_end = meta.get("page_end")
    if page_start is not None:
        if page_end is not None and page_end != page_start:
            parts.append(f"p.{page_start}-{page_end}")
        else:
            parts.append(f"p.{page_start}")

    heading = meta.get("section_heading")
    if heading:
        parts.append(f"§{heading}")

    return "[" + ", ".join(parts) + "]"


def _excerpt(content: str, budget: int) -> str:
    """Whitespace-collapsed content excerpt, ``budget`` chars INCLUDING the
    trailing ellipsis, so the result never exceeds the per-block budget."""
    if budget <= 0:
        return ""
    collapsed = _WHITESPACE.sub(" ", content).strip()
    if len(collapsed) <= budget:
        return collapsed
    return collapsed[: budget - 1].rstrip() + "…"


def register() -> None:
    tool_registry.register(
        name="document_search",
        handler=document_search,
        description=(
            "Search the master's ingested documents (PDFs, Word/Excel files, "
            "notes, markdown) for passages relevant to a question — the RAG "
            "knowledge base. Use when the answer lives in an uploaded document: "
            "'what does the contract say about termination', 'what was Q3 revenue "
            "per the report', 'summarize the onboarding policy'. "
            "Does NOT search email (use email_history_search) or conversation "
            "memory (use memory_search). "
            "Each passage is prefixed with a citation like [report.pdf, p.3, "
            "§Results]. When you use a passage to answer, cite it with that exact "
            "bracket so the master can verify the source; never state a document "
            "fact without its citation. Answer ONLY from the returned passages — "
            "if they don't contain the answer, say the documents don't cover it; "
            "do NOT fall back to your own general knowledge for a question about "
            "the master's documents."
        ),
        args_schema=DocumentSearchArgs,
    )
