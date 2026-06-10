"""Turn 17.9 smoke — observability + reasoning lifts (p/q/q2/q3/s).

Deterministic checks where they fit:
  - stop_reason (q3): derived per exit path, consistent with status, every path
    covered. Tests the pure helpers + the error-envelope pairing.
  - q2: the args-override warning fires (and ONLY) on an args escalation.
  - latency (s): _log_audit writes latency_ms; the approval-lifecycle default is None.
  - calendar descriptions (p): the "does NOT" half + sibling cross-ref + an example.

The KV-cache stability of the SAFETY_DOCTRINE change (q) is covered by the existing
pytest `tests/test_prompt_cache_stability.py` — run that separately.

Self-cleaning. Run inside the container:

    docker compose exec -T backend python scripts/smoke_observability.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app.agent.runner import (  # noqa: E402
    _error_envelope,
    _stop_reason_for_completion,
    _stop_reason_for_error,
)
from app.agent.safety import SafetyClassifier, SafetyLevel  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.engine import async_session  # noqa: E402
from app.db.models import AuditTrail  # noqa: E402
from app.utils.exceptions import CostCapExceededError  # noqa: E402
from app.utils.logging import configure_logging  # noqa: E402

_SMOKE_THREAD = "smoke-obs-thread"


def _check_stop_reason(failures: list[str]) -> None:
    print("=== stop_reason per exit path (q3) ===")
    cases = [
        ("completion natural", _stop_reason_for_completion({"final_response": "hi there"}), "end_turn"),
        ("completion empty", _stop_reason_for_completion({}), "end_turn"),
        ("completion rate-limited", _stop_reason_for_completion({"final_response": "rate_limited"}), "rate_limit"),
        ("error cost-cap", _stop_reason_for_error(CostCapExceededError("cap")), "cost_cap"),
        ("error generic", _stop_reason_for_error(ValueError("boom")), "error"),
    ]
    for label, got, want in cases:
        print(f"  {label}: {got}")
        if got != want:
            failures.append(f"stop_reason: {label} expected {want}, got {got}")
    # status↔stop_reason can't disagree: every error-envelope stop_reason pairs with status=error.
    for sr in ("error", "cost_cap"):
        env = _error_envelope("t", "msg", stop_reason=sr)
        if env["status"] != "error" or env["stop_reason"] != sr:
            failures.append(f"stop_reason: error envelope inconsistent for {sr}: {env['status']}/{env['stop_reason']}")


def _check_args_override_warning(failures: list[str]) -> None:
    print("=== safety args-override warning (q2) ===")
    clf = SafetyClassifier()
    non_master = "999999999"  # distinct from any real master chat id
    # capture_logs reconfigures structlog before safety's logger is first USED,
    # so the warning is captured despite cache_logger_on_first_use.
    with structlog.testing.capture_logs() as captured:
        escalated = clf.classify("telegram_send", {"chat_id": non_master})
    events = [e for e in captured if e.get("event") == "safety_args_override_escalated"]
    print(f"  non-master telegram_send -> {escalated.value}; warnings={len(events)}")
    if escalated != SafetyLevel.APPROVE:
        failures.append(f"q2: non-master telegram_send should escalate to APPROVE, got {escalated}")
    if not events:
        failures.append("q2: no safety_args_override_escalated warning captured on escalation")
    elif events[-1].get("to_level") != "approve" or not events[-1].get("override_reason"):
        failures.append(f"q2: warning missing to_level/override_reason: {events[-1]}")

    # No escalation, no warning: empty chat_id is the master-path NOTIFY (no bump).
    with structlog.testing.capture_logs() as captured2:
        base = clf.classify("telegram_send", {"chat_id": ""})
    if base != SafetyLevel.NOTIFY:
        failures.append(f"q2: empty chat_id should stay NOTIFY, got {base}")
    if any(e.get("event") == "safety_args_override_escalated" for e in captured2):
        failures.append("q2: warning fired without an escalation")


async def _check_latency_write(failures: list[str]) -> None:
    print("=== _log_audit writes latency_ms (s) ===")
    from app.agent.nodes import _log_audit

    await _log_audit(_SMOKE_THREAD, "smoke_tool", SafetyLevel.SAFE, {"a": 1}, success=True, latency_ms=137)
    await _log_audit(_SMOKE_THREAD, "smoke_blocked", SafetyLevel.SAFE, {}, success=False, error="X")  # no latency

    async with async_session() as session:
        rows = (await session.execute(
            select(AuditTrail.tool_name, AuditTrail.latency_ms).where(AuditTrail.thread_id == _SMOKE_THREAD)
        )).all()
    by_tool = {r.tool_name: r.latency_ms for r in rows}
    print(f"  latencies: {by_tool}")
    if by_tool.get("smoke_tool") != 137:
        failures.append(f"s: executed-tool latency_ms should be 137, got {by_tool.get('smoke_tool')}")
    if by_tool.get("smoke_blocked") is not None:
        failures.append(f"s: non-dispatch row latency_ms should be None, got {by_tool.get('smoke_blocked')}")


def _check_calendar_descriptions(failures: list[str]) -> None:
    print("=== calendar tool descriptions (p) ===")
    from app.agent.tools import calendar_tool
    from app.agent.tools.registry import tool_registry

    calendar_tool.register()
    read_desc = tool_registry.get_tool_object("calendar_read").description
    create_desc = tool_registry.get_tool_object("calendar_create").description

    if "does not" not in read_desc.lower():
        failures.append("p: calendar_read missing 'does NOT' boundary language")
    if "calendar_create" not in read_desc:
        failures.append("p: calendar_read missing cross-reference to calendar_create")
    if "conflict" not in read_desc.lower() or "timezone" not in read_desc.lower():
        failures.append("p: calendar_read should name the missing enrichments (conflicts/timezones)")

    if "does not" not in create_desc.lower():
        failures.append("p: calendar_create missing 'does NOT' boundary language")
    if "calendar_read" not in create_desc:
        failures.append("p: calendar_create missing cross-reference to calendar_read")
    if "event_id" not in create_desc or "meet" not in create_desc.lower():
        failures.append("p: calendar_create should name the missing enrichments (event_id / Meet link)")
    if "@" not in create_desc:
        failures.append("p: calendar_create should include an example with an attendee")
    print("  calendar_read + calendar_create carry does-NOT + cross-ref + example")


async def _cleanup() -> None:
    async with async_session() as session:
        await session.execute(delete(AuditTrail).where(AuditTrail.thread_id == _SMOKE_THREAD))
        await session.commit()


async def main() -> int:
    configure_logging()
    failures: list[str] = []
    _check_stop_reason(failures)
    _check_args_override_warning(failures)
    _check_calendar_descriptions(failures)
    try:
        await _check_latency_write(failures)
    finally:
        await _cleanup()
        print("=== cleanup === removed smoke audit rows")

    print()
    if failures:
        print(f"FAIL: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: stop_reason consistent per exit path, q2 warning fires, latency written, calendar honest")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
