"""
LiteLLM provider wiring — idempotent.

Both `app.llm.gateway` and `app.agent.tools.registry` call directly into
LiteLLM (one for chat completions, the other for embeddings). LiteLLM reads
provider creds and base URLs from process env vars at call time, so those
have to be set before either module fires its first request.

Putting the wiring in this dedicated module means:
  - Whichever LiteLLM-using module loads first triggers the wiring once.
  - Subsequent imports skip the work via the `_wired` guard.
  - The Langfuse callback is wired in the same place so we don't end up
    with traces appearing for chat calls but not for embeddings (or vice
    versa).

If you add another module that calls litellm directly, import this one and
call `wire_litellm_providers()` at its top.
"""
import os

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


_wired = False


def wire_litellm_providers() -> None:
    """Push provider keys + base URLs into env vars LiteLLM expects.

    Idempotent — safe to call from every LiteLLM-using module's top level.
    """
    global _wired
    if _wired:
        return

    if settings.ANTHROPIC_API_KEY:
        os.environ["ANTHROPIC_API_KEY"] = settings.ANTHROPIC_API_KEY
    if settings.OPENAI_API_KEY:
        os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if settings.GROQ_API_KEY:
        os.environ["GROQ_API_KEY"] = settings.GROQ_API_KEY
    if settings.GOOGLE_GEMINI_API_KEY:
        os.environ["GEMINI_API_KEY"] = settings.GOOGLE_GEMINI_API_KEY

    # Ollama — needs OLLAMA_API_BASE to find the daemon. Inside the docker
    # network the host's daemon is reached via host.docker.internal; the
    # backend service in docker-compose sets OLLAMA_BASE_URL accordingly.
    if settings.OLLAMA_BASE_URL:
        os.environ["OLLAMA_API_BASE"] = settings.OLLAMA_BASE_URL

    _wired = True
    logger.debug("litellm_providers_wired")


def wire_langfuse_callback() -> None:
    """Tell LiteLLM to trace every call to Langfuse. Idempotent.

    Lives here (not in gateway) for the same reason as provider wiring —
    we want every LiteLLM call traced, not just the ones the chat gateway
    made.
    """
    if not (settings.LANGFUSE_ENABLED and settings.LANGFUSE_PUBLIC_KEY):
        return

    import litellm  # local — keeps cold-start fast for non-llm scripts

    # LiteLLM's success/failure callback lists are mutated in place.
    if "langfuse" not in (litellm.success_callback or []):
        litellm.success_callback = [*(litellm.success_callback or []), "langfuse"]
    if "langfuse" not in (litellm.failure_callback or []):
        litellm.failure_callback = [*(litellm.failure_callback or []), "langfuse"]

    os.environ["LANGFUSE_PUBLIC_KEY"] = settings.LANGFUSE_PUBLIC_KEY
    os.environ["LANGFUSE_SECRET_KEY"] = settings.LANGFUSE_SECRET_KEY
    os.environ["LANGFUSE_HOST"] = settings.LANGFUSE_HOST


def wire_all() -> None:
    """Convenience — call both at once."""
    wire_litellm_providers()
    wire_langfuse_callback()
