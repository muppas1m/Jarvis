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
import asyncio
import json
import os
import tempfile
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


def _format_ingest_reply(filename: str, result: dict) -> str:
    """Master-facing confirmation for a completed ingestion. Pure (testable) —
    maps the ``ingest_document`` result dict to a reply, distinguishing a fresh
    ingest from a content-hash dedup (no-op) and a pipeline-version replace."""
    chunks = result.get("chunks_stored", 0)
    if result.get("deduplicated"):
        return (
            f"📄 *{filename}* is already in my knowledge base — no changes needed. "
            "Ask me anything about it."
        )
    if result.get("replaced"):
        return (
            f"📄 Updated *{filename}* — re-indexed {chunks} chunk(s) with the latest "
            "pipeline. Ask me anything about it."
        )
    return (
        f"📄 Ingested *{filename}* — {chunks} chunk(s) indexed. Ask me anything about it."
    )


class TelegramChannel(Channel):
    platform = "telegram"

    def __init__(self) -> None:
        if not settings.TELEGRAM_BOT_TOKEN:
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")
        self.bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
        # Strong refs to detached background tasks (ingestion). Without this the
        # event loop only keeps a weak ref and can GC a task mid-run — a real
        # upload would silently vanish after the "ingesting…" ack.
        self._bg_tasks: set = set()

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
    # Document ingestion (RAG corpus uploads)
    # ------------------------------------------------------------------
    async def handle_document(self, message: Any) -> None:
        """Ingest a document attached to a Telegram message into the RAG corpus.

        Telegram attachments arrive as ``message.document``; the polling driver's
        TEXT-only handler silently dropped them (the master's "uploaded doc never
        ingested" gap). This downloads the file and runs the same
        ``ingest_document`` pipeline the /documents/upload API uses, then confirms.

        Master-only: an open ingest path is corpus poisoning by anyone who can DM
        the bot (every later search reads what was ingested). Unsupported types
        and oversized files get a plain reply — never a silent drop.
        """
        doc = getattr(message, "document", None)
        if doc is None:
            return
        chat_id = str(message.chat_id)
        if chat_id != settings.TELEGRAM_MASTER_CHAT_ID:
            logger.warning("telegram_document_non_master_ignored", chat_id=chat_id)
            return

        # Canonical allowed set + pipeline live in the documents layer; reuse the
        # API's constant so Telegram and HTTP accept exactly the same formats.
        from app.api.documents import ALLOWED_EXTENSIONS

        filename = doc.file_name or "upload"
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            await self._send_with_markdown_fallback(
                chat_id,
                f"I can't ingest `{ext or 'that'}` files. I handle: "
                + ", ".join(sorted(ALLOWED_EXTENSIONS)) + ".",
                "Markdown",
            )
            return

        max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if doc.file_size and doc.file_size > max_bytes:
            await self._send_with_markdown_fallback(
                chat_id,
                f"That file is too large (~{doc.file_size // (1024 * 1024)} MB). "
                f"My limit is {settings.MAX_UPLOAD_SIZE_MB} MB.",
                "Markdown",
            )
            return

        # Ack immediately, then ingest in the BACKGROUND. Ingestion (download +
        # extract/chunk/contextualize/embed) takes many seconds and MUST NOT block
        # the Telegram polling loop — awaiting it inline froze the whole bot ~20min
        # on a 1.2 MB PDF. create_task detaches it; the sync extract/chunk stages
        # run off-thread inside ingest_document so this genuinely yields.
        await self._send_with_markdown_fallback(
            chat_id,
            f"📄 Got *{filename}* — ingesting now, I'll confirm when it's ready.",
            "Markdown",
        )
        task = asyncio.create_task(
            self._ingest_document_bg(chat_id, doc.file_id, filename, ext)
        )
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _ingest_document_bg(
        self, chat_id: str, file_id: str, filename: str, ext: str
    ) -> None:
        """Download + ingest detached from the poller, then reply with the outcome.
        Never raises (it's a fire-and-forget task); a failure replies instead of
        silently dropping."""
        try:
            await self.bot.send_chat_action(chat_id=chat_id, action="typing")
        except Exception:
            pass

        tmp_path: str | None = None
        try:
            tg_file = await self.bot.get_file(file_id)
            with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
                tmp_path = tmp.name
            await tg_file.download_to_drive(tmp_path)

            from app.documents.ingestion import ingest_document

            result = await ingest_document(tmp_path, filename, owner_id="master")
            reply = _format_ingest_reply(filename, result)
            logger.info(
                "telegram_document_ingested",
                filename=filename,
                chunks=result.get("chunks_stored"),
                deduplicated=result.get("deduplicated"),
                replaced=result.get("replaced"),
            )
        except Exception as exc:  # noqa: BLE001 — surface a failure, never silent-drop
            logger.error("telegram_document_ingest_failed", filename=filename, error=str(exc))
            reply = (
                f"Sorry, I couldn't ingest *{filename}* ({exc.__class__.__name__}). "
                "Try again, or send it as a different format."
            )
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

        await self._send_with_markdown_fallback(chat_id, reply, "Markdown")

    async def handle_photo(self, message: Any) -> None:
        """Acknowledge a photo/image upload instead of silently dropping it.

        A "photographed document" arrives as ``message.photo`` (a list of
        PhotoSize), NOT ``message.document`` — so the document handler misses it
        and `filters.Document.ALL` doesn't catch it. We don't OCR images yet
        (deferred), but the master must get a reply, not silence."""
        chat_id = str(message.chat_id)
        if chat_id != settings.TELEGRAM_MASTER_CHAT_ID:
            return
        await self._send_with_markdown_fallback(
            chat_id,
            "I can't read photos or images yet (no OCR). If that's a document, "
            "send it as a file — `.pdf`, `.docx`, `.xlsx`, `.txt`, `.md`, `.csv` "
            "— and I'll ingest it.",
            "Markdown",
        )

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

        async def _on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.document:
                return
            await self.handle_document(update.message)

        async def _on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            if not update.message or not update.message.photo:
                return
            await self.handle_photo(update.message)

        async def _on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
            from app.agent.approval_dispatch import alert_text_for, resolve_and_dispatch

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

            # Acknowledge the button + edit the message so the master sees the
            # action took. `action` is "approve" | "reject" — past-tense rendering
            # can't use a simple +"ed" suffix (would produce "Approveed").
            past_tense = "Approved" if action == "approve" else "Rejected"
            await query.answer(text=f"{past_tense}.")
            await query.edit_message_text(
                text=f"{'✅' if action == 'approve' else '❌'} {past_tense}."
            )

            # The single claim-then-dispatch gate (Phase 3): atomically claims +
            # executes out-of-band (email/calendar/whatsapp/…). Then surface the
            # outcome (the send result) as a follow-up alert.
            outcome = await resolve_and_dispatch(approval_id, action, "telegram", decision)
            alert = alert_text_for(outcome)
            if alert:
                await self.send_alert(alert)

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
        app.add_handler(MessageHandler(filters.Document.ALL, _on_document))
        app.add_handler(MessageHandler(filters.PHOTO, _on_photo))
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
