"""
In-process runtime stats for the dashboard (4.C.2): process uptime + a real
turn counter. Deliberately cheap — module-level ints, no DB query per poll —
read by GET /api/system.

Scope + honesty caveats (disclosed, not hidden):
  - Counts turns seen by THIS process. The web backend and the Celery worker are
    separate processes, so Telegram/Gmail turns handled by Celery are not counted
    here — this gauges the web backend's own activity.
  - `today_turns` resets on process restart (it's turns-this-process-saw-today,
    not a DB-backed all-of-today total) — consistent with `uptime_s` being
    "since restart". A mid-day restart therefore undercounts today_turns.

Single-threaded asyncio in the web process, so the increment is atomic (no await
inside record_turn) — no lock needed.
"""
import time
from datetime import datetime, timezone

_started_at: float | None = None
_session_turns = 0
_today_key = ""
_today_turns = 0


def mark_started() -> None:
    """Stamp process start. Called once from the FastAPI lifespan; idempotent."""
    global _started_at
    if _started_at is None:
        _started_at = time.time()


def record_turn() -> None:
    """One increment per agent turn — called at each runner entry point."""
    global _session_turns, _today_turns, _today_key
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _session_turns += 1
    if today != _today_key:
        _today_key = today
        _today_turns = 0
    _today_turns += 1


def get_stats() -> dict[str, float | int]:
    start = _started_at if _started_at is not None else time.time()
    return {
        "uptime_s": max(0.0, time.time() - start),
        "session_turns": _session_turns,
        "today_turns": _today_turns,
    }
