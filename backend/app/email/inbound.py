"""Provider-agnostic inbound email pipeline.

Receives new mail (via a provider push or a safety-net poll), classifies it,
drafts a reply when needed, and routes it — archive (spam) / digest (fyi) /
queue-for-approval (action_required). Every provider touch goes through the
``EmailProvider`` interface (``parse_push`` / ``list_recent_message_ids`` /
``fetch_message`` / ``archive``); the classify/draft/digest steps are already
provider-neutral (they operate on subject/sender/body strings).

Three entry points, one pipeline (was ``gmail_pubsub``):
  - ``handle_push`` — a provider push notification (Gmail Pub/Sub today)
  - ``sweep_recent_inbox`` — the 15-min safety-net poll + the post-watch-renew
    catch-up

INSERT-as-gate race fix (preserved verbatim from the Gmail era — see
project_gmail_approval_duplicate_race): the EmailLog row is INSERTed BEFORE any
side effect, so concurrent deliveries of the same message arbitrate on the
UNIQUE(gmail_message_id) constraint — exactly one wins, the rest abort.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.briefing import record_briefing_item
from app.config import settings
from app.db.engine import async_session
from app.db.models import EmailLog
from app.email.classifier import classify_email
from app.email.provider import EmailProvider, InboundMessage, get_email_provider
from app.email.responder import generate_draft
from app.messaging.failure_alerter import send_approval_request_to_master
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def handle_push(provider_name: str, push_payload: dict) -> None:
    """Process a provider push notification — parse the delta cursor + sweep.

    The webhook is provider-specific (Gmail Pub/Sub vs Graph subscriptions carry
    different shapes + auth), so it passes its provider name; the adapter's
    ``parse_push`` extracts the cursor."""
    provider = get_email_provider(provider_name)
    cursor = provider.parse_push(push_payload)
    if cursor is None:
        return
    await sweep_recent_inbox(cursor=cursor, provider_name=provider_name)


async def sweep_recent_inbox(cursor: str | None = None, provider_name: str = "") -> int:
    """List recent inbox messages, skip ones already processed, run the rest
    through the pipeline. Shared by the push handler, the 15-min poll, and the
    post-renew catch-up. Returns the count of NEW messages processed."""
    provider = get_email_provider(provider_name or None)
    new_ids = await _new_message_ids(provider, cursor)
    for mid in new_ids:
        msg = await provider.fetch_message(mid)
        await _process_message(provider, msg)
    return len(new_ids)


async def _new_message_ids(provider: EmailProvider, cursor: str | None) -> list[str]:
    """Recent message ids the pipeline hasn't seen — provider lists candidates,
    we dedup against EmailLog (resilient to duplicate push deliveries)."""
    ids = await provider.list_recent_message_ids(cursor)
    if not ids:
        return []
    async with async_session() as session:
        result = await session.execute(
            select(EmailLog.gmail_message_id).where(EmailLog.gmail_message_id.in_(ids))
        )
        already = {row[0] for row in result.all()}
    return [i for i in ids if i not in already]


async def _process_message(provider: EmailProvider, msg: InboundMessage) -> None:
    """Full pipeline for one message. Ordering is load-bearing — the EmailLog
    INSERT claims the message id (the race gate) BEFORE any side effect fires."""
    # Step 1: six-axis triage (cheap classification on the fast model) — incl. the
    # simple/complex reply_effort, decided HERE before any drafting.
    triage = await classify_email(subject=msg.subject, sender=msg.sender, body=msg.body)

    # Step 2: draft ONLY a SIMPLE action_required reply (reply_effort decides, before
    # drafting — a complex one is never wastefully drafted; it gets a heads-up card and
    # is drafted on the master's "go"). Draft before the gate so the EmailLog row carries
    # it on first INSERT.
    draft = None
    if triage.classification == "action_required" and triage.reply_effort == "simple":
        draft = await generate_draft(subject=msg.subject, sender=msg.sender, body=msg.body)

    # GATE: claim ownership of this message id via the EmailLog INSERT. The
    # column is historically named gmail_message_id; it stores the OPAQUE provider
    # message id (a rename is a deferred cosmetic — see commits.md).
    async with async_session() as session:
        log = EmailLog(
            provider=provider.name,
            gmail_message_id=msg.message_id,
            subject=msg.subject,
            sender=msg.sender,
            classification=triage.classification,
            meta=triage.model_dump(),
            draft_response=draft,
            response_complexity=triage.reply_effort,
        )
        session.add(log)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info("email_log_already_exists", provider=provider.name, message_id=msg.message_id)
            return  # CRITICAL: another delivery owns it — no side effects fire.

    # Step 3: route — only reached when this delivery claimed the message id.
    route = triage.classification
    if route == "spam" and triage.confidence < settings.EMAIL_TRIAGE_CONFIDENCE_FLOOR:
        logger.info("spam_downgraded_low_confidence", subject=msg.subject, confidence=triage.confidence)
        route = "fyi"  # low-confidence spam → digest, so a misclassified real email stays visible

    if route == "spam":
        await provider.archive(msg.message_id)
        logger.info("email_archived_spam", provider=provider.name, subject=msg.subject)
    elif route == "fyi":
        # Durable briefing item (5.3) — windowable by the HWM, replacing the
        # clear-on-build Redis digest. occurred_at = arrival time.
        await record_briefing_item(
            kind="email",
            title=msg.subject or "",
            source=msg.sender or "",
            preview=(msg.body or "")[:300],
            urgency=triage.urgency,
            occurred_at=datetime.now(UTC),
            meta={"provider": provider.name, "message_id": msg.message_id},
        )
        logger.info("email_recorded_to_briefing", subject=msg.subject, urgency=triage.urgency)
    elif route == "action_required":
        if triage.reply_effort == "simple":
            # Simple — already drafted; queue the draft + the original email for approval.
            await _queue_email_approval(provider.name, msg, draft=draft, needs_drafting=False)
        else:
            # Complex — NO draft. Queue a heads-up card the master acts on (HUD + voice +
            # Telegram, like everything else); on "go" it drafts + re-queues as a simple
            # one. No wasted drafting; the master controls when the careful draft happens.
            await _queue_email_approval(provider.name, msg, draft=None, needs_drafting=True)


async def _queue_email_approval(
    provider_name: str, msg: InboundMessage, *, draft: str | None, needs_drafting: bool
) -> None:
    """Queue an inbound email for the master — provider-tagged. Two shapes, ONE card
    kind (``email_reply``) so the queue / voice / HUD plumbing is shared:

      - SIMPLE (``needs_drafting=False``) — carries the ``draft`` + the ORIGINAL email
        body; the master approves to SEND.
      - COMPLEX (``needs_drafting=True``) — NO draft yet; a heads-up the master can act
        on. On "go" (approve), the dispatcher drafts + re-queues a simple card; the
        original body rides in the payload for both the heads-up and the re-draft.

    thread_id = ``email:<provider>:<message_id>``; interrupt_id mirrors it (no LangGraph
    token); expires_at uses APPROVAL_EXPIRY_HOURS."""
    from datetime import datetime, timedelta

    from app.db.models import PendingApproval

    thread_id = f"email:{provider_name}:{msg.message_id}"
    expires_at = datetime.now(UTC) + timedelta(hours=settings.APPROVAL_EXPIRY_HOURS)

    if needs_drafting:
        description = (
            f"📧 A reply to '{msg.subject}' from {msg.sender} needs your input — "
            f"say the word and I'll draft it."
        )
    else:
        description = f"Reply to '{msg.subject}' from {msg.sender}:\n\n{draft}"

    async with async_session() as session:
        approval = PendingApproval(
            thread_id=thread_id,
            interrupt_id=thread_id,
            action_type="email_reply",
            description=description,
            payload={
                "provider": provider_name,
                "message_id": msg.message_id,
                "thread_ref": msg.thread_ref,
                "rfc822_message_id": msg.rfc822_message_id,
                "subject": msg.subject,
                "sender": msg.sender,
                "body": msg.body or "",          # the ORIGINAL email — shown on the card
                "draft": draft or "",            # the reply draft ("" until drafted)
                "needs_drafting": needs_drafting,
            },
            expires_at=expires_at,
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)

    await send_approval_request_to_master(
        approval_id=str(approval.id),
        tool_name="email_reply",
        description=approval.description,
        needs_drafting=needs_drafting,   # heads-up → "Draft it / Leave it" on Telegram too
    )


async def requeue_drafted_email_card(row, draft: str) -> None:
    """Create a SIMPLE email_reply card from a needs_drafting row's payload + a freshly
    generated draft — the master's "go" → draft path (called by the dispatcher). Same
    shape + Telegram announce as a simple ingest; the new card then surfaces to the HUD
    + voice via the unified /approvals/queue poll, exactly like an inbound simple card."""
    from datetime import datetime, timedelta

    from app.db.models import PendingApproval

    p = dict(row.payload or {})
    subject, sender = p.get("subject", ""), p.get("sender", "")
    async with async_session() as session:
        new = PendingApproval(
            thread_id=row.thread_id,
            interrupt_id=row.thread_id,
            action_type="email_reply",
            description=f"Reply to '{subject}' from {sender}:\n\n{draft}",
            payload={**p, "draft": draft, "needs_drafting": False},  # carries the original body
            expires_at=datetime.now(UTC) + timedelta(hours=settings.APPROVAL_EXPIRY_HOURS),
        )
        session.add(new)
        await session.commit()
        await session.refresh(new)

    await send_approval_request_to_master(
        approval_id=str(new.id), tool_name="email_reply", description=new.description,
    )
