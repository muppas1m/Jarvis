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
"""
from fastapi import APIRouter, HTTPException, Request, status

from app.email.gmail_pubsub import handle_gmail_push
from app.security.webhook_verify import verify_gmail_webhook
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/gmail", status_code=status.HTTP_200_OK)
async def gmail_webhook(request: Request) -> dict:
    """Receive a Gmail Pub/Sub push, verify, dispatch to handler."""
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

    await handle_gmail_push(message)
    return {"ok": True}
