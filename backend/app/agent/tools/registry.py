"""
Tool registry with dynamic embedding-based selection.

What this gives us:
  - Tools register a name, an async or sync handler, a one-paragraph
    description, and a Pydantic args schema. We wrap them as LangChain
    StructuredTool objects so LangGraph's `bind_tools()` can hand them to
    any provider's chat model.
  - On startup the orchestrator calls `index_all_tools()` which embeds every
    registered tool's description (BGE-M3 via Ollama, 1024 dims) and upserts
    a row into `tool_embeddings`. Re-embedding only happens for descriptions
    that changed, so restarts are cheap.
  - On every agent turn `select_relevant_tools(query, top_k)` does a cosine
    search over `tool_embeddings` and returns the top-k most relevant tools
    plus all `always_loaded=True` tools. The agent binds only those, which
    keeps the LLM's tool list small even when the codebase has hundreds of
    registered tools.

Tools that should bypass ranking — memory_search, anything that's relevant on
nearly every turn — register with `always_loaded=True`.
"""
import inspect
from collections.abc import Callable
from typing import Any

import litellm
from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import ToolEmbedding
from app.llm.bootstrap import wire_litellm_providers
from app.utils.logging import get_logger

# Push OLLAMA_API_BASE etc. into env so litellm.aembedding can reach the
# Ollama daemon. Idempotent — gateway.py also calls wire_all() which does
# the same thing, so whichever module loads first wins and the second is a no-op.
wire_litellm_providers()

logger = get_logger(__name__)


class _ToolEntry:
    __slots__ = ("name", "tool", "always_loaded", "description", "capability",
                 "approval_essentials")

    def __init__(
        self,
        name: str,
        tool: BaseTool,
        always_loaded: bool,
        description: str,
        capability: str = "",
        approval_essentials: list[dict] | None = None,
    ) -> None:
        self.name = name
        self.tool = tool
        self.always_loaded = always_loaded
        self.description = description
        # Master-facing one-line capability summary for the prompt's "You CAN" recital
        # (distinct from `description`, which is LLM tool-ROUTING text). Empty = internal
        # tool, excluded from the recital. The registry is the source of truth → the recital
        # can't drift out of sync with the actual tools.
        self.capability = capability
        # ESSENTIALS REGISTRY (A2 s1b — a recorded roadmap standard): the payload fields an
        # APPROVAL MESSAGE for this tool must NAME before the deterministic floor may stand
        # down — each {"field": <tool_args key>, "kind": "recipient"|"text"|"time"}. EVERY
        # APPROVE-tier tool declares its essentials at registration; an undeclared tool falls
        # back to its humanized name AND logs a warning (the weak path stays visible, never
        # the quiet norm — the reviewer's (b)-lens flags undeclared APPROVE tools).
        self.approval_essentials = approval_essentials


