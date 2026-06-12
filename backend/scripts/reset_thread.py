"""Reset (delete) a conversation thread's checkpoint state.

Recovery hatch for a poisoned thread — one whose history carries an orphaned
tool_call that makes the LLM reject every subsequent turn (the Jun-11 terminal
error). After a reset, the next message to that thread starts clean.

    # list recent threads to find the one to reset
    docker compose exec backend python scripts/reset_thread.py --list

    # reset a specific thread (irreversible)
    docker compose exec backend python scripts/reset_thread.py <thread_id>

Irreversible: drops the thread's checkpoints, blobs, and pending writes.
"""
import argparse
import asyncio

from sqlalchemy import text

from app.agent.graph import close_checkpointer, init_checkpointer, reset_thread
from app.db.engine import async_session


async def _list_recent(limit: int) -> None:
    """Show the most-recently-updated threads so the operator can pick one.

    Reads the LangGraph checkpoints table directly (ordered by the SDK's
    monotonic checkpoint_id) — no public saver API exposes a thread listing."""
    async with async_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT thread_id, COUNT(*) AS checkpoints, MAX(checkpoint_id) AS latest "
                    "FROM checkpoints GROUP BY thread_id ORDER BY latest DESC LIMIT :limit"
                ),
                {"limit": limit},
            )
        ).all()
    if not rows:
        print("No threads found in the checkpoints table.")
        return
    print(f"{'thread_id':<40} {'checkpoints':>11}  latest_checkpoint_id")
    for thread_id, checkpoints, latest in rows:
        print(f"{thread_id:<40} {checkpoints:>11}  {latest}")


async def _reset(thread_id: str) -> None:
    await init_checkpointer()
    try:
        await reset_thread(thread_id)
        print(f"Reset thread {thread_id!r} — checkpoint state cleared.")
    finally:
        await close_checkpointer()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("thread_id", nargs="?", help="Thread to reset")
    parser.add_argument("--list", action="store_true", help="List recent threads and exit")
    parser.add_argument("--limit", type=int, default=20, help="Rows for --list (default 20)")
    args = parser.parse_args()

    if args.list:
        asyncio.run(_list_recent(args.limit))
        return
    if not args.thread_id:
        raise SystemExit("Provide a thread_id to reset, or --list to see candidates.")
    asyncio.run(_reset(args.thread_id))


if __name__ == "__main__":
    main()
