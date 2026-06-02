"""8am daily morning brief — email digest + (future) news section.

The plan's Task 2.8 version also imports a news_briefing module from Phase 3.
Until that module exists (Turn 25), the morning brief is email-digest-only.
Wrapped in try/except so once news_briefing lands, it'll be picked up
without a code edit here (graceful import-time degradation).
"""
import asyncio

from app.email.digest import build_and_clear_digest
from app.messaging.failure_alerter import PRIMARY_ALERT_CHANNEL
from app.messaging.channel_registry import channel_registry
from app.scheduler.task_helpers import reset_async_state_for_task
from app.scheduler.task_wrapper import critical_task
from app.utils.logging import get_logger

logger = get_logger(__name__)


@critical_task(name="app.scheduler.tasks.morning_brief.send_morning_brief")
def send_morning_brief():
    """Wrapped in @critical_task — alerts master after 3 failed runs."""
    asyncio.run(_send())


async def _send():
    await reset_async_state_for_task()

    parts = []

    digest = await build_and_clear_digest()
    parts.append(digest if digest else "📬 *Email Digest:* No new FYI emails since yesterday.")

    # News section is Phase 3 (Turn 25). Import is lazy + guarded so this
    # task starts producing news briefs the moment news_briefing.build_news_brief
    # exists, without an edit here.
    try:
        from app.scheduler.tasks.news_briefing import build_news_brief  # noqa: F401
        news = await build_news_brief()
        if news:
            parts.append(news)
    except ImportError:
        # Phase 3 module not landed yet — proceed with email-digest-only brief.
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("morning_brief_news_failed", error=str(exc))

    full_brief = "\n\n---\n\n".join(parts)

    ch = channel_registry.get(PRIMARY_ALERT_CHANNEL)
    await ch.send_alert(f"☀️ *Good Morning!*\n\n{full_brief}")
    logger.info("morning_brief_sent", parts_count=len(parts))
