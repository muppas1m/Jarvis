"""
Webhook signature / JWT verification.

Phase 2 ships stubs for the channels whose real verifiers don't land until
Phase 4. The wiring (importing + calling these from the route handlers) is
identical between the stub and the real implementation — only this file
changes when Phase 4 lands. That's the point: route handlers don't have
to be rewritten when verification turns real.

Currently stubbed:
  - verify_gmail_webhook → Phase 4 Task 4.16 implements full Pub/Sub OIDC
    JWT verification (Google signing keys, audience claim against
    settings.WEBHOOK_SECRET_GMAIL, email claim is gmail-api-push@system,
    email_verified=True). Until then, returns True so the Phase 2 email
    flow can be exercised end-to-end.

The Telegram webhook verifier already lives inline in
`app/api/webhooks/telegram.py` (`_verify_telegram_secret`) — it's a simple
shared-secret HMAC compare, not complex enough to need its own module.
"""


def verify_gmail_webhook(_: str) -> bool:
    """Phase 2 stub. Replaced by Phase 4 Task 4.16's real verifier.

    The real implementation will:
      1. Strip "Bearer " prefix from the Authorization header
      2. Verify the JWT signature against Google's public keys (cached)
      3. Verify aud == settings.WEBHOOK_SECRET_GMAIL
      4. Verify email == gmail-api-push@system.gserviceaccount.com
      5. Verify email_verified is True
      6. Verify iss is accounts.google.com

    Returning True unconditionally during Phase 2 means anyone who finds
    /api/webhooks/gmail can POST to it. This is acceptable in Phase 2
    because (a) the URL is only exposed via the Cloudflare tunnel and (b)
    the worst a malicious POST can do is enqueue a Gmail history fetch
    against an attacker-controlled historyId, which falls back gracefully
    in _fetch_new_messages. Phase 4 closes this hole completely.
    """
    return True
