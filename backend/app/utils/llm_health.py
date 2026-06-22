"""
Passive LLM-call health (4.C.3) — zero token cost.

FUNCTIONAL health, not provider health (4.C.3-fix). The gateway + the agent's
FallbackChatLLM call `record_llm_result` once per call at the point the FINAL
outcome is known — `ok=True` if the agent got an answer by ANY path (primary OR
fallback), `ok=False` only when it genuinely couldn't answer (every path failed).

So a handled Groq rate-limit (primary fails, fallback answers) leaves Brain
GREEN — Jarvis is working — and only a both-paths failure drives it amber/red.
The earlier "record the primary attempt" version false-degraded the ring on the
free tier's frequent rate-limits even while the fallback answered fine.

`via_fallback` carries the subtle "primary degraded, running on backup" hint —
surfaced as a member-name note in the health ring, NEVER the ring colour. Cheap
module ints, no DB.
"""

# After this many CONSECUTIVE genuine failures (no path answered), Brain is
# "down" (red); 1–2 is "degraded" (amber). A single answered call resets to ok.
_DOWN_THRESHOLD = 3

_consecutive_failures = 0
_total_calls = 0
_on_fallback = False  # did the most recent answered call come via the fallback?


def record_llm_result(ok: bool, via_fallback: bool = False) -> None:
    """Record one call's FINAL outcome (after any fallback hop).

    ok=True  → the agent answered (by primary or fallback). via_fallback flags
               that only the fallback covered it (primary degraded).
    ok=False → no path answered → a genuine brain failure.
    """
    global _consecutive_failures, _total_calls, _on_fallback
    _total_calls += 1
    if ok:
        _consecutive_failures = 0
        _on_fallback = via_fallback
    else:
        _consecutive_failures += 1


def brain_status() -> str:
    """'unknown' (no calls yet this process) | 'ok' | 'degraded' | 'down'."""
    if _total_calls == 0:
        return "unknown"
    if _consecutive_failures == 0:
        return "ok"
    if _consecutive_failures >= _DOWN_THRESHOLD:
        return "down"
    return "degraded"


def primary_degraded() -> bool:
    """True when the agent IS answering but only via the fallback (primary
    provider degraded) — the subtle secondary hint, not a ring alarm."""
    return _on_fallback


def _reset_for_test() -> None:
    """Test-only hook to clear the counters."""
    global _consecutive_failures, _total_calls, _on_fallback
    _consecutive_failures = 0
    _total_calls = 0
    _on_fallback = False
