"""
Langfuse hooks.

Two integration points exist between Jarvis and Langfuse:

1. LiteLLM auto-callback — every LLM completion that goes through the gateway
   gets traced automatically. Wired in `app.llm.bootstrap.wire_langfuse_callback`
   via `litellm.success_callback = ["langfuse"]`. No code in this file needed
   for that path; LiteLLM imports `langfuse` itself.

2. LangGraph callback handler — when the agent graph runs, its node steps
   (memory_load, agent, tool_executor, persist) become discrete spans inside
   the SAME trace that the LiteLLM callback emits, giving end-to-end
   observability of "the LLM said X because the prompt said Y because the
   memory_load returned Z". This needs the full `langchain` package
   alongside `langfuse[langchain]`'s CallbackHandler.

   Both pieces install via:
       pip install langchain langfuse[langchain]

   `langfuse_callback_handler(thread_id)` returns a fresh handler per call.
   The handler is stateless across `run_turn` / `resume_turn` invocations —
   each invocation produces its own trace, all grouped under the same
   `session_id` (= thread_id) for the Langfuse Sessions view.

   See memory note `project_langfuse_langchain_callback.md` for more detail.

`langfuse_client()` is the direct-trace API surface — useful for non-graph
custom spans (Celery jobs, scheduled tasks). Singleton; safe to import early.
"""
from typing import Any

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_client: Any | None = None


def langfuse_client() -> Any | None:
    """Return the singleton Langfuse client, or None if observability is disabled."""
    global _client
    if not settings.LANGFUSE_ENABLED or not settings.LANGFUSE_PUBLIC_KEY:
        return None

    if _client is None:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
        logger.info("langfuse_client_init", host=settings.LANGFUSE_HOST)

    return _client


def langfuse_callback_handler(thread_id: str | None = None) -> Any | None:
    """Build a CallbackHandler for one graph invocation.

    Returns None when observability is disabled or when the langfuse v2 SDK
    callback path is unavailable (e.g. an SDK upgrade removed it). Callers
    should always tolerate None.

    The handler is fresh per call on purpose:
      - Each `run_turn` produces its own trace (one root span "memory_load → agent → ...").
      - Each `resume_turn` produces its own trace too (one root span starting at
        the resumed node). Langfuse groups both traces under the same
        `session_id` (thread_id) in its Sessions view.
      - The handler is NOT shared across calls. It holds no state we want to
        accumulate — each new graph invocation should start fresh.
    """
    if not settings.LANGFUSE_ENABLED or not settings.LANGFUSE_PUBLIC_KEY:
        return None

    # Lazy import — keep cold-start fast for scripts that don't need tracing,
    # and let the function still return None if the import path goes away
    # (langfuse v3+ moved the symbol; we're pinned to v2.x but defensive
    # coding here means an accidental upgrade returns None instead of crashing
    # the whole agent path).
    try:
        from langfuse.callback import CallbackHandler  # langfuse v2 path
    except ImportError as exc:
        logger.warning(
            "langfuse_callback_unavailable",
            error=str(exc),
            hint="install langchain + check langfuse SDK version",
        )
        return None

    return CallbackHandler(
        public_key=settings.LANGFUSE_PUBLIC_KEY,
        secret_key=settings.LANGFUSE_SECRET_KEY,
        host=settings.LANGFUSE_HOST,
        session_id=thread_id,
        user_id="master",
    )
