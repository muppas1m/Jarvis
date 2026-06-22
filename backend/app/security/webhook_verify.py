"""
Webhook signature / JWT verification.

Gmail Pub/Sub push delivery carries a Google-signed OIDC JWT in the
`Authorization: Bearer <jwt>` header (Pub/Sub's push authentication). This module
verifies it against Google's public signing keys (Phase 4.5 / plan Task 4.16),
replacing the Phase-2 always-True stub.

Scope: ONLY the Gmail verifier lives here.
  - Telegram's verifier is already real, inline in `app/api/webhooks/telegram.py`
    (`_verify_telegram_secret` — constant-time HMAC, deny-on-empty-secret). It's a
    simple shared-secret compare and doesn't need this module.
  - WhatsApp has no channel yet; its verifier ships with the WhatsApp task, not as
    dead code here.

Rollout note: the route handler runs this verifier on every push and logs its
verdict, but ENFORCEMENT (403 on a failed verdict) is gated by
`settings.GMAIL_WEBHOOK_ENFORCE` (default False = shadow/observe). See
`app/api/webhooks/gmail.py`. That keeps flipping the stub to the real verifier
from 403-ing the whole inbox before the live subscription's
`oidcToken.audience` is confirmed to match `WEBHOOK_SECRET_GMAIL`.
"""
from cachetools import TTLCache
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Gmail's Pub/Sub publisher service account — the OIDC token's `email` claim.
_PUBSUB_SERVICE_ACCOUNT = "gmail-api-push@system.gserviceaccount.com"
_GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}

# Google rotates its public keys; google-auth caches the JWKS internally keyed on
# the transport. Reuse a single transport (recycled hourly) instead of building a
# fresh one — and its cert cache — on every push.
_jwt_cache: TTLCache = TTLCache(maxsize=1, ttl=3600)


def _google_request() -> google_requests.Request:
    cached = _jwt_cache.get("transport")
    if cached is None:
        cached = google_requests.Request()
        _jwt_cache["transport"] = cached
    return cached


def verify_gmail_webhook(authorization_header: str) -> bool:
    """Verify a Gmail Pub/Sub push's OIDC JWT.

    Returns True only when: the JWT is signed by Google, `aud` matches our
    configured audience (`WEBHOOK_SECRET_GMAIL`, else `BASE_URL`), `email` is the
    Pub/Sub publisher service account, `email_verified` is True, and `iss` is a
    Google issuer. Every reject path logs a DISTINCT structured reason; a pass
    logs the decoded `aud`/`iss`/`email` — so the first real push after re-auth
    instantly shows pass-vs-reject in the logs. Never raises.
    """
    if not authorization_header:
        logger.warning("gmail_webhook_reject", reason="missing_auth_header")
        return False

    if not authorization_header.startswith("Bearer "):
        logger.warning("gmail_webhook_reject", reason="malformed_auth_header")
        return False

    bearer = authorization_header.removeprefix("Bearer ").strip()
    expected_audience = settings.WEBHOOK_SECRET_GMAIL or settings.BASE_URL

    try:
        # verify_oauth2_token enforces the signature, expiry, AND audience — a
        # wrong `aud` raises ValueError here, so it lands in this branch.
        claims = id_token.verify_oauth2_token(
            bearer, _google_request(), audience=expected_audience
        )
    except ValueError as exc:
        logger.warning("gmail_webhook_reject", reason="jwt_invalid", error=str(exc))
        return False

    aud = claims.get("aud")
    iss = claims.get("iss")
    email = claims.get("email")
    email_verified = claims.get("email_verified")

    issuer_ok = iss in _GOOGLE_ISSUERS
    sa_ok = email == _PUBSUB_SERVICE_ACCOUNT
    verified_ok = email_verified is True

    if not (issuer_ok and sa_ok and verified_ok):
        logger.warning(
            "gmail_webhook_reject",
            reason="claims_rejected",
            issuer_ok=issuer_ok,
            sa_ok=sa_ok,
            verified_ok=verified_ok,
            aud=aud,
            iss=iss,
            email=email,
            email_verified=email_verified,
        )
        return False

    logger.info("gmail_webhook_verified", aud=aud, iss=iss, email=email)
    return True
