"""Actionable-memory tools (Phase 4.1) — the task-list foundation.

Discriminates the status lifecycle (open → done/dropped, resolved_at stamped),
the content-match behaviour (unique / none / ambiguous), the PRIORITY ELICITATION
contract (required low|medium|high enum), and the RECALL ROUTING (descriptions
cross-reference memory_search / email_history_search so task-recall lands here).

Real DB; each test tags its rows with a unique marker and cleans them up.
"""
import uuid

import pydantic
import pytest
from sqlalchemy import delete, select

import app.agent.tools.actionable_tool as T
from app.db.engine import async_session
from app.db.models import ActionableItem


async def _rows(tag: str):
    async with async_session() as s:
        return (await s.execute(
            select(ActionableItem).where(ActionableItem.content.ilike(f"%{tag}%"))
        )).scalars().all()


async def _cleanup(tag: str):
    async with async_session() as s:
        await s.execute(delete(ActionableItem).where(ActionableItem.content.ilike(f"%{tag}%")))
        await s.commit()


# --- status lifecycle --------------------------------------------------------
async def test_add_creates_open_with_priority_and_due():
    tag = uuid.uuid4().hex[:8]
    try:
        out = await T.task_add(content=f"renew licence {tag}", priority="high", due_date="2026-07-15")
        assert "Recorded" in out and "high" in out and "2026-07-15" in out
        rows = await _rows(tag)
        assert len(rows) == 1
        r = rows[0]
        assert r.status == "open" and r.priority == "high"
        assert r.due_date.isoformat() == "2026-07-15"
        assert r.resolved_at is None
    finally:
        await _cleanup(tag)


async def test_add_rejects_bad_due_date_and_creates_nothing():
    tag = uuid.uuid4().hex[:8]
    try:
        out = await T.task_add(content=f"thing {tag}", priority="low", due_date="next friday")
        assert "couldn't read" in out.lower()
        assert await _rows(tag) == []  # a bad date creates NO row (clean data)
    finally:
        await _cleanup(tag)


async def test_complete_transitions_open_to_done_and_stamps_resolved():
    tag = uuid.uuid4().hex[:8]
    try:
        await T.task_add(content=f"call dentist {tag}", priority="medium")
        out = await T.task_complete(task=f"dentist {tag}")
        assert "Marked done" in out
        r = (await _rows(tag))[0]
        assert r.status == "done" and r.resolved_at is not None
    finally:
        await _cleanup(tag)


async def test_drop_transitions_to_dropped_and_stamps_resolved():
    tag = uuid.uuid4().hex[:8]
    try:
        await T.task_add(content=f"old errand {tag}", priority="low")
        out = await T.task_drop(task=f"errand {tag}")
        assert "Dropped" in out
        r = (await _rows(tag))[0]
        assert r.status == "dropped" and r.resolved_at is not None
    finally:
        await _cleanup(tag)


async def test_list_filters_by_status():
    tag = uuid.uuid4().hex[:8]
    try:
        await T.task_add(content=f"open one {tag}", priority="high")
        await T.task_add(content=f"will finish {tag}", priority="low")
        await T.task_complete(task=f"will finish {tag}")
        open_out = await T.task_list(status="open")
        assert f"open one {tag}" in open_out
        assert f"will finish {tag}" not in open_out  # done → excluded from the open list
        done_out = await T.task_list(status="done")
        assert f"will finish {tag}" in done_out
    finally:
        await _cleanup(tag)


# --- content-match behaviour: unique / none / ambiguous ----------------------
async def test_complete_no_match_changes_nothing():
    out = await T.task_complete(task=f"nonexistent-{uuid.uuid4().hex}")
    assert "don't see an open task" in out.lower()


async def test_complete_ambiguous_asks_and_changes_nothing():
    tag = uuid.uuid4().hex[:8]
    try:
        await T.task_add(content=f"call mom {tag}", priority="low")
        await T.task_add(content=f"email mom {tag}", priority="low")
        out = await T.task_complete(task=tag)  # the tag matches BOTH → ambiguous
        assert "which one" in out.lower()
        rows = await _rows(tag)
        assert all(r.status == "open" for r in rows)  # nothing transitioned
    finally:
        await _cleanup(tag)


# --- the elicitation contract: priority REQUIRED (schema) + valid value (handler) ---
def test_priority_required_at_schema_but_plain_str_no_enum():
    # priority is REQUIRED — the agent must supply it (i.e. ask first, not omit).
    with pytest.raises(pydantic.ValidationError):
        T._TaskAddArgs(content="x")
    # but it's a PLAIN STRING (no Literal/enum constraint — open-weights-friendly):
    # any string passes the schema; the VALUE is validated in the handler.
    assert T._TaskAddArgs(content="x", priority="high").priority == "high"
    assert T._TaskAddArgs(content="x", priority="urgent").priority == "urgent"  # schema accepts it


async def test_off_enum_priority_rejected_in_handler_creates_nothing():
    tag = uuid.uuid4().hex[:8]
    try:
        out = await T.task_add(content=f"thing {tag}", priority="urgent")
        # rejected at the handler with the helpful low/medium/high message
        assert all(w in out.lower() for w in ("low", "medium", "high"))
        assert await _rows(tag) == []  # off-enum priority → no row
    finally:
        await _cleanup(tag)


async def test_off_enum_status_rejected_in_handler():
    out = await T.task_list(status="archived")
    assert all(w in out.lower() for w in ("open", "done", "dropped"))


# --- the recall-routing contract (descriptions cross-reference) -------------
def test_descriptions_route_task_recall_to_task_list_not_memory():
    import app.agent.tools.builtin_memory as M
    from app.agent.tools.registry import tool_registry

    T.register()
    M.register()
    task_list_desc = tool_registry._entries["task_list"].description.lower()
    mem_desc = tool_registry._entries["memory_search"].description.lower()

    # task_list IS the to-do list, and routes other recall elsewhere
    assert "what's on my list" in task_list_desc
    assert "does not search conversation memory" in task_list_desc
    assert "email_history_search" in task_list_desc
    # memory_search routes to-dos AWAY to task_list
    assert "task_list" in mem_desc and ("to-do" in mem_desc or "task" in mem_desc)
