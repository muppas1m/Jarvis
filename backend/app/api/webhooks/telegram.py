"""
Telegram webhook receiver — production inbound path.

Long-polling (the dev mode) needs no public URL but holds a connection
open and burns Telegram's getUpdates rate. In prod the bot is registered
with Telegram via setWebhook(url, secret_token=...) and Telegram POSTs
each Update here instead.

Security:
  - Telegram includes `X-Telegram-Bot-Api-Secret-Token` on every POST,
    set to whatever we passed when registering the webhook. Constant-time
    compare against TELEGRAM_WEBHOOK_SECRET; any mismatch is a 401 with
    no body to avoid signal-leak via timing.
  - The endpoint is intentionally NOT behind get_current_user — Telegram
    can't carry our X-API-Key or a JWT. The HMAC-style secret_token IS
    the auth here. That's why this lives under /api/webhooks (a dedicated
    public mount) rather than under any router that depends on
    get_current_user.

The actual normalize → route_inbound path is identical to long-polling;
only the transport changes. That symmetry is what makes the lifespan
mutex (one mode active at a time) safe — we're not maintaining two
parallel pipelines.
"""
import hmac

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import settings
from app.messaging.channels.telegram import get_telegram_channel
from app.messaging.router import route_inbound
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_telegram_secret(presented: str | None) -> bool:
    expected = settings.TELEGRAM_WEBHOOK_SECRET
    if not expected:
        # Defense against an empty .env value silently accepting every
        # incoming POST. If the server didn't configure a secret, no one
        # gets in.
        return False
    if not presented:
        return False
    return hmac.compare_digest(
        presented.encode("utf-8"), expected.encode("utf-8")
    )


@router.post("/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Receive a Telegram Update payload, verify HMAC, dispatch to route_inbound."""
    if not _verify_telegram_secret(x_telegram_bot_api_secret_token):
        logger.warning(
            "telegram_webhook_bad_secret",
            presented=bool(x_telegram_bot_api_secret_token),
        )
        # Return 401 with empty body — Telegram retries on 5xx but treats
        # 4xx as "stop sending". A persistently bad secret means our
        # config drifted and we want Telegram to back off until we fix it.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    payload = await request.json()
    tg = get_telegram_channel()
    msg = await tg.normalize(payload)
    if msg is None:
        # Non-message updates (edited messages, channel posts, callback
        # queries via webhook). Phase 1 only handles direct messages;
        # callback queries go through the polling app's CallbackQueryHandler
        # in dev. Returning 200 silently is correct: Telegram considers
        # the update delivered and won't retry.
        return {"ok": True, "ignored": True}

    await route_inbound(msg)
    return {"ok": True}
