"""
Actionable-memory tools (Phase 4.1) — the master's task list.

task_add / task_list / task_complete / task_drop CRUD the `actionable_items`
table: open tasks with an elicited priority + an optional due date. This is the
foundation readiness intelligence (4.3) aggregates over a time period.

Two contracts beyond plain CRUD:
  - PRIORITY ELICITATION — `task_add`'s priority is a REQUIRED low|medium|high
    enum, and the description tells the agent to ASK when the master's words
    don't signal urgency rather than guess (reinforced by a system-prompt rule).
  - RECALL ROUTING — the descriptions cross-reference memory_search /
    email_history_search ("Does NOT search X; use Y") so a task-recall query
    ("what's on my list", "what do I need to do about X") routes HERE, not to
    memory_search (mirrors the memory/email cross-source disambiguation).

All four are SAFE tier (recording/listing/closing a task has no external side
effect) — see app.agent.safety.TOOL_SAFETY_MAP.
"""
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.tools.registry import tool_registry
from app.db.engine import async_session
from app.db.models import ActionableItem

_PRIORITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _fmt(item: ActionableItem) -> str:
    due = f", due {item.due_date.isoformat()}" if item.due_date else ""
    return f"- [{item.priority}] {item.content}{due}"


async def task_add(content: str, priority: Literal["low", "medium", "high"], due_date: str = "") -> str:
    """Record a new open task with an elicited priority + optional due date."""
    content = (content or "").strip()
    if not content:
        return "I need the task itself before I can record it, Sir."

    parsed_due: date | None = None
    if due_date.strip():
        try:
            parsed_due = date.fromisoformat(due_date.strip())
        except ValueError:
            return (
                f"I couldn't read the due date '{due_date}', Sir — give it to me as "
                f"YYYY-MM-DD (e.g. 2026-06-30) and I'll record the task."
            )

    async with async_session() as session:
        session.add(ActionableItem(content=content, priority=priority, due_date=parsed_due))
        await session.commit()

    due_txt = f", due {parsed_due.isoformat()}" if parsed_due else ""
    return f"Recorded, Sir: {content} ({priority} priority{due_txt})."


async def task_list(status: Literal["open", "done", "dropped"] = "open") -> str:
    """List the master's tasks of a given status (open by default), soonest-due first."""
    async with async_session() as session:
        rows = (await session.execute(
            select(ActionableItem).where(ActionableItem.status == status)
        )).scalars().all()

    if not rows:
        return f"No {status} tasks, Sir." if status != "open" else "Your list is clear, Sir — no open tasks."

    # Soonest-due first (no-due last), then higher priority, then oldest.
    rows = sorted(
        rows,
        key=lambda i: (i.due_date or date.max, -_PRIORITY_RANK.get(i.priority, 0), i.created_at),
    )
    header = "Your open tasks, Sir:" if status == "open" else f"Your {status} tasks, Sir:"
    return header + "\n" + "\n".join(_fmt(i) for i in rows)


async def _resolve_one(session, task: str) -> ActionableItem | list[ActionableItem]:
    """Find the single OPEN task whose content matches `task` (case-insensitive
    substring). Returns the item on a unique match, else the list of matches (0 or
    >1) so the caller can ask the master which one."""
    matches = (await session.execute(
        select(ActionableItem)
        .where(ActionableItem.status == "open")
        .where(ActionableItem.content.ilike(f"%{task.strip()}%"))
    )).scalars().all()
    return matches[0] if len(matches) == 1 else list(matches)


async def _close(task: str, *, new_status: str, verb: str) -> str:
    task = (task or "").strip()
    if not task:
        return "Which task, Sir?"
    async with async_session() as session:
        found = await _resolve_one(session, task)
        if isinstance(found, list):
            if not found:
                return f"I don't see an open task matching '{task}', Sir."
            listed = "\n".join(_fmt(i) for i in found)
            return f"Several open tasks match '{task}', Sir — which one?\n{listed}"
        found.status = new_status
        found.resolved_at = datetime.now(UTC)
        content = found.content
        await session.commit()
    return f"{verb}, Sir: {content}."


async def task_complete(task: str) -> str:
    """Mark an open task done (the master finished it)."""
    return await _close(task, new_status="done", verb="Marked done")


async def task_drop(task: str) -> str:
    """Drop an open task the master no longer needs to do (abandoned, not done)."""
    return await _close(task, new_status="dropped", verb="Dropped")


def register() -> None:
    tool_registry.register(
        name="task_add",
        handler=task_add,
        description=(
            "Record a task / to-do the master needs to act on, into their task list. "
            "PRIORITY IS REQUIRED (low | medium | high) — if the master's words don't "
            "clearly signal urgency, ASK 'what's the priority, Sir?' BEFORE calling; "
            "never guess it. Optional due_date as YYYY-MM-DD. "
            "Use for: 'remind me to X', 'I need to Y', 'add Z to my list', "
            "'don't let me forget W'."
        ),
        args_schema=_TaskAddArgs,
    )
    tool_registry.register(
        name="task_list",
        handler=task_list,
        description=(
            "List the master's tasks — their TO-DO list, the source of truth for what "
            "they need to act on (open by default; also done/dropped). "
            "Does NOT search conversation memory (use memory_search) or email "
            "(use email_history_search). "
            "Use for: 'what's on my list', 'what do I need to do', 'what do I need to "
            "do about X', 'my open tasks', 'anything outstanding'."
        ),
        args_schema=_TaskListArgs,
    )
    tool_registry.register(
        name="task_complete",
        handler=task_complete,
        description=(
            "Mark a task DONE when the master says they've finished it — matches an "
            "open task by its words. "
            "Use for: 'I did X', 'finished Y', 'X is done', 'completed Z'."
        ),
        args_schema=_TaskRefArgs,
    )
    tool_registry.register(
        name="task_drop",
        handler=task_drop,
        description=(
            "DROP / cancel a task the master no longer needs to do — abandoned, NOT "
            "done. Matches an open task by its words. "
            "Use for: 'forget about X', 'cancel Y', 'never mind Z', 'drop W'."
        ),
        args_schema=_TaskRefArgs,
    )


class _TaskAddArgs(BaseModel):
    content: str = Field(..., description="The task, in the master's own words.")
    priority: Literal["low", "medium", "high"] = Field(
        ...,
        description=(
            "REQUIRED urgency. If the master's words don't signal it, ASK "
            "'what's the priority, Sir?' first — do not guess."
        ),
    )
    due_date: str = Field(
        default="", description="Optional due date as YYYY-MM-DD; omit if none stated."
    )


class _TaskListArgs(BaseModel):
    status: Literal["open", "done", "dropped"] = Field(
        default="open", description="Which tasks to list. Default: open."
    )


class _TaskRefArgs(BaseModel):
    task: str = Field(..., description="Words identifying the open task (matched against its content).")
