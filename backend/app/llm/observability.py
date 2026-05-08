"""
Langfuse hooks.

Two integration points exist between Jarvis and Langfuse:

1. LiteLLM auto-callback — every LLM completion that goes through the gateway
   gets traced automatically. Wired in `gateway.py` via
   `litellm.success_callback = ["langfuse"]`. No code in this file needed for
   that path; LiteLLM imports `langfuse` itself.

2. LangGraph callback handler — when the agent graph runs, its steps (memory
   load, tool calls, LLM nodes) become spans inside the same trace. This needs
   `langfuse.langchain.CallbackHandler`, which Langfuse v4 ships behind the
   `langfuse[langchain]` extra. We don't install `langchain` in this commit
   because the agent graph isn't built yet; the handler returns None for now
   and gets a real implementation when the graph wiring lands.

`langfuse_client()` is the direct-trace API surface — useful for non-LLM
custom spans (Celery jobs, scheduled tasks). Singleton; safe to import early.
"""
from typing import Any

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_client: Any | None = None


def langfuse_client() -> Any | None:
    """Return the singleton Langfuse client, or None if observability is disabled.

    Typed `Any` because the Langfuse class moved between v3 and v4 SDKs and we
    want this signature stable across upgrades. Callers should treat it as
    duck-typed.
    """
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
    """LangGraph CallbackHandler factory — currently a STUB.

    Returns None until the agent graph commit lands `langchain` in pyproject.toml
    and switches this body to:

        from langfuse.langchain import CallbackHandler
        return CallbackHandler(session_id=thread_id, user_id="master")

    For now graph wiring code that calls this gracefully degrades to no
    LangGraph-level tracing (LLM-level tracing via the LiteLLM callback still works).
    """
    if not settings.LANGFUSE_ENABLED or not settings.LANGFUSE_PUBLIC_KEY:
        return None

    # langchain not installed yet — see module docstring.
    logger.debug("langfuse_callback_handler_stub", thread_id=thread_id)
    return None
