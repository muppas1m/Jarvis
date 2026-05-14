"""
Telegram channel — Phase 1 primary.

Two entry modes:
  - Long-polling (TELEGRAM_USE_POLLING=true, default in dev) — needs no
    public URL. python-telegram-bot's `Application.run_polling()` opens a
    persistent connection to Telegram and pulls updates.
  - Webhook (TELEGRAM_USE_POLLING=false, prod) — Telegram POSTs to
    `/api/webhooks/telegram`; same code path through `normalize()`.

The two-button approval keyboard ferries `{"a": "approve"|"reject", "id": <approval_id>}`
back through the CallbackQueryHandler, which resolves the DB row and
resumes the graph via `route_approval_decision`.

Lazy factory `get_telegram_channel()` — the constructor raises if
TELEGRAM_BOT_TOKEN is unset, and we don't want that crash to fire at
module-import time (it'd happen before lifespan can guard).
"""
import json
from typing import Any

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.config import settings
from app.messaging.channel import Channel, NormalizedMessage
from app.utils.logging import get_logger

logger = get_logger(__name__)


class TelegramChannel(Channel):
    platform = "telegram"

    def __init__(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)

    # ------------------------------------------------------------------
    # Channel interface
    # ------------------------------------------------------------------
    async def normalize(self, raw_payload: dict) -> NormalizedMessage | None:
        update = Update.de_json(raw_payload, self.bot)
        if not update or not update.message or not update.message.text:
            return None

        chat_id = str(update.message.chat_id)
        return NormalizedMessage(
            platform="telegram",
            channel_user_id=chat_id,
            text=update.message.text,
            thread_id=Channel.thread_id_for("telegram", chat_id),
            is_master=(chat_id == settings.TELEGRAM_MASTER_CHAT_ID),
            reply_to_message_id=str(update.message.message_id),
            raw=raw_payload,
        )

    async def _send_with_markdown_fallback(
        self,
        chat_id: str,
        text: str,
        parse_mode: str | None,
        **extra: Any,
    ) -> None:
        """Telegram's MarkdownV1 parser is finicky and the bot's replies
        come from an LLM that doesn't always produce well-balanced markup
        (unmatched underscores, asterisks inside URLs, code-block fences
        without language tags, etc.). A parse failure raises BadRequest
        and — because the call originates inside python-telegram-bot's
        polling callback, NOT under route_inbound's try/except — silently
        swallows the reply.

        Always retry once with parse_mode=None so the master never sees a
        silent drop. Plain text is strictly worse formatting but strictly
        better than no reply at all."""
        try:
            await self.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=parse_mode, **extra
            )
        except BadRequest as exc:
            if "parse" not in str(exc).lower():
                raise
            logger.warning(
                "telegram_markdown_parse_failed",
                chat_id=chat_id,
                error=str(exc),
                text_preview=text[:120],
            )
            await self.bot.send_message(
                chat_id=chat_id, text=text, parse_mode=None, **extra
            )

    async def send_reply(
        self,
        msg: NormalizedMessage,
        text: str,
        parse_mode: str = "Markdown",
    ) -> None:
        await self._send_with_markdown_fallback(
            chat_id=msg.channel_user_id, text=text, parse_mode=parse_mode
        )
        logger.info(
            "telegram_send_reply",
            chat_id=msg.channel_user_id,
            thread_id=msg.thread_id,
            text_len=len(text or ""),
        )

    async def send_alert(self, text: str) -> None:
        await self._send_with_markdown_fallback(
            chat_id=settings.TELEGRAM_MASTER_CHAT_ID,
            text=text,
            parse_mode="Markdown",
        )

    async def send_approval_request(self, approval_id: str, description: str) -> None:
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Approve",
                    callback_data=json.dumps({"a": "approve", "id": approval_id}),
                ),
                InlineKeyboardButton(
                    "❌ Reject",
                    callback_data=json.dumps({"a": "reject", "id": approval_id}),
                ),
            ]
        ])
        await self._send_with_markdown_fallback(
            chat_id=settings.TELEGRAM_MASTER_CHAT_ID,
            text=f"🔔 *Approval Required*\n\n{description}",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )

    async def show_typing(self, msg: NormalizedMessage) -> None:
        # Defensive — a failed typing indicator must never block the reply path.
        try:
            await self.bot.send_chat_action(
                chat_id=msg.channel_user_id, action="typing"
            )
        except Exception as exc:
            logger.debug("telegram_typing_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Long-polling driver (dev mode)
    # ------------------------------------------------------------------
    def build_polling_application(self) -> Application:
        """Build a python-telegram-bot Application configured for long-polling.

        Lifespan starts this in a background task. It never returns by itself
        — Telegram holds the connection open and pushes updates as they arrive.
        """
        app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

        async def _on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            from app.messaging.router import route_inbound

            payload = update.to_dict()
            msg = await self.normalize(payload)
            if msg is None:
                return
            await route_inbound(msg)

        async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            from app.api.approvals import resolve_approval
            from app.messaging.router import route_approval_decision

            query = update.callback_query
            if not query or not query.data:
                return

            try:
                data = json.loads(query.data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("telegram_callback_bad_json", data=query.data)
                return

            action = data.get("a")              # "approve" | "reject"
            approval_id = data.get("id")
            if action not in ("approve", "reject") or not approval_id:
                logger.warning("telegram_callback_malformed", data=data)
                return

            decision: dict[str, Any] = {"approved": action == "approve"}
            if action == "reject":
                decision["reason"] = "rejected via Telegram"

            # Acknowledge the button + edit the message so the master sees
            # the action took. The actual graph resume is below.
            # `action` is "approve" | "reject" — past-tense rendering can't
            # use a simple +"ed" suffix (would produce "Approveed").
            past_tense = "Approved" if action == "approve" else "Rejected"
            await query.answer(text=f"{past_tense}.")
            await query.edit_message_text(
                text=f"{'✅' if action == 'approve' else '❌'} {past_tense}."
            )

            thread_id = await resolve_approval(
                approval_id=approval_id,
                action=action,
                resolved_via="telegram",
            )
            if thread_id:
                await route_approval_decision(thread_id, "telegram", decision)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
        app.add_handler(CallbackQueryHandler(_on_callback))
        return app


# Lazy singleton — see channel ABC docstring for why we don't construct
# TelegramChannel at import time.
_telegram_channel: TelegramChannel | None = None


def get_telegram_channel() -> TelegramChannel:
    """Construct (once) and return the TelegramChannel singleton."""
    global _telegram_channel
    if _telegram_channel is None:
        _telegram_channel = TelegramChannel()
    return _telegram_channel
