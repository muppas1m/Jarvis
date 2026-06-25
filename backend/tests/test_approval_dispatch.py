"""Phase 3 Step 1 — the generic execute-on-approve dispatcher + the claim's
expiry/double-fire gate, tested in isolation (decide_approval NOT yet rewired).

Seeds REAL PendingApproval rows. Mocks only execute_tool_guarded (the tool
execution boundary) and dispatch_email_approval (to assert routing without
re-running the email path). Proves: a tool row executes via the guarded core; a
reject doesn't execute; a now-BLOCKED tool is refused; a missing row is handled;
an email row routes to the untouched email handler; an expired row can't be
claimed; the atomic claim gates dispatch so a double-fire executes once.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete

from app.agent.approval_dispatch import dispatch_approval
from app.agent.nodes import ToolExecResult
from app.agent.safety import SafetyLevel
from app.api.approvals import resolve_approval
from app.db.engine import async_session
from app.db.models import PendingApproval
from app.email.approval_handler import EmailApprovalOutcome


async def _seed_tool(action_type="calendar_create", tool_args=None, expires_min=60) -> str:
    aid = uuid.uuid4()
    async with async_session() as s:
        s.add(PendingApproval(
            id=aid, thread_id="web:master", interrupt_id=str(uuid.uuid4()),
            action_type=action_type, description=f"{action_type} approval",
            payload={"tool_name": action_type, "tool_args": tool_args or {"summary": "Lunch"}},
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_min),
        ))
        await s.commit()
    return str(aid)


async def _seed_email(expires_min=60) -> str:
    aid = uuid.uuid4()
    mid = f"disp-{uuid.uuid4().hex[:8]}"
    async with async_session() as s:
        s.add(PendingApproval(
            id=aid, thread_id=f"email:gmail:{mid}", interrupt_id=f"email:gmail:{mid}",
            action_type="email_reply", description="reply",
            payload={"provider": "gmail", "message_id": mid, "sender": "b@x.com",
                     "subject": "Hi", "draft": "ok", "rfc822_message_id": "<x>", "thread_ref": ""},
            expires_at=datetime.now(UTC) + timedelta(minutes=expires_min),
        ))
        await s.commit()
    return str(aid)


async def _cleanup(approval_id: str):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.id == uuid.UUID(approval_id)))
        await s.commit()


def _mock_exec(monkeypatch, rec):
    async def fake_exec(thread_id, tool_name, tool_args, *, level, tool_call_id=""):
        rec.setdefault("n", 0)
        rec["n"] += 1
        rec["args"] = (thread_id, tool_name, tool_args, level)
        return ToolExecResult(content="Event created", success=True, error=None, latency_ms=5)

    monkeypatch.setattr("app.agent.nodes.execute_tool_guarded", fake_exec)


async def test_dispatch_executes_tool_via_guarded(monkeypatch):
    aid = await _seed_tool("calendar_create", {"summary": "Lunch", "start_iso": "2026-07-01T12:00"})
    rec: dict = {}
    _mock_exec(monkeypatch, rec)
    try:
        outcome = await dispatch_approval(aid, {"approved": True})
        assert outcome.kind == "tool" and outcome.status == "executed"
        assert outcome.detail == "Event created" and outcome.success
        tid, tname, targs, level = rec["args"]
        assert tid == "web:master" and tname == "calendar_create" and targs["summary"] == "Lunch"
        assert level == SafetyLevel.APPROVE  # classified APPROVE → executed via the guard
    finally:
        await _cleanup(aid)


async def test_dispatch_reject_does_not_execute(monkeypatch):
    aid = await _seed_tool()
    rec: dict = {}
    _mock_exec(monkeypatch, rec)
    try:
        outcome = await dispatch_approval(aid, {"approved": False})
        assert outcome.kind == "tool" and outcome.status == "rejected"
        assert "n" not in rec  # the tool was NEVER executed on reject
    finally:
        await _cleanup(aid)


async def test_dispatch_now_blocked_tool_refused(monkeypatch):
    """Defense-in-depth: a tool that's since become BLOCKED must not execute on
    approve — safety still gates (invariant 5)."""
    aid = await _seed_tool("calendar_create")
    rec: dict = {}
    _mock_exec(monkeypatch, rec)
    import app.agent.approval_dispatch as ad
    monkeypatch.setattr(ad._safety, "classify", lambda n, a: SafetyLevel.BLOCKED)
    try:
        outcome = await dispatch_approval(aid, {"approved": True})
        assert outcome.status == "blocked"
        assert "n" not in rec  # refused → not executed
    finally:
        await _cleanup(aid)


async def test_dispatch_missing_row(monkeypatch):
    rec: dict = {}
    _mock_exec(monkeypatch, rec)
    outcome = await dispatch_approval(str(uuid.uuid4()), {"approved": True})
    assert outcome.status == "row_missing" and "n" not in rec


async def test_dispatch_email_row_routes_to_email_handler_untouched(monkeypatch):
    aid = await _seed_email()
    routed: dict = {}
    rec: dict = {}
    _mock_exec(monkeypatch, rec)

    async def fake_email(thread_id, decision, *, approval_id=None):
        routed["thread_id"] = thread_id
        routed["approval_id"] = approval_id
        return EmailApprovalOutcome(status="sent", recipient="b@x.com", subject="Re: Hi", detail="id=1")

    monkeypatch.setattr("app.agent.approval_dispatch.dispatch_email_approval", fake_email)
    try:
        outcome = await dispatch_approval(aid, {"approved": True})
        assert outcome.kind == "email" and outcome.status == "sent"
        assert outcome.email_outcome is not None  # carries the taxonomy outcome (Step 2 renders it)
        assert routed["thread_id"].startswith("email:gmail:")
        assert routed["approval_id"] == aid  # the SPECIFIC row is passed (revise-safe, not thread_id)
        assert "n" not in rec  # the TOOL path was NOT taken — email handler untouched
    finally:
        await _cleanup(aid)


async def test_resolve_claim_rejects_expired_row():
    """Invariant 7: an expired (but not-yet-swept) row can't be claimed → can't
    execute. The claim's atomic WHERE includes expires_at > now()."""
    aid = await _seed_tool("calendar_create", expires_min=-1)  # already expired
    try:
        assert await resolve_approval(aid, "approve", "web") is None  # not claimed
    finally:
        await _cleanup(aid)


async def test_claim_gates_dispatch_executes_once(monkeypatch):
    """Invariant 1: the atomic claim gates dispatch — a double resolve claims once,
    so a well-behaved caller (skip dispatch on None) executes exactly once."""
    aid = await _seed_tool("calendar_create")
    rec: dict = {}
    _mock_exec(monkeypatch, rec)
    try:
        tid1 = await resolve_approval(aid, "approve", "web")
        assert tid1 is not None  # first wins the claim
        await dispatch_approval(aid, {"approved": True})

        tid2 = await resolve_approval(aid, "approve", "voice")
        assert tid2 is None  # second loses (already approved) → caller skips dispatch
        # the only dispatch that ran was the first; exactly one execution
        assert rec["n"] == 1
    finally:
        await _cleanup(aid)
