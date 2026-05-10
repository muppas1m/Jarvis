"""
Read-only memory inspector endpoints.

Used by the dashboard's /memory page (Phase 4) to let the master see
what's in their long-term memory and what their profile looks like. Also
useful for debugging — `curl /api/memory/search?q=...` is the fastest way
to verify Mem0 is finding what you'd expect.

These are read-only on purpose. Profile mutations happen via the agent's
own update flows (memory consolidation Celery job, in-conversation profile
updates), not directly through HTTP.
"""
from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.memory.manager import MemoryManager

router = APIRouter(prefix="/memory", tags=["memory"])

_memory = MemoryManager()


class MemoryHit(BaseModel):
    id: str
    content: str
    score: float
    metadata: dict


class ProfileResponse(BaseModel):
    always_on: dict
    on_demand_keys: list[str]


@router.get("/search", response_model=list[MemoryHit])
async def search_memory(
    q: str = Query(..., min_length=1, description="Free-text search query"),
    k: int = Query(10, ge=1, le=50, description="Max results"),
) -> list[MemoryHit]:
    """Semantic search over Mem0."""
    hits = await _memory.recall(q, thread_id=None, k=k)
    # `recall` already returns the right shape — coerce to MemoryHit so
    # FastAPI emits a clean schema in the OpenAPI doc.
    return [MemoryHit(**h) for h in hits]


@router.get("/profile", response_model=ProfileResponse)
async def get_profile() -> ProfileResponse:
    """Return the master's profile (always-on slice + the keys present in
    on-demand). Full on-demand sections are intentionally NOT returned in
    bulk — fetch by key via a future endpoint if needed."""
    return ProfileResponse(
        always_on=await _memory.get_always_on(),
        on_demand_keys=await _memory.list_on_demand_keys(),
    )
