"""
Tool registry — STUB.

This is a minimum-viable shim so `app.agent.nodes` can import and call
`tool_registry.select_relevant_tools(...)` and `tool_registry.execute(...)`
without crashing while the full registry (Task 1.11 / Turn 10) is still
to be written.

Behavior:
  - select_relevant_tools(...) returns [] — no tools are bound to the LLM,
    so the agent always replies in plain text. This lets us smoke-test the
    graph + checkpointer path without needing real tool implementations.
  - execute(...) raises NotImplementedError. If something tries to call it
    in this state we want a loud failure, not silent no-op.

Turn 10 replaces this entire file with the real registry: Pydantic-validated
tool registration, BGE-M3 embedded tool descriptions stored in
tool_embeddings, top-k cosine search on every turn, always-loaded bypass.
"""
from typing import Any

from app.utils.logging import get_logger

logger = get_logger(__name__)


class _ToolRegistryStub:
    """Returns no tools; raises on execution. Real impl arrives in Turn 10."""

    async def select_relevant_tools(self, query: str, top_k: int = 15) -> list:  # noqa: ARG002
        logger.debug("tool_registry_stub_select", query_len=len(query), top_k=top_k)
        return []

    async def execute(self, tool_name: str, tool_args: dict[str, Any]) -> Any:  # noqa: ARG002
        raise NotImplementedError(
            f"tool_registry stub cannot execute {tool_name!r} — "
            "real registry implementation arrives in Turn 10."
        )


tool_registry = _ToolRegistryStub()
