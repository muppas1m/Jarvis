"""
Security-boundary tests for `verify_gmail_webhook` (Phase 4.5 / plan Task 4.16).

This is the auth on the public /api/webhooks/gmail route, so the bar is: a valid
Google-signed Pub/Sub OIDC token passes, and EVERY tampered/forged variant is
rejected. The Google JWT call (`id_token.verify_oauth2_token`) is mocked — no
network, and we exercise both its raise paths (bad signature / wrong audience)
and the claim-level checks we layer on top.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.webhooks import gmail as gmail_route
from app.security import webhook_verify
from app.security.webhook_verify import verify_gmail_webhook

GOOD_CLAIMS = {
    "aud": "3f5ae4e10ebccb38aec341590381b005",
    "iss": "https://accounts.google.com",
    "email": "gmail-api-push@system.gserviceaccount.com",
    "email_verified": True,
}


def _patch_verify(*, return_value=None, side_effect=None):
    """Mock the Google JWT verification call — no network."""
    return patch.object(
        webhook_verify.id_token,
        "verify_oauth2_token",
        return_value=return_value,
        side_effect=side_effect,
    )


def test_valid_token_passes():
    with _patch_verify(return_value=dict(GOOD_CLAIMS)):
        assert verify_gmail_webhook("Bearer good.jwt.token") is True


def test_missing_header_rejected():
    assert verify_gmail_webhook("") is False


def test_no_bearer_prefix_rejected():
    # A raw token without the "Bearer " prefix must reject WITHOUT even calling
    # the verifier (malformed header, fail fast).
    with _patch_verify(return_value=dict(GOOD_CLAIMS)) as m:
        assert verify_gmail_webhook("good.jwt.token") is False
        m.assert_not_called()


def test_bad_signature_rejected():
    # verify_oauth2_token raises ValueError on a bad/unverifiable signature.
    with _patch_verify(side_effect=ValueError("Could not verify token signature")):
        assert verify_gmail_webhook("Bearer forged.signature") is False


def test_wrong_audience_rejected():
    # The library enforces `aud`, raising ValueError on mismatch — so a token
    # minted for someone else's audience never reaches our claim checks.
    with _patch_verify(side_effect=ValueError("Token has wrong audience some-other-aud")):
        assert verify_gmail_webhook("Bearer wrong.aud.token") is False


def test_wrong_email_rejected():
    # Validly-signed Google token, but NOT from the Pub/Sub publisher SA.
    claims = dict(GOOD_CLAIMS, email="attacker@evil.example")
    with _patch_verify(return_value=claims):
        assert verify_gmail_webhook("Bearer x") is False


def test_email_not_verified_rejected():
    claims = dict(GOOD_CLAIMS, email_verified=False)
    with _patch_verify(return_value=claims):
        assert verify_gmail_webhook("Bearer x") is False


def test_wrong_issuer_rejected():
    claims = dict(GOOD_CLAIMS, iss="https://accounts.evil.example")
    with _patch_verify(return_value=claims):
        assert verify_gmail_webhook("Bearer x") is False


# --- Rollout: shadow vs enforce (the stated risk — no silent pipeline breakage) ---


def _mock_request(auth: str = ""):
    req = MagicMock()
    req.headers.get.return_value = auth
    req.json = AsyncMock(return_value={})  # empty body → ignored before processing
    return req


async def test_handler_shadow_does_not_403(monkeypatch):
    """Shadow mode (default): a failed verdict logs but STILL processes — flipping
    the stub to the real verifier can't 403 the inbox before the OIDC audience is
    confirmed."""
    monkeypatch.setattr(gmail_route.settings, "GMAIL_WEBHOOK_ENFORCE", False)
    with patch.object(gmail_route, "verify_gmail_webhook", return_value=False):
        result = await gmail_route.gmail_webhook(_mock_request(""))
    assert result.get("ok") is True  # processed, not rejected


async def test_handler_enforce_403(monkeypatch):
    """Enforce mode (flipped on after a real push is seen passing): a failed
    verdict 403s."""
    monkeypatch.setattr(gmail_route.settings, "GMAIL_WEBHOOK_ENFORCE", True)
    with (
        patch.object(gmail_route, "verify_gmail_webhook", return_value=False),
        pytest.raises(HTTPException) as exc_info,
    ):
        await gmail_route.gmail_webhook(_mock_request(""))
    assert exc_info.value.status_code == 403


async def test_handler_valid_processes_in_both_modes(monkeypatch):
    """A valid verdict always processes, enforce on or off."""
    for enforce in (True, False):
        monkeypatch.setattr(gmail_route.settings, "GMAIL_WEBHOOK_ENFORCE", enforce)
        with patch.object(gmail_route, "verify_gmail_webhook", return_value=True):
            result = await gmail_route.gmail_webhook(_mock_request("Bearer good"))
        assert result.get("ok") is True
