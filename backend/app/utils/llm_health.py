"""
Passive LLM-call health (4.C.3) — zero token cost.

The 4.C.2 Brain probe was config-presence only, so a real Groq rate-limit/outage
still showed green. This module is the fix: the gateway + the agent's
FallbackChatLLM record each PRIMARY call's outcome here, and `_check_brain` reads
it — so a struggling primary provider finally turns Brain amber/red.

We record the PRIMARY attempt only (not the cross-provider fallback recovery) on
purpose: when Groq is degraded but the OpenAI fallback keeps the agent working,
the master should still SEE that the primary brain is struggling — that's the
signal. One success clears it (recovery). Cheap module ints, no DB.
"""

# After this many CONSECUTIVE primary failures, Brain is "down" (red); 1–2 is
# "degraded" (amber). A single success resets to "ok".
_DOWN_THRESHOLD = 3

_consecutive_failures = 0
_total_calls = 0


def record_llm_result(ok: bool) -> None:
    """Record one primary LLM-call outcome. Called from the gateway + FallbackChatLLM."""
    global _consecutive_failures, _total_calls
    _total_calls += 1
    if ok:
        _consecutive_failures = 0
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


def _reset_for_test() -> None:
    """Test-only hook to clear the counters."""
    global _consecutive_failures, _total_calls
    _consecutive_failures = 0
    _total_calls = 0
