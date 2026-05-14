"""
Gmail Pub/Sub push notification receiver.

Auth model differs from Telegram's webhook:
  - Telegram: shared-secret HMAC echoed in X-Telegram-Bot-Api-Secret-Token
  - Gmail: Google-signed JWT in Authorization: Bearer header — verified
    against Google's signing keys + audience claim

Phase 2 ships with verify_gmail_webhook stubbed (returns True). Phase 4
Task 4.16 implements the real JWT verification. The route wiring here
doesn't change between phases — only the verifier behind it does. See
`app/security/webhook_verify.py` for the stub and the real-implementation
checklist.

The endpoint mounts at /api/webhooks/gmail (under the public api/webhooks
mount, NOT under protected_router — Pub/Sub can't carry our X-API-Key or
master JWT, the OIDC token in Authorization IS the auth on this path).

## ACK policy (Turn 17)

Pub/Sub push subscriptions use the HTTP status code as the ACK signal:
2xx = acknowledged, stop retrying; anything else = NACK, retry with
exponential backoff for up to 7 days. The naive "let exceptions bubble
up → FastAPI returns 500" path retries every failure, including
non-retry-worthy ones (auth revoked, LLM gateway exhausted after its own
internal retries, permanent Gmail API errors). Those retries burn LLM
quota for no benefit — the failure won't fix itself before the next push.

Policy: return 2xx by default, surface 5xx ONLY for transient
infrastructure failures where retry will likely succeed (DB unreachable,
Redis unreachable, Gmail API 5xx). Everything else: log structured error
+ return 200 so Pub/Sub stops retrying.

The whitelist below is conservative — adding new retry-worthy exception
types is cheap; removing them (and losing recovery for transient bugs)
is expensive.
"""
import asyncio

import redis.exceptions
from fastapi import APIRouter, HTTPException, Request, status
from googleapiclient.errors import HttpError as GoogleAPIError
from sqlalchemy.exc import DBAPIError, OperationalError

from app.email.gmail_pubsub import handle_gmail_push
from app.security.webhook_verify import verify_gmail_webhook
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _is_retry_worthy(exc: BaseException) -> bool:
    """Should this exception cause Pub/Sub to retry the push?

    Yes for transient infrastructure failures. No for everything else —
    the gateway already retried LLM calls 2x internally (tenacity), and
    returning 5xx would just amplify quota burn without recovery."""
    if isinstance(exc, (OperationalError, DBAPIError)):
        return True
    if isinstance(exc, redis.exceptions.ConnectionError):
        return True
    if isinstance(exc, asyncio.TimeoutError):
        return True
    if isinstance(exc, GoogleAPIError):
        try:
            if int(exc.resp.status) >= 500:
                return True
        except (AttributeError, ValueError):
            pass
    return False


@router.post("/gmail", status_code=status.HTTP_200_OK)
async def gmail_webhook(request: Request) -> dict:
    """Receive a Gmail Pub/Sub push, verify auth, dispatch with ACK policy."""
    auth_header = request.headers.get("Authorization", "")
    if not verify_gmail_webhook(auth_header):
        logger.warning("gmail_webhook_unauthorized")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Pub/Sub JWT")

    body = await request.json()
    message = body.get("message", {})
    if not message:
        # Pub/Sub sometimes sends test/health messages with no `message` field;
        # ack with 200 so it doesn't retry.
        return {"ok": True, "ignored": True}

    try:
        await handle_gmail_push(message)
        return {"ok": True}
    except Exception as exc:
        if _is_retry_worthy(exc):
            logger.warning(
                "gmail_webhook_retry_worthy_failure",
                error_type=type(exc).__name__,
                error=str(exc)[:300],
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="transient",
            )
        # Default: log + 200 so Pub/Sub stops retrying. The audit trail
        # is in the structured log; manual investigation if needed.
        logger.exception(
            "gmail_webhook_handler_failed_logged_not_retried",
            error_type=type(exc).__name__,
        )
        return {"ok": True, "error_logged": True}
