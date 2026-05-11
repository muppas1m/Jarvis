"""
Seed (or re-seed) the master's profile row.

Phase 1 has exactly one master, stored as a single row in `user_profiles`
with always_on (small dict joined into every system prompt) and on_demand
(larger sections retrieved by Mem0 semantic search). The first-run guard
in main.py refuses to boot if this row doesn't exist, so this script is
the canonical bootstrapping step on a fresh deployment.

Idempotency:
  - On a fresh DB (no row): inserts cleanly.
  - On an existing row WITHOUT --force: refuses with a clear message
    naming the existing row's name + id. This is intentional — silent
    no-op would defeat the audit purpose ("you ran it, it said OK, but
    actually did nothing"), and silent overwrite risks clobbering fields
    that have been organically refined over weeks of conversation.
  - On an existing row WITH --force: deletes the row and reinserts. Mem0
    sections from a prior seed are NOT cleaned up (Mem0 doesn't expose a
    tidy "delete by metadata" API in v0.1.x); a warning is logged and
    operators can clear stale entries manually if needed.

Input:
  Reads JSON from --config <path> if provided, else from stdin. The
  schema is:

    {
      "name": "Master",
      "always_on": {
        "timezone": "America/New_York",
        "language": "English",
        "communication_style": "Direct, brief, bullet points"
      },
      "on_demand": {
        "news_topics": ["AI", "Crypto", "Web3"]
      }
    }

  always_on values are scalars/short strings (they go into every prompt).
  on_demand values can be larger lists/dicts — they're retrieved only
  when relevant via Mem0 semantic search.

Usage:
    docker compose run --rm backend python scripts/seed_profile.py < profile.json
    docker compose run --rm backend python scripts/seed_profile.py --config /app/profile.json
    docker compose run --rm backend python scripts/seed_profile.py --config /app/profile.json --force
"""
import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import select

from app.db.engine import async_session, close_db, init_db
from app.db.models import UserProfile
from app.memory.manager import MemoryManager


EXAMPLE = {
    "name": "Master",
    "always_on": {
        "timezone": "America/New_York",
        "language": "English",
        "communication_style": "Direct, brief, bullet points",
    },
    "on_demand": {
        "news_topics": ["AI", "Crypto", "Web3"],
    },
}


def _read_config(path: str | None) -> dict[str, Any]:
    """Read JSON from --config <path> or stdin. Validates the top-level shape."""
    if path:
        with open(path) as f:
            data = json.load(f)
    else:
        stdin_text = sys.stdin.read() if not sys.stdin.isatty() else ""
        if not stdin_text.strip():
            print(
                "ERROR: provide profile JSON via --config <path> or piped stdin.\n\n"
                "Example shape:\n"
                + json.dumps(EXAMPLE, indent=2)
                + "\n\nPipe via:\n"
                "  docker compose run --rm backend python scripts/seed_profile.py < profile.json\n"
                "Or:\n"
                "  docker compose run --rm backend python scripts/seed_profile.py --config /app/profile.json",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            data = json.loads(stdin_text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"ERROR: stdin is not valid JSON: {exc}")

    if not isinstance(data, dict):
        raise SystemExit("ERROR: profile JSON must be an object at the top level")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise SystemExit("ERROR: 'name' must be a non-empty string")
    if "always_on" in data and not isinstance(data["always_on"], dict):
        raise SystemExit("ERROR: 'always_on' must be an object")
    if "on_demand" in data and not isinstance(data["on_demand"], dict):
        raise SystemExit("ERROR: 'on_demand' must be an object")

    data.setdefault("always_on", {})
    data.setdefault("on_demand", {})
    return data


async def _seed(profile_data: dict[str, Any], force: bool) -> int:
    await init_db()

    try:
        async with async_session() as session:
            existing_result = await session.execute(select(UserProfile).limit(1))
            existing = existing_result.scalar_one_or_none()

        if existing is not None and not force:
            print(
                f"REFUSED: master profile already exists.\n"
                f"  id:   {existing.id}\n"
                f"  name: {existing.name!r}\n\n"
                f"Re-run with --force to delete the existing row and replace it.\n"
                f"WARNING: --force loses any always_on / on_demand fields that\n"
                f"         have been organically refined since the last seed.",
                file=sys.stderr,
            )
            return 1

        # --- delete existing if --force ---
        if existing is not None:
            async with async_session() as session:
                row_result = await session.execute(select(UserProfile).limit(1))
                row = row_result.scalar_one()
                await session.delete(row)
                await session.commit()
            print(
                f"  deleted existing profile (id={existing.id}, name={existing.name!r}).\n"
                f"  WARNING: stale Mem0 entries from prior on_demand sections are\n"
                f"           NOT cleaned up — Mem0 v0.1.x has no delete-by-metadata\n"
                f"           API. Clear them manually if needed.",
                file=sys.stderr,
            )

        # --- insert new row ---
        async with async_session() as session:
            profile = UserProfile(
                name=profile_data["name"],
                always_on=profile_data["always_on"],
                on_demand={},  # filled in via MemoryManager so Mem0 indexing fires
            )
            session.add(profile)
            await session.commit()
            new_id = profile.id

        print(
            f"  inserted master profile (id={new_id}, name={profile_data['name']!r})",
            file=sys.stderr,
        )
        if profile_data["always_on"]:
            print(
                f"  always_on: {sorted(profile_data['always_on'].keys())}",
                file=sys.stderr,
            )

        # --- index on_demand sections via MemoryManager ---
        # update_profile_on_demand writes both the user_profiles.on_demand
        # JSONB AND a Mem0 entry with metadata.kind="profile" so semantic
        # recall surfaces the section when relevant.
        if profile_data["on_demand"]:
            mgr = MemoryManager()
            for key, value in profile_data["on_demand"].items():
                await mgr.update_profile_on_demand(key, value)
            print(
                f"  on_demand sections indexed: {sorted(profile_data['on_demand'].keys())}",
                file=sys.stderr,
            )

        print("OK", file=sys.stderr)
        return 0
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed the master's user_profiles row.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example profile JSON:\n" + json.dumps(EXAMPLE, indent=2)
        ),
    )
    parser.add_argument("--config", help="Path to profile JSON (else read from stdin).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Delete an existing profile row and replace. Required when a row exists.",
    )
    args = parser.parse_args()

    profile_data = _read_config(args.config)
    sys.exit(asyncio.run(_seed(profile_data, force=args.force)))


if __name__ == "__main__":
    main()
