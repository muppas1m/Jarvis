"""
API router aggregator.

Mounted under `/api` by main.py. Two tiers:

  PUBLIC routers — no auth dependency:
    - health       (uptime probes, no auth possible)
    - webhooks/*   (each receiver verifies its own provider HMAC)

  PROTECTED routers — gated by Depends(get_current_user):
    - chat, approvals, memory, costs    (Turn 12b)

Turn 12a ships the public tier + the auth dependency itself. Turn 12b
mounts the protected tier under a sub-router with the auth dependency
attached at router-level so individual endpoints don't have to repeat
it.
"""
from fastapi import APIRouter, Depends

from app.api.health import router as health_router
from app.api.webhooks.telegram import router as telegram_webhook_router
from app.security.auth import UserContext, get_current_user

api_router = APIRouter()

# --- public ---------------------------------------------------------------
api_router.include_router(health_router)
api_router.include_router(telegram_webhook_router)

# --- protected ------------------------------------------------------------
# All routes mounted here inherit Depends(get_current_user) at the
# router level — individual endpoints don't need to repeat it. Turn 12b
# adds chat / approvals / memory / costs under this same protected router.
protected_router = APIRouter(dependencies=[Depends(get_current_user)])


@protected_router.get("/_auth/whoami", tags=["auth"])
async def whoami(user: UserContext = Depends(get_current_user)) -> dict:
    """Smoke endpoint — confirms a request authenticated cleanly. Returns
    which credential type passed (api_key vs jwt) and the resolved user_id.
    Useful for verifying both auth paths during 12a smoke and any future
    auth changes."""
    return {"user_id": user.user_id, "auth_method": user.auth_method}


api_router.include_router(protected_router)
