"""
StateGraph wiring + AsyncPostgresSaver checkpointer.

Topology lives in `build_graph()`'s docstring below — keeping it in one
place so the diagram doesn't drift across files. nodes.py also references
the same picture from the consumer side.

The checkpointer persists state to Postgres after each node, so a conversation
survives process restarts. Phase 3 retired `interrupt()`: an APPROVE-level tool
no longer pauses the graph — it QUEUES a PendingApproval and the turn completes,
executing out-of-band on approve via the claim-gated dispatcher.

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
    card_resolution_node,
    compact_node,
    memory_load_node,
    persist_node,
    queued_finish_node,
    route_after_card,
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


async def reset_thread(thread_id: str) -> None:
    """Delete all persisted checkpoint state for a thread.

    Recovery hatch for a poisoned conversation — e.g. a thread whose history
    carries an orphaned tool_call that makes the LLM reject every subsequent
    turn (the Jun-11 terminal error). After a reset the next message to that
    thread starts a clean turn. Irreversible: drops the thread's checkpoints,
    blobs, and pending writes. Used by scripts/reset_thread.py."""
    await get_checkpointer().adelete_thread(thread_id)
    logger.info("thread_reset", thread_id=thread_id)


def build_graph():
    """Compile the agent StateGraph. Call AFTER init_checkpointer().

    Topology (Step A added card_resolution before the agent):
        START -> memory_load -> card_resolution -> [route_after_card]
                                  ^                  ├─ card_handled? -> persist (end the turn
                                  |                  │                    with the node's outcome)
                                  |                  └─ no            -> agent
                                  |
                                  |     agent -> [should_continue]
                                  |       ├─ tool_calls?       -> tool_executor
                                  |       ├─ queued this turn? -> queued_finish (read-back)
                                  |       └─ else              -> persist
                                  |
                                  |     tool_executor -> [should_continue_tools]  (A1 natural loop)
                                  |       ├─ more pending?          -> tool_executor
                                  |       ├─ nothing to consume     -> queued_finish -> persist
                                  |       │  (all [QUEUED]/[ALREADY_QUEUED] — the safety floor)
                                  └───────└─ read/execute result    -> agent

        persist -> compact -> END

    card_resolution (Step A): when the master is viewing an approval card
    (presented_approval_id set), it judges their message on the STRONG model and either
    resolves the card (claim-gated dispatch) IN-graph — so the exchange persists — or routes
    the turn to the agent for a normal answer. Retires the old runner short-circuits that
    never persisted (D2/NV1) and gave canned wrong-context answers (D3).

    The tool_executor node processes ONE tool call per invocation; the
    conditional edge after it loops back to itself until every tool call
    in the most recent AIMessage has produced a ToolMessage.
    """
    builder = StateGraph(AgentState)

    builder.add_node("memory_load", memory_load_node)
    builder.add_node("card_resolution", card_resolution_node)
    builder.add_node("agent", agent_node)
    builder.add_node("tool_executor", tool_executor_node)
    builder.add_node("queued_finish", queued_finish_node)
    builder.add_node("persist", persist_node)
    builder.add_node("compact", compact_node)

    builder.add_edge(START, "memory_load")
    builder.add_edge("memory_load", "card_resolution")
    builder.add_conditional_edges(
        "card_resolution",
        route_after_card,
        {
            "agent": "agent",
            "persist": "persist",
        },
    )
    builder.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tool_executor": "tool_executor",
            # A1: a natural answer with cards queued this turn ends via queued_finish (the
            # deterministic read-back), not straight to persist — the mixed-round read-back path.
            "queued_finish": "queued_finish",
            "persist": "persist",
        },
    )
    builder.add_conditional_edges(
        "tool_executor",
        should_continue_tools,
        {
            "tool_executor": "tool_executor",
            "agent": "agent",
            # ROOT FIX (duplicate-cards): an all-[QUEUED] round ENDS the turn here instead of
            # looping back to agent_node (which re-queued the same action 5×).
            "queued_finish": "queued_finish",
        },
    )
    builder.add_edge("queued_finish", "persist")
    # persist → compact (4.B.3 rolling summary at the turn boundary) → END.
    builder.add_edge("persist", "compact")
    builder.add_edge("compact", END)

    return builder.compile(checkpointer=get_checkpointer())
