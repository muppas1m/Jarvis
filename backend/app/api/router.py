"""
API router aggregator — STUB.

main.py mounts this under `/api`. Turn 12 fleshes it out with chat,
webhooks, approvals, health, memory, news, documents, and costs sub-
routers. For now the aggregator carries only a single liveness endpoint
so the backend container can start cleanly and serve health checks while
the messaging-layer (Telegram polling) does its thing in the background.
"""
from fastapi import APIRouter

api_router = APIRouter()


@api_router.get("/health", tags=["health"])
async def health() -> dict:
    """Liveness probe. Real /health with DB + checkpointer + Langfuse status
    lands in Turn 12 / Task 1.15. For now just confirms the FastAPI app is up."""
    return {"status": "ok"}
