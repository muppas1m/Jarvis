"""
StateGraph wiring + AsyncPostgresSaver checkpointer.

Topology lives in `build_graph()`'s docstring below — keeping it in one
place so the diagram doesn't drift across files. nodes.py also references
the same picture from the consumer side.

The checkpointer persists state to Postgres after each node, so a turn that
hits `interrupt()` (in tool_executor for an APPROVE-level call) survives
process restarts. Resume happens via `Command(resume=...)` from runner.py.

Lifecycle:
  - `init_checkpointer()` is called from FastAPI's lifespan startup hook.
    It opens an async connection pool against Postgres and calls setup() —
    setup() is idempotent; the actual schema was created by alembic migration
    002, this just verifies and migrates the SDK's internal version table
    if needed.
  - `close_checkpointer()` runs at shutdown to drain the pool cleanly.
  - `get_checkpointer()` raises if it's queried before init — this should
    never happen at runtime; the lifespan ordering guarantees it.

The returned compiled graph is cached in module state by runner.py so we
don't rebuild on every turn.
"""
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

from app.agent.nodes import (
    agent_node,
    memory_load_node,
    persist_node,
    should_continue,
    should_continue_tools,
    tool_executor_node,
)
from app.agent.state import AgentState
from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Module-level state for the singleton checkpointer + its context manager.
_checkpointer: AsyncPostgresSaver | None = None
_checkpointer_cm = None


def _checkpointer_conn_string() -> str:
    """psycopg expects a bare postgresql:// URL — strip SQLAlchemy's
    +psycopg qualifier from DATABASE_URL_SYNC. Same fix as the
    002_langgraph_checkpoints alembic migration."""
    return settings.DATABASE_URL_SYNC.replace("+psycopg", "")


async def init_checkpointer() -> None:
    """Open the AsyncPostgresSaver. Call from FastAPI lifespan startup."""
    global _checkpointer, _checkpointer_cm
    if _checkpointer is not None:
        return  # idempotent — already open
    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(_checkpointer_conn_string())
    _checkpointer = await _checkpointer_cm.__aenter__()
    # setup() is no-op when alembic has already provisioned the tables, but
    # safe to call — handles the SDK's internal version row.
    await _checkpointer.setup()
    logger.info("checkpointer_ready")


async def close_checkpointer() -> None:
    """Drain the pool. Call from FastAPI lifespan shutdown."""
    global _checkpointer, _checkpointer_cm
    if _checkpointer_cm is not None:
        await _checkpointer_cm.__aexit__(None, None, None)
    _checkpointer = None
    _checkpointer_cm = None
    logger.info("checkpointer_closed")


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError(
            "Checkpointer not initialized. Call init_checkpointer() first "
            "(this happens automatically inside FastAPI's lifespan startup)."
        )
    return _checkpointer


def build_graph():
    """Compile the agent StateGraph. Call AFTER init_checkpointer().

    Topology:
        START -> memory_load -> agent -> [should_continue]
                                  ^       ├─ tool_calls? -> tool_executor
                                  |       └─ no          -> persist -> END
                                  |
                                  |     [should_continue_tools after tool_executor]
                                  |       ├─ more pending? -> tool_executor
                                  └───────└─ all done     -> agent

    The tool_executor node processes ONE tool call per invocation; the
    conditional edge after it loops back to itself until every tool call
    in the most recent AIMessage has produced a ToolMessage. This is what
    makes the resume-from-interrupt path safe — see nodes.py docstring.
    """
    builder = StateGraph(AgentState)

    builder.add_node("memory_load", memory_load_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tool_executor", tool_executor_node)
    builder.add_node("persist", persist_node)

    builder.add_edge(START, "memory_load")
    builder.add_edge("memory_load", "agent")
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tool_executor": "tool_executor",
            "persist": "persist",
        },
    )
    builder.add_conditional_edges(
        "tool_executor",
        should_continue_tools,
        {
            "tool_executor": "tool_executor",
            "agent": "agent",
        },
    )
    builder.add_edge("persist", END)

    return builder.compile(checkpointer=get_checkpointer())
