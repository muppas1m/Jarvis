"""Handle incoming Gmail Pub/Sub push notifications."""
import base64
import json
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from sqlalchemy import select
from app.config import settings
from app.email.classifier import classify_email
from app.email.responder import generate_draft
from app.email.digest import add_to_digest
from app.messaging.failure_alerter import send_approval_request_to_master, send_system_alert
from app.db.engine import async_session
from app.db.models import EmailLog
import structlog

logger = structlog.get_logger()


async def handle_gmail_push(pubsub_message: dict):
    """Process a Gmail Pub/Sub push notification — decode + delegate to
    `sweep_recent_inbox`. The actual fetch/dedup/process pipeline lives in
    the shared helper so gmail_renew (post-renewal catch-up) and gmail_check
    (15-min safety-net poll) can reuse it without duplicating logic."""
    data = base64.b64decode(pubsub_message.get("data", "")).decode("utf-8")
    payload = json.loads(data)
    history_id = payload.get("historyId")

    if not history_id:
        return

    await sweep_recent_inbox(history_id)


async def sweep_recent_inbox(history_id: str | None = None) -> int:
    """List recent INBOX messages and run each not yet in email_logs through
    the full classify/route/log pipeline.

    Single helper, three callers:
      - handle_gmail_push (Pub/Sub-driven, real-time)
      - gmail_renew Celery task (after watch re-registration — catches anything
        published in the seam between the old watch's last delivery and the new
        watch's first)
      - gmail_check Celery task (every 15 min as a Pub/Sub safety net)

    `history_id` is currently accepted but unused — kept for forward-compat
    with a future state-tracked-delta implementation that uses history.list().

    Returns the count of messages the lister returned (NOT the count actually
    processed; dedup may skip some). Callers can log this for visibility.
    """
    service = _get_gmail_service()
    messages = await _fetch_new_messages(service, history_id)

    for msg in messages:
        await _process_single_email(service, msg)

    return len(messages)


async def _process_single_email(service, message_data: dict):
    """Full pipeline for one email.

    Ordering matters here. The original Task 2.3 verbatim ordering had
    routing → side-effects → email_logs INSERT. Concurrent Pub/Sub
    deliveries (Pub/Sub guarantees at-least-once and retries on any 5xx)
    could both pass the _fetch_new_messages dedup query before either
    committed an EmailLog row, then race through the routing block —
    archiving twice, queuing N approval rows, adding N digest entries —
    before the IntegrityError on the eventual EmailLog INSERT caught
    the second writer. Observed in Turn 16: 12 PendingApproval rows for
    one Zapier email (`19e2274ca914e6b6`).

    The fix: claim ownership of `msg_id` by INSERTing the EmailLog row
    BEFORE any side effects fire. The UNIQUE constraint on
    gmail_message_id atomically arbitrates concurrent writers — exactly
    one delivery wins, the rest hit IntegrityError and abort. See
    `project_gmail_approval_duplicate_race.md` for the full rationale.

    Trade-off: generate_draft fires for action_required emails before
    the gate check, so a duplicate delivery wastes one drafting LLM call
    per redelivery. Cheap (~$0.001 each, Groq is $0 anyway) vs. the
    UPDATE-after-gate alternative which would add a query for every
    successful action_required write.
    """
    from sqlalchemy.exc import IntegrityError

    msg_id = message_data["id"]

    # Fetch full message
    full_msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    headers = {h["name"]: h["value"] for h in full_msg["payload"].get("headers", [])}
    subject = headers.get("Subject", "(No Subject)")
    sender = headers.get("From", "Unknown")
    body = _extract_body(full_msg)

    # Step 1: Classify (cheap classification call against fast model).
    classification = await classify_email(subject=subject, sender=sender, body=body)

    # Step 2: Generate draft if needed BEFORE the gate, so the EmailLog
    # row carries the draft fields on first INSERT (no follow-up UPDATE).
    draft = None
    if classification == "action_required":
        draft = await generate_draft(subject=subject, sender=sender, body=body)

    # GATE: claim ownership of this msg_id by INSERTing EmailLog FIRST.
    # If a concurrent delivery beat us to it, IntegrityError fires here
    # and we return immediately — NO side effects fire on the duplicate path.
    async with async_session() as session:
        log = EmailLog(
            gmail_message_id=msg_id,
            subject=subject,
            sender=sender,
            classification=classification,
            draft_response=draft["response"] if draft else None,
            response_complexity=draft.get("complexity") if draft else None,
        )
        session.add(log)
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            logger.info("email_log_already_exists", gmail_message_id=msg_id)
            return  # CRITICAL: stop processing, the other delivery owns it.

    # Step 3: Route based on classification — only reached when this delivery
    # successfully claimed ownership of msg_id via the EmailLog INSERT above.
    if classification == "spam":
        service.users().messages().modify(
            userId="me", id=msg_id, body={"removeLabelIds": ["INBOX"]}
        ).execute()
        logger.info("email_archived_spam", subject=subject)

    elif classification == "fyi":
        await add_to_digest(subject=subject, sender=sender, body_preview=body[:300])
        logger.info("email_added_to_digest", subject=subject)

    elif classification == "action_required":
        # RFC822 Message-ID header — used by gmail_send for In-Reply-To
        # threading. Distinct from msg_id (Gmail-internal). Stored in
        # PendingApproval.payload so the dispatch path can skip a Gmail
        # fetch for new rows. Header is sometimes capitalized "Message-Id"
        # or missing entirely; default to empty string and let dispatch
        # fetch as fallback.
        rfc822_message_id = (
            headers.get("Message-ID")
            or headers.get("Message-Id")
            or ""
        )

        if draft["complexity"] == "simple":
            # Auto-send (still APPROVE safety — queue for approval).
            await _queue_email_approval(
                msg_id=msg_id,
                rfc822_message_id=rfc822_message_id,
                subject=subject,
                sender=sender,
                draft=draft["response"],
            )
        else:
            # Complex — notify master with full context. Copy is deliberately
            # capability-neutral: no trailing "what happens next" footer.
            # The conversational reply-to-edit path doesn't exist yet (see
            # project_email_action_capability_gap.md); promising it in copy
            # would be the same trap as the original "say 'send it'" wording
            # from plan-verbatim Task 2.3. Master sees the draft for context
            # and decides whether to handle the email manually in Gmail.
            await send_system_alert(
                f"📧 **Action Required** — agent needs your input\n\n"
                f"**From:** {sender}\n"
                f"**Subject:** {subject}\n\n"
                f"**Draft for context (review before responding):**\n{draft['response']}"
            )


