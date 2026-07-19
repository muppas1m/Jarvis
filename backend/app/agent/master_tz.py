"""B1-TZ (D-B1-9) — ONE resolved timezone per turn, threaded into every sync render.

The async/sync crux: `_resolve_timezone` is async (a profile read); the render functions
(`describe_card`/`_human_time`) are sync, called from sync resolution paths. So the TZ is
resolved ONCE at each async turn entry (`resolve_and_bind`) and read sync (`current_tz`)
everywhere below.

The ContextVar is bound BEFORE graph invocation — safe against the node-boundary lesson
(B1-brief-2): `copy_context` copies parent values into every node, so a pre-graph bind is
readable in all nodes; the fatal pattern (SET in one node, READ in another) is never used here.

Unbound (a surface that forgot to bind, or a non-turn context) → the flagged default —
fail-VISIBLE, never a silently-wrong time.
"""
from __future__ import annotations

from contextvars import ContextVar

from app.agent.tools.calendar_tool import _resolve_timezone
from app.config import settings

_master_tz: ContextVar[tuple[str, bool] | None] = ContextVar("master_tz", default=None)


async def resolve_and_bind() -> tuple[str, bool]:
    """Resolve the master's TZ (column → legacy always_on → flagged default) and bind it for
    this turn. Called at every async entry that renders times (run/stream/voice)."""
    resolved = await _resolve_timezone("")
    _master_tz.set(resolved)
    return resolved


def current_tz() -> tuple[str, bool]:
    """The turn's resolved (tz_name, fallback) — sync, for the render layer."""
    return _master_tz.get() or (settings.DEFAULT_TIMEZONE, True)
