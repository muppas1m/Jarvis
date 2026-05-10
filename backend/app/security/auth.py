"""
Auth dependency — dual path, single FastAPI dependency.

Two ways to authenticate against the API in Phase 1:

  1. X-API-Key: <static>            constant-time HMAC compare against
                                    API_SECRET_KEY. Identity is hardcoded
                                    to user_id="master" — there's only one
                                    user in this system. Used by curl, cron,
                                    scripts, and any non-browser client.

  2. Authorization: Bearer <jwt>    Auth.js-issued JWT (HS256 signed with
                                    AUTH_SECRET). Identity comes from the
                                    `sub` claim. Used by the Phase 4 web
                                    dashboard once it lands.

Either succeeds; otherwise 401. Never both — first one present wins so
clients don't accidentally compose mismatched headers.

Phase 4 swap notes:
  - Auth.js v5 default session token is a JWE (encrypted JWT) using
    A256CBC-HS512, NOT a signed JWT. When the dashboard ships, either:
    (a) configure Auth.js to use HS256 JWT (`session.strategy = "jwt"`
        with `jwt.encryption: false`, or pass a custom encode/decode) and
        keep this validator, or
    (b) replace `_verify_jwt` here with a JWE decryption path (jose
        supports it; just need the same AUTH_SECRET as the dir-mode key).
  - The X-API-Key path stays as the fallback / scripting credential
    indefinitely. Rotate it manually when needed — there's no per-key
    rotation infrastructure planned for Phase 1.
"""
import hmac
from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from jose import JWTError, jwt

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class UserContext:
    """What every authenticated request carries.

    Phase 1: always the master. Phase 4: still always the master, but
    `auth_method` lets us tell dashboard sessions apart from scripted
    callers in audit logs."""

    user_id: str
    auth_method: str  # "api_key" | "jwt"


def _verify_api_key(presented: str) -> bool:
    """Constant-time compare against API_SECRET_KEY.

    Returns False if the secret isn't configured — defense against an
    empty .env value silently authorizing every request."""
    expected = settings.API_SECRET_KEY
    if not expected:
        return False
    return hmac.compare_digest(presented.encode("utf-8"), expected.encode("utf-8"))


def _verify_jwt(token: str) -> Optional[dict]:
    """HS256 verify against AUTH_SECRET. Returns claims dict or None.

    Phase 1 placeholder: works for any HS256 JWT we mint ourselves
    (scripts/issue_jwt.py is the canonical issuer). Phase 4 either keeps
    this if the Auth.js setup is HS256, or swaps to JWE decryption."""
    if not settings.AUTH_SECRET:
        return None
    try:
        return jwt.decode(
            token,
            settings.AUTH_SECRET,
            algorithms=["HS256"],
            # No audience check in Phase 1 — single-tenant, single-issuer.
            options={"verify_aud": False},
        )
    except JWTError as exc:
        logger.warning("jwt_verify_failed", error=str(exc))
        return None


async def get_current_user(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> UserContext:
    """FastAPI dependency. Use as: `Depends(get_current_user)` on protected
    routes, or `dependencies=[Depends(get_current_user)]` on a router.

    Raises HTTPException(401) on missing/invalid credentials."""
    # API key first — cheaper to verify and the more common Phase 1 path.
    if x_api_key:
        if _verify_api_key(x_api_key):
            return UserContext(user_id="master", auth_method="api_key")
        # Don't fall through to JWT — mismatched X-API-Key is suspicious,
        # not a "try the other one" scenario.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid api key",
        )

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        claims = _verify_jwt(token)
        if claims and claims.get("sub"):
            return UserContext(user_id=claims["sub"], auth_method="jwt")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="authentication required (X-API-Key or Authorization: Bearer)",
        headers={"WWW-Authenticate": "Bearer"},
    )


CurrentUser = Depends(get_current_user)