class ToolRegistry:
    """Singleton — holds every registered tool plus its embedding metadata."""

    def __init__(self) -> None:
        self._entries: dict[str, _ToolEntry] = {}

    # ------------------------------------------------------------------
    # Registration + execution
    # ------------------------------------------------------------------
    def register(
        self,
        name: str,
        handler: Callable[..., Any],
        description: str,
        args_schema: type[BaseModel] | None = None,
        always_loaded: bool = False,
        capability: str = "",
        approval_essentials: list[dict] | None = None,
    ) -> None:
        """Register a tool. `handler` may be sync or async — StructuredTool
        supports both via `func=` vs `coroutine=`.

        `capability` is an OPTIONAL master-facing one-liner for the system prompt's "You CAN"
        recital (see build_capabilities). Omit it for internal/signal tools (deliver_briefing)
        so they don't appear as a master-visible capability."""
        if inspect.iscoroutinefunction(handler):
            tool = StructuredTool.from_function(
                coroutine=handler,
                name=name,
                description=description,
                args_schema=args_schema,
            )
        else:
            tool = StructuredTool.from_function(
                func=handler,
                name=name,
                description=description,
                args_schema=args_schema,
            )

        self._entries[name] = _ToolEntry(
            name=name,
            tool=tool,
            always_loaded=always_loaded,
            description=description,
            capability=capability,
            approval_essentials=approval_essentials,
        )
        logger.info("tool_registered", name=name, always_loaded=always_loaded)

    def approval_essentials(self, tool_name: str) -> list[dict] | None:
        """The tool's declared approval-message essentials (the Essentials-registry standard),
        or None for an undeclared tool (callers fall back to the humanized name + WARN)."""
        entry = self._entries.get(tool_name)
        return entry.approval_essentials if entry else None

    def capabilities(self) -> list[str]:
        """The master-facing capability one-liners of every registered tool that declared one,
        in registration order — the source for the prompt's "You CAN" recital. Internal tools
        (no `capability`) are excluded. Deterministic (registration order is fixed) → the
        recital is a stable prefix, cache-friendly."""
        return [e.capability for e in self._entries.values() if e.capability]

    async def execute(self, name: str, args: dict[str, Any]) -> str:
        """Run a registered tool by name. Used by tool_executor_node."""
        entry = self._entries.get(name)
        if entry is None:
            raise ValueError(f"Unknown tool: {name!r}")
        # ainvoke handles both sync + async tools uniformly.
        result = await entry.tool.ainvoke(args)
        return str(result)

    # ------------------------------------------------------------------
    # Introspection helpers (used by tests + dashboard)
    # ------------------------------------------------------------------
    def all_names(self) -> list[str]:
        return list(self._entries.keys())

    def get_tool_object(self, name: str) -> BaseTool | None:
        entry = self._entries.get(name)
        return entry.tool if entry else None

    def is_registered(self, name: str) -> bool:
        return name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Embedding-based dynamic selection
    # ------------------------------------------------------------------
    async def index_all_tools(self) -> None:
        """Embed every registered tool's description and upsert into
        `tool_embeddings`. Idempotent — only re-embeds rows whose description
        actually changed since last run, so restarts skip the Ollama work
        when nothing has moved."""
        if not self._entries:
            logger.warning("index_all_tools_called_with_empty_registry")
            return

        async with async_session() as session:
            for entry in self._entries.values():
                existing = await session.execute(
                    select(ToolEmbedding).where(ToolEmbedding.tool_name == entry.name)
                )
                row = existing.scalar_one_or_none()

                # Skip re-embedding if description unchanged.
                if row is not None and row.description == entry.description:
                    if row.is_always_loaded != entry.always_loaded:
                        row.is_always_loaded = entry.always_loaded
                    if row.embedding_model != settings.EMBEDDING_MODEL:
                        # Embedding model changed — force re-embed even though
                        # the description didn't, so we don't mix dimensions.
                        row.embedding = await _embed_text(entry.description)
                        row.embedding_model = settings.EMBEDDING_MODEL
                    continue

                emb = await _embed_text(entry.description)
                if row is None:
                    session.add(
                        ToolEmbedding(
                            tool_name=entry.name,
                            description=entry.description,
                            embedding=emb,
                            embedding_model=settings.EMBEDDING_MODEL,
                            is_always_loaded=entry.always_loaded,
                        )
                    )
                else:
                    row.description = entry.description
                    row.embedding = emb
                    row.embedding_model = settings.EMBEDDING_MODEL
                    row.is_always_loaded = entry.always_loaded

            await session.commit()
            logger.info("tool_embeddings_indexed", count=len(self._entries))

    async def select_relevant_tools(
        self,
        query: str,
        top_k: int = 15,
    ) -> list[BaseTool]:
        """Return the top-k tools by cosine similarity against `query`,
        plus every always-loaded tool (which bypass the ranking)."""
        always = [e.tool for e in self._entries.values() if e.always_loaded]

        # If the registry is empty (or only has always-loaded tools), the
        # cosine search would return nothing — short-circuit.
        rankable = [e for e in self._entries.values() if not e.always_loaded]
        if not rankable:
            logger.debug("dynamic_tools_selected", query_len=len(query), only_always=True, count=len(always))
            return always

        # Fast-path: when there are no more rankable tools than top_k, the cosine
        # search would return ALL of them anyway — so the query embed + pgvector
        # search are pure latency (~210ms/turn). Skip them and return everything;
        # tool ORDER doesn't affect whether the model calls a tool.
        if len(rankable) <= top_k:
            seen = {t.name for t in always}
            merged = list(always)
            for e in rankable:
                if e.tool.name not in seen:
                    merged.append(e.tool)
                    seen.add(e.tool.name)
            logger.debug(
                "dynamic_tools_selected", query_len=len(query),
                fast_path=True, always=len(always), rankable=len(rankable), total=len(merged),
            )
            return merged

        q_emb = await _embed_text(query)
        async with async_session() as session:
            # pgvector cosine distance operator (smaller = more similar).
            stmt = (
                select(ToolEmbedding.tool_name)
                .where(ToolEmbedding.is_always_loaded == False)  # noqa: E712 — SQL needs literal False
                .order_by(ToolEmbedding.embedding.cosine_distance(q_emb))
                .limit(top_k)
            )
            result = await session.execute(stmt)
            ranked_names = [r[0] for r in result.all()]

        ranked_tools = [
            self._entries[n].tool
            for n in ranked_names
            if n in self._entries
        ]

        # Always-loaded first, then ranked, dedup by name.
        seen = {t.name for t in always}
        merged = list(always)
        for t in ranked_tools:
            if t.name not in seen:
                merged.append(t)
                seen.add(t.name)

        logger.debug(
            "dynamic_tools_selected",
            query_len=len(query),
            top_k=top_k,
            always=len(always),
            ranked=len(ranked_tools),
            total=len(merged),
        )
        return merged


async def _embed_text(text: str) -> list[float]:
    """Embed a string via LiteLLM (which routes to Ollama for `ollama/bge-m3`).

    Defensive on the response shape — LiteLLM versions differ on whether
    `response.data[0]` is a dict or an object with `.embedding`.
    """
    response = await litellm.aembedding(
        model=settings.EMBEDDING_MODEL,
        input=[text],
    )
    item = response.data[0]
    if hasattr(item, "embedding"):
        return list(item.embedding)
    return list(item["embedding"])


# Module-level singleton — every other module imports this.
tool_registry = ToolRegistry()
