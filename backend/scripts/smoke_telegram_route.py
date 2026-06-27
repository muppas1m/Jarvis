"""Turn 11b — deterministic Telegram channel smoke.

Bypasses the live polling glue (which needs you to message the bot from
your phone). Constructs a NormalizedMessage as if Telegram had just
delivered it, calls route_inbound, and asserts:

  - The agent runs to completion.
  - TelegramChannel.send_reply was called with non-empty text addressed
    to the master's chat_id.
  - A ConversationAnalytics row was upserted for the thread.

The live round-trip ("open Telegram, send hi") is a separate manual smoke
documented in the Turn 11b wrap-up.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/smoke_telegram_route.py"
"""

import asyncio
import sys
import uuid
from unittest.mock import patch

import _smoke_isolation  # noqa: F401  — side effect: bind to the test DB before any app import
from sqlalchemy import select

from app.agent.graph import close_checkpointer, init_checkpointer
from app.agent.tools import register_all_tools
from app.agent.tools.registry import tool_registry
from app.config import settings
from app.db.engine import async_session, close_db
from app.db.models import ConversationAnalytics
from app.messaging.channel import NormalizedMessage
from app.messaging.channel_registry import channel_registry
from app.messaging.channels.telegram import get_telegram_channel
from app.messaging.router import route_inbound


async def main() -> int:
    if not settings.TELEGRAM_BOT_TOKEN:
        print("FAIL: TELEGRAM_BOT_TOKEN not set — can't construct TelegramChannel")
        return 1
    if not settings.TELEGRAM_MASTER_CHAT_ID:
        print("FAIL: TELEGRAM_MASTER_CHAT_ID not set — channel needs to know who's master")
        return 1

    print("=== bring up agent stack ===")
    await init_checkpointer()
    register_all_tools()
    await tool_registry.index_all_tools()

    # Register the real Telegram channel — but patch send_reply / send_alert
    # / show_typing so we don't actually call the Bot API. The smoke is
    # deterministic and offline-friendly.
    tg = get_telegram_channel()
    channel_registry.register(tg)
    print(f"  ✓ TelegramChannel registered (platform={tg.platform})")

    sent_replies: list[tuple[str, str]] = []   # (chat_id, text)
    sent_alerts: list[str] = []

    async def fake_send_reply(msg, text, parse_mode="Markdown"):
        sent_replies.append((msg.channel_user_id, text))

    async def fake_send_alert(text):
        sent_alerts.append(text)

    async def fake_show_typing(msg):
        return None

    print("=== route a fake inbound message ===")
    chat_id = settings.TELEGRAM_MASTER_CHAT_ID
    thread_id_unique = f"telegram:{chat_id}-smoke-{uuid.uuid4().hex[:6]}"
    msg = NormalizedMessage(
        platform="telegram",
        channel_user_id=chat_id,
        text="Reply with exactly the three words: hello world friend.",
        thread_id=thread_id_unique,
        is_master=True,
        reply_to_message_id="42",
        raw={"smoke": True},
    )

    with patch.object(tg, "send_reply", side_effect=fake_send_reply), \
         patch.object(tg, "send_alert", side_effect=fake_send_alert), \
         patch.object(tg, "show_typing", side_effect=fake_show_typing):
        await route_inbound(msg)

    print(f"  send_reply calls: {len(sent_replies)}")
    for chat, text in sent_replies:
        print(f"    chat_id={chat!r}  text={text[:120]!r}")

    failures: list[str] = []
    if len(sent_replies) != 1:
        failures.append(f"expected 1 send_reply, got {len(sent_replies)}")
    elif sent_replies[0][0] != chat_id:
        failures.append(
            f"send_reply chat_id was {sent_replies[0][0]!r}, expected master {chat_id!r}"
        )
    elif not sent_replies[0][1].strip():
        failures.append("send_reply text was empty")

    print("=== verify ConversationAnalytics row ===")
    async with async_session() as session:
        result = await session.execute(
            select(ConversationAnalytics).where(
                ConversationAnalytics.thread_id == thread_id_unique
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        failures.append("no ConversationAnalytics row for this thread")
    else:
        print(f"  thread_id={row.thread_id!r}")
        print(f"  platform={row.platform!r}")
        print(f"  message_count={row.message_count}")
        print(f"  last_message_at={row.last_message_at}")
        if row.platform != "telegram":
            failures.append(f"analytics platform was {row.platform!r}, expected 'telegram'")

    print("=== route a non-master message — should be politely refused ===")
    sent_replies.clear()
    non_master_msg = NormalizedMessage(
        platform="telegram",
        channel_user_id="999999999",
        text="Hi, are you Jarvis?",
        thread_id="telegram:999999999",
        is_master=False,
        reply_to_message_id="7",
        raw={"smoke": True},
    )
    with patch.object(tg, "send_reply", side_effect=fake_send_reply), \
         patch.object(tg, "show_typing", side_effect=fake_show_typing):
        await route_inbound(non_master_msg)
    if len(sent_replies) != 1 or "master" not in sent_replies[0][1].lower():
        failures.append(
            f"non-master path didn't refuse cleanly; replies={sent_replies}"
        )
    else:
        print(f"  ✓ refused: {sent_replies[0][1]!r}")

    print()
    if failures:
        print("=== FAIL ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("=== ALL GREEN ===")
    return 0


async def _runner() -> int:
    try:
        return await main()
    finally:
        await close_checkpointer()
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_runner()))