async def _queue_email_approval(
    msg_id: str,
    rfc822_message_id: str,
    subject: str,
    sender: str,
    draft: str,
):
    """Queue email send for master approval via Telegram.

    Plan gap fill: Task 2.3's verbatim PendingApproval construction omits
    thread_id, but the Phase 1 schema (001_initial_schema) declares
    pending_approvals.thread_id NOT NULL. Synthesizing as `gmail:<msg_id>`
    so Gmail-originated approvals are distinguishable from LangGraph-
    conversation approvals (which use telegram:<chat_id> / web:<uuid>) and
    the row traces back to its source email.

    Also setting interrupt_id and expires_at — both NOT NULL columns the
    plan-verbatim code skipped. interrupt_id mirrors thread_id since
    there's no LangGraph interrupt token to reference; expires_at uses
    APPROVAL_EXPIRY_HOURS to match the LangGraph approval flow's expiry.

    Turn 17.5 addition: payload now also stores `subject` and
    `rfc822_message_id`. The Gmail-approval dispatch path in
    app.messaging.router.route_approval_decision uses these directly so it
    can skip an extra Gmail API call per Approve tap for new rows. Stale
    rows (from before Turn 17.5) fall back to fetching from Gmail.
    """
    from datetime import datetime, timedelta, timezone

    from app.config import settings
    from app.db.models import PendingApproval

    thread_id = f"gmail:{msg_id}"
    expires_at = datetime.now(timezone.utc) + timedelta(
        hours=settings.APPROVAL_EXPIRY_HOURS
    )

    async with async_session() as session:
        approval = PendingApproval(
            thread_id=thread_id,
            interrupt_id=thread_id,
            action_type="gmail_reply",
            description=f"Reply to '{subject}' from {sender}:\n\n{draft}",
            payload={
                "gmail_message_id": msg_id,
                "rfc822_message_id": rfc822_message_id,
                "subject": subject,
                "sender": sender,
                "draft": draft,
            },
            expires_at=expires_at,
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)

    # Plan-verbatim Task 2.3 calls this with (approval_id, description) but the
    # actual Phase 1 signature is (approval_id, tool_name, description). Adapting.
    await send_approval_request_to_master(
        approval_id=str(approval.id),
        tool_name="gmail_reply",
        description=approval.description,
    )


def _get_gmail_service():
    from app.email.gmail_watch import get_gmail_service
    return get_gmail_service()


async def _fetch_new_messages(service, history_id: str) -> list[dict]:
    """Fetch recent INBOX messages we haven't already processed.

    Plan gap: Task 2.3 references this function but never defines it. The
    "obvious" implementation would be users.history.list(startHistoryId=...)
    using a stored last-seen historyId — but Phase 1's reset deliberately
    dropped the gmail_sync_state table (Pub/Sub-only architecture, no
    polling cursor). Without that state, history.list with the Pub/Sub
    payload's historyId returns empty (it asks "what's after N" when N is
    already the latest).

    Pragmatic fallback: list recent INBOX message IDs (small bounded
    request), filter against email_logs.gmail_message_id (UNIQUE) to skip
    anything we've already processed. Resilient to duplicate Pub/Sub
    deliveries (Pub/Sub guarantees at-least-once). The `history_id` arg
    is accepted but unused — forward-compat for if a later task introduces
    state tracking and switches to history.list-based deltas.
    """
    list_response = service.users().messages().list(
        userId="me",
        labelIds=["INBOX"],
        maxResults=10,
    ).execute()
    candidates = list_response.get("messages", [])

    if not candidates:
        return []

    candidate_ids = [m["id"] for m in candidates]
    async with async_session() as session:
        result = await session.execute(
            select(EmailLog.gmail_message_id).where(
                EmailLog.gmail_message_id.in_(candidate_ids)
            )
        )
        already_logged = {row[0] for row in result.all()}

    return [m for m in candidates if m["id"] not in already_logged]


def _extract_body(message: dict) -> str:
    """Extract plain text body from Gmail message."""
    payload = message.get("payload", {})
    parts = payload.get("parts", [])

    for part in parts:
        if part.get("mimeType") == "text/plain":
            data = part.get("body", {}).get("data", "")
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Fallback: direct body
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return ""
