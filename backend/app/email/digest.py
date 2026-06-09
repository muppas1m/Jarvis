"""Daily email digest — accumulates FYI emails and delivers at 8am.

Urgency-aware (Turn 17.8): each queued entry carries the triage urgency, and the
morning build sorts entries most-urgent-first via the `urgency_rank` ordinal
(NOT an alphabetical text sort, which would put "none" second and "today" last)
before rendering inline tags. This digest reads the Redis queue (populated as FYI
emails arrive), not EmailLog rows — so ordering correctness lives entirely in the
deterministic `_order_entries` step over `urgency_rank`, which is unit-tested.
The LLM only groups/compresses; it does not own the ordering.
"""
import json

import redis.asyncio as aioredis

from app.config import settings
from app.email.classifier import URGENCY_TAG, urgency_rank
from app.llm.gateway import llm_gateway

redis_client = aioredis.from_url(settings.REDIS_URL)
DIGEST_KEY = "jarvis:daily_digest"


async def add_to_digest(subject: str, sender: str, body_preview: str, urgency: str = "none"):
    """Add an FYI email to today's digest batch, tagged with its triage urgency."""
    entry = json.dumps(
        {"subject": subject, "sender": sender, "preview": body_preview, "urgency": urgency}
    )
    await redis_client.rpush(DIGEST_KEY, entry)


def _order_entries(entries: list[dict]) -> list[dict]:
    """Sort entries most-urgent-first via the urgency ordinal. Pure over its
    input — the sort the digest's ordering correctness depends on."""
    return sorted(entries, key=lambda e: urgency_rank(e.get("urgency", "none")))


def _render_entry(e: dict) -> str:
    tag = URGENCY_TAG.get(e.get("urgency", "none"), "")
    prefix = f"{tag} " if tag else ""
    return f"- {prefix}From: {e['sender']} | Subject: {e['subject']} | Preview: {e['preview'][:100]}"


async def build_and_clear_digest() -> str | None:
    """Build the morning digest from accumulated FYI emails, then clear the queue."""
    entries_raw = await redis_client.lrange(DIGEST_KEY, 0, -1)
    if not entries_raw:
        return None

    entries = _order_entries([json.loads(e) for e in entries_raw])
    email_list = "\n".join(_render_entry(e) for e in entries)

    prompt = f"""Summarize these {len(entries)} FYI emails into a concise morning digest.
The list is already ordered most-urgent-first — PRESERVE that order and keep any
[IMMEDIATE] / [TODAY] / [THIS WEEK] tags on their items. Group related items by
category (e.g., Receipts, Notifications, Team Updates). Keep each item to one line.

Emails:
{email_list}"""

    response = await llm_gateway.complete(
        messages=[{"role": "user", "content": prompt}],
        task_type="summarization",
        temperature=0.3,
    )
    digest = response["choices"][0]["message"]["content"]

    await redis_client.delete(DIGEST_KEY)

    return f"📬 **Morning Email Digest** ({len(entries)} emails)\n\n{digest}"
