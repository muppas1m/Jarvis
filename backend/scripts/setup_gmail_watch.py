"""
One-shot Gmail watch registration. Phase 2 Task 2.2 closer.

Calls Gmail's `users.watch()` once to subscribe the master's INBOX label
to push notifications on the configured Pub/Sub topic. Gmail starts POSTing
update events to the topic; the topic's push subscription forwards them to
`/api/webhooks/gmail` (Task 2.3 lands the handler).

Watches expire after 7 days. Re-running this script renews them. Phase 2
Task 2.7's Celery beat job (`gmail_renew.py`) automates the renewal at a
6-day cadence wrapped in @critical_task; until that lands, this script is
the manual renewal mechanism too.

## Prereqs (verify before running)

  - `GOOGLE_REFRESH_TOKEN` populated in `.env` (Task 2.1 / google_oauth.py)
  - `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`
  - `GMAIL_PUBSUB_TOPIC` in `.env`, full resource name format:
        projects/<project-id>/topics/<topic-name>
  - Pub/Sub topic exists and `gmail-api-push@system.gserviceaccount.com`
    has roles/pubsub.publisher on it (Task 0.0 step C)

## Run

The running backend container has stale settings (the `.env` was edited
after it started). Spawn a fresh container that re-reads `.env`:

    docker compose run --rm --entrypoint sh backend -c \\
        "cd /app && python scripts/setup_gmail_watch.py"

## Success

A `gmail_watch_registered` log line with an `expiration` value (ms-since-
epoch). The script prints the expiration in ISO format too. The Gmail
account starts pushing INBOX changes to the Pub/Sub topic immediately.

## Common failures

  - "Login Required" / refresh token rejected: token revoked or scopes
    don't include gmail.modify. Re-run google_oauth.py.
  - "Topic not found": GMAIL_PUBSUB_TOPIC value is wrong (most often the
    project ID — must be the project that owns the Gmail OAuth client,
    not the GATSY project that owns GOOGLE_GEMINI_API_KEY).
  - "User not authorized": gmail-api-push@system.gserviceaccount.com is
    missing the publisher role on the topic. Re-do Task 0.0 step C.
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

from app.config import settings
from app.email.gmail_watch import setup_gmail_watch


def _check_prereqs() -> list[str]:
    missing = []
    if not settings.GOOGLE_REFRESH_TOKEN:
        missing.append("GOOGLE_REFRESH_TOKEN")
    if not settings.GOOGLE_CLIENT_ID:
        missing.append("GOOGLE_CLIENT_ID")
    if not settings.GOOGLE_CLIENT_SECRET:
        missing.append("GOOGLE_CLIENT_SECRET")
    if not settings.GMAIL_PUBSUB_TOPIC:
        missing.append("GMAIL_PUBSUB_TOPIC")
    return missing


def _format_expiration(expiration_ms: str | int | None) -> str:
    """Gmail returns expiration as ms-since-epoch (string in JSON, sometimes
    int). Convert to ISO so the operator sees when it'll need renewing."""
    if expiration_ms is None:
        return "(no expiration in response)"
    try:
        ms = int(expiration_ms)
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
        return f"{dt.isoformat()} (UTC)"
    except (ValueError, TypeError):
        return f"(unparseable: {expiration_ms!r})"


async def main() -> int:
    missing = _check_prereqs()
    if missing:
        print(
            "ERROR: missing required env vars: " + ", ".join(missing),
            file=sys.stderr,
        )
        print(
            "Set them in .env and re-run (use `docker compose run --rm` so "
            "the container reads the fresh .env).",
            file=sys.stderr,
        )
        return 1

    print(f"Registering Gmail watch for INBOX -> {settings.GMAIL_PUBSUB_TOPIC}")
    print()
    try:
        result = await setup_gmail_watch()
    except Exception as exc:  # noqa: BLE001 — top-level operator script
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print("=" * 60)
    print("Gmail watch registered.")
    print(f"  historyId:  {result.get('historyId')}")
    print(f"  expiration: {_format_expiration(result.get('expiration'))}")
    print("=" * 60)
    print()
    print("Watch expires in ~7 days. Re-run this script (or wait for")
    print("Task 2.7's gmail_renew.py Celery beat job to handle it).")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
