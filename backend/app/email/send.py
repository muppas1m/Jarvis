"""Provider-neutral email send — the single outbound path.

Both the agent tool (``agent.tools.email_send``) and the approval handler
(``email.approval_handler``) call ``send_email``; it resolves the configured
``EmailProvider`` adapter, sends, and writes the provider-neutral side effects
(AuditTrail row + EmailLog.auto_sent flip). The provider does the wire work
(MIME/threading/Graph); this owns the bookkeeping that's identical regardless of
provider. (These side effects previously lived inside ``gmail_send``; relocating
them here keeps the adapter pure and the bookkeeping shared.)
"""
from __future__ import annotations

import time
import uuid

from sqlalchemy import update

from app.db.engine import async_session
from app.db.models import AuditTrail, EmailLog
from app.email.provider import ReplyRef, SendResult, get_email_provider
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def send_email(
    to: str,
    subject: str,
    body: str,
    reply_to: ReplyRef | None = None,
    *,
    source_message_id: str = "",
    provider_name: str = "",
) -> SendResult:
    """Send via the configured (or named) provider, with audit + auto_sent.

    ``source_message_id`` is the opaque id of the message this is a reply to —
    used to flip that EmailLog row's ``auto_sent`` (so history-search can tell
    "auto-sent" from "drafted, never sent"). ``provider_name`` pins a specific
    adapter (the approval handler passes the tag the message arrived on); empty →
    the ``EMAIL_PROVIDER`` default."""
    provider = get_email_provider(provider_name or None)

    send_start = time.monotonic()
    try:
        result = await provider.send(to, subject, body, reply_to=reply_to)
    except Exception as exc:  # noqa: BLE001 — audited then re-raised
        await _audit(
            provider.name, to, subject, source_message_id,
            success=False, error=str(exc)[:500],
            latency_ms=int((time.monotonic() - send_start) * 1000),
        )
        logger.error("email_send_failed", provider=provider.name, to=to, error=str(exc))
        raise

    logger.info(
        "email_send_ok",
        provider=provider.name, to=to, subject=subject[:80],
        sent_message_id=result.sent_message_id, threaded=bool(reply_to),
    )
    await _audit(
        provider.name, to, subject, source_message_id,
        success=True, error=None, sent_message_id=result.sent_message_id,
        latency_ms=int((time.monotonic() - send_start) * 1000),
    )
    if source_message_id:
        await _mark_email_auto_sent(source_message_id)
    return result


async def _audit(
    provider_name: str,
    to: str,
    subject: str,
    source_message_id: str,
    success: bool,
    error: str | None = None,
    sent_message_id: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """AuditTrail row for the send attempt — same schema tool_executor_node uses,
    so audit queries are uniform across invocation pathways."""
    thread_id = f"email:{provider_name}:{source_message_id}" if source_message_id else None
    output_summary = f"sent_message_id={sent_message_id}" if success else f"error={error}"
    async with async_session() as session:
        session.add(
            AuditTrail(
                id=uuid.uuid4(),
                thread_id=thread_id,
                action="email_send",
                tool_name="email_send",
                safety_level="approve",
                input_summary=f"to={to}, subject={subject[:120]}"[:500],
                output_summary=output_summary[:500] if output_summary else None,
                success=success,
                error=error,
                cost_usd=0.0,
                latency_ms=latency_ms,
            )
        )
        await session.commit()


async def _mark_email_auto_sent(source_message_id: str) -> None:
    """Flip EmailLog.auto_sent on the source row. Best-effort: an agent-direct
    send against a message that never went through the inbound pipeline has no
    row — log and continue (the audit trail is canonical either way).

    (The column is historically named ``gmail_message_id`` but stores the opaque
    provider message id; a rename is a deferred cosmetic — see commits.md.)"""
    try:
        async with async_session() as session:
            await session.execute(
                update(EmailLog)
                .where(EmailLog.gmail_message_id == source_message_id)
                .values(auto_sent=True)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning("email_auto_sent_update_failed", source_message_id=source_message_id, error=str(exc))
