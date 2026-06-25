"""
Tool registration entry point.

`register_all_tools()` is called once from FastAPI's lifespan startup hook
(in `app.main`). It imports each tool module and runs its module-level
`register()` function, which lands a tool in the singleton `tool_registry`.

After this runs, `tool_registry.index_all_tools()` embeds every tool's
description into pgvector so `select_relevant_tools()` can do top-k cosine
search per turn.

Adding a new tool:
  1. Write `app/agent/tools/<your_tool>.py` following the
     `builtin_memory.py` pattern: Pydantic args class, async handler,
     `register()` function calling `tool_registry.register(...)`.
  2. Import + call its `register()` here.
  3. (Optional) classify it in `app.agent.safety.TOOL_SAFETY_MAP`. Anything
     not in the map defaults to APPROVE — fail-safe but noisy.
"""
from app.agent.tools.registry import tool_registry  # re-exported for convenience
from app.utils.logging import get_logger

__all__ = ["tool_registry", "register_all_tools"]

logger = get_logger(__name__)


def register_all_tools() -> None:
    """Import each tool module and call its register(). Order doesn't matter
    because tools are independent."""
    from app.agent.tools.builtin_memory import register as register_memory
    register_memory()

    from app.agent.tools.calendar_tool import register as register_calendar
    register_calendar()

    from app.agent.tools.email_send import register as register_email_send
    register_email_send()

    from app.agent.tools.email_history import register as register_email_history
    register_email_history()

    from app.agent.tools.document_search import register as register_document_search
    register_document_search()

    from app.agent.tools.actionable_tool import register as register_actionable
    register_actionable()

    from app.agent.tools.readiness_tool import register as register_readiness
    register_readiness()

    # Phase 2 / Phase 3 / Phase 4 tool registrations land below as each
    # tool module ships. Keep them commented until their underlying module
    # exists, so this function never raises ImportError on a fresh build.
    #
    # from app.agent.tools.browser_tool import register as register_browser
    # register_browser()
    # from app.agent.tools.search_tool import register as register_search
    # register_search()
    # from app.agent.tools.crawl_tool import register as register_crawl
    # register_crawl()
    # from app.agent.tools.telegram_tool import register as register_telegram
    # register_telegram()
    # from app.agent.tools.whatsapp_tool import register as register_whatsapp
    # register_whatsapp()
    # from app.agent.tools.booking_tool import register as register_booking
    # register_booking()

    logger.info("tools_registered", count=len(tool_registry))
