"""P4 — Telegram document-upload handler.

Telegram attachments arrive as ``message.document``; before this they were
silently dropped (the master's "uploaded doc never ingested" gap). The handler
downloads the file and runs the same ``ingest_document`` pipeline as the HTTP
API, master-only, with plain replies for unsupported / oversized files.

Covered: the pure reply formatter (new / dedup / replaced) and the handler
control flow (non-master ignored, unsupported ext rejected, happy path ingests).
The download+ingest internals are the API's already-tested pipeline; here we mock
the Bot + ingest_document and assert routing/gating.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.messaging.channels.telegram import TelegramChannel, _format_ingest_reply


def _make_channel() -> TelegramChannel:
    """Build a channel without the TELEGRAM_BOT_TOKEN constructor check, with a
    mocked Bot."""
    ch = TelegramChannel.__new__(TelegramChannel)
    ch.bot = AsyncMock()
    ch._bg_tasks = set()  # __init__ is bypassed; the offload needs this
    return ch


def _fake_message(chat_id: str, file_name: str, file_size: int = 1000) -> MagicMock:
    msg = MagicMock()
    msg.chat_id = chat_id
    doc = MagicMock()
    doc.file_name = file_name
    doc.file_size = file_size
    doc.file_id = "FILEID"
    msg.document = doc
    return msg


# --------------------------------------------------------------------------- #
# pure formatter                                                              #
# --------------------------------------------------------------------------- #
def test_format_ingest_reply_new():
    r = _format_ingest_reply("notes.md", {"chunks_stored": 5, "deduplicated": False, "replaced": False})
    assert "notes.md" in r and "5" in r


def test_format_ingest_reply_dedup():
    r = _format_ingest_reply("notes.md", {"chunks_stored": 0, "deduplicated": True, "replaced": False})
    assert "already" in r.lower()


def test_format_ingest_reply_replaced():
    r = _format_ingest_reply("notes.md", {"chunks_stored": 7, "deduplicated": False, "replaced": True})
    assert "updated" in r.lower() and "7" in r


# --------------------------------------------------------------------------- #
# handler control flow                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handle_document_ignores_non_master():
    """An open ingest path is corpus poisoning — only the master may ingest."""
    ch = _make_channel()
    msg = _fake_message(chat_id="99999", file_name="x.md")  # not the master
    with patch("app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"):
        await ch.handle_document(msg)
    ch.bot.send_message.assert_not_called()  # no ack, nothing scheduled


@pytest.mark.asyncio
async def test_handle_document_rejects_unsupported_ext():
    ch = _make_channel()
    msg = _fake_message(chat_id="12345", file_name="photo.jpg")
    with patch("app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"):
        await ch.handle_document(msg)
    ch.bot.get_file.assert_not_called()       # not downloaded
    ch.bot.send_message.assert_awaited()       # told the master why


@pytest.mark.asyncio
async def test_handle_document_acks_immediately_and_offloads(monkeypatch):
    """handle_document must NOT block on ingest — it acks and schedules the work
    on a background task (the freeze fix). The poller stays responsive."""
    ch = _make_channel()
    msg = _fake_message(chat_id="12345", file_name="report.md")
    scheduled = []

    def fake_create_task(coro):
        scheduled.append(coro)
        coro.close()  # don't run it here; avoids an un-awaited-coroutine warning
        return MagicMock()

    monkeypatch.setattr(
        "app.messaging.channels.telegram.asyncio.create_task", fake_create_task
    )
    with patch("app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"):
        await ch.handle_document(msg)
    ch.bot.send_message.assert_awaited()        # the "ingesting" ack
    assert len(scheduled) == 1                  # ingest offloaded to a task
    assert len(ch._bg_tasks) == 1               # strong ref held (no mid-run GC)
    ch.bot.get_file.assert_not_called()         # download is in the bg task, not here


@pytest.mark.asyncio
async def test_ingest_bg_ingests_and_confirms():
    """The background worker actually ingests + sends the outcome reply."""
    ch = _make_channel()
    ch.bot.get_file = AsyncMock(return_value=AsyncMock())  # File with download_to_drive
    ingest = AsyncMock(return_value={"chunks_stored": 3, "deduplicated": False, "replaced": False})
    with patch("app.documents.ingestion.ingest_document", new=ingest):
        await ch._ingest_document_bg("12345", "FILEID", "report.md", ".md")
    ingest.assert_awaited_once()
    assert ingest.await_args.kwargs.get("owner_id") == "master"  # multi-user seam
    ch.bot.send_message.assert_awaited()  # confirmation sent


# --------------------------------------------------------------------------- #
# photo upload — acknowledge, never silent-drop                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_handle_photo_acknowledges_master():
    """A photographed document arrives as message.photo (not .document) — we
    don't OCR yet, but must reply rather than drop."""
    ch = _make_channel()
    msg = MagicMock()
    msg.chat_id = "12345"
    msg.photo = [MagicMock()]  # a PhotoSize list
    with patch("app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"):
        await ch.handle_photo(msg)
    ch.bot.send_message.assert_awaited()  # acknowledged, not dropped


@pytest.mark.asyncio
async def test_handle_photo_ignores_non_master():
    ch = _make_channel()
    msg = MagicMock()
    msg.chat_id = "99999"
    msg.photo = [MagicMock()]
    with patch("app.config.settings.TELEGRAM_MASTER_CHAT_ID", "12345"):
        await ch.handle_photo(msg)
    ch.bot.send_message.assert_not_called()
