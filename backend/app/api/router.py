"""
API router aggregator.

Mounted under `/api` by main.py. Two tiers:

  PUBLIC routers — no auth dependency:
    - health       (uptime probes, no auth possible)
    - webhooks/*   (each receiver verifies its own provider HMAC)

  PROTECTED routers — gated by Depends(get_current_user):
    - chat, approvals, memory, costs    (Turn 12b)
    - documents                         (Turn 20 — upload/search the RAG corpus)

Turn 12a ships the public tier + the auth dependency itself. Turn 12b
mounts the protected tier under a sub-router with the auth dependency
attached at router-level so individual endpoints don't have to repeat
it.
"""
from fastapi import APIRouter, Depends

from app.api.approvals import router as approvals_router
from app.api.chat import router as chat_router
from app.api.costs import router as costs_router
from app.api.documents import router as documents_router
from app.api.health import router as health_router
from app.api.memory import router as memory_router
from app.api.system import router as system_router
from app.api.voice import router as voice_router
from app.api.voice import ws_router as voice_ws_router
from app.api.webhooks.gmail import router as gmail_webhook_router
from app.api.webhooks.telegram import router as telegram_webhook_router
from app.security.auth import UserContext, get_current_user

api_router = APIRouter()

# --- public ---------------------------------------------------------------
api_router.include_router(health_router)
api_router.include_router(telegram_webhook_router)
api_router.include_router(gmail_webhook_router)
# Wake-word WS — self-authenticates on a short-lived JWT ticket (a browser WS
# can't carry the X-API-Key header the protected tier expects). See voice.wake_ws.
api_router.include_router(voice_ws_router)

# --- protected ------------------------------------------------------------
# All routes mounted here inherit Depends(get_current_user) at the
# router level — individual endpoints don't need to repeat it.
protected_router = APIRouter(dependencies=[Depends(get_current_user)])


@protected_router.get("/_auth/whoami", tags=["auth"])
async def whoami(user: UserContext = Depends(get_current_user)) -> dict:
    """Smoke endpoint — confirms a request authenticated cleanly. Returns
    which credential type passed (api_key vs jwt) and the resolved user_id.
    Useful for verifying both auth paths and any future auth changes."""
    return {"user_id": user.user_id, "auth_method": user.auth_method}


protected_router.include_router(chat_router)
protected_router.include_router(voice_router)
protected_router.include_router(approvals_router)
protected_router.include_router(memory_router)
protected_router.include_router(costs_router)
protected_router.include_router(documents_router)
protected_router.include_router(system_router)

api_router.include_router(protected_router)
