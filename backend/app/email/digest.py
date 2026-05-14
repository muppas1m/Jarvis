"""Daily email digest — accumulates FYI emails and delivers at 8am."""
import redis.asyncio as aioredis
import json
from app.config import settings
from app.llm.gateway import llm_gateway

redis_client = aioredis.from_url(settings.REDIS_URL)
DIGEST_KEY = "jarvis:daily_digest"


async def add_to_digest(subject: str, sender: str, body_preview: str):
    """Add an FYI email to today's digest batch."""
    entry = json.dumps({"subject": subject, "sender": sender, "preview": body_preview})
    await redis_client.rpush(DIGEST_KEY, entry)


async def build_and_clear_digest() -> str | None:
    """Build the morning digest from accumulated FYI emails, then clear the queue."""
    entries_raw = await redis_client.lrange(DIGEST_KEY, 0, -1)

    if not entries_raw:
        return None

    entries = [json.loads(e) for e in entries_raw]

    # Summarize via LLM
    email_list = "\n".join(
        f"- From: {e['sender']} | Subject: {e['subject']} | Preview: {e['preview'][:100]}"
        for e in entries
    )

    prompt = f"""Summarize these {len(entries)} FYI emails into a concise morning digest.
Group by category (e.g., Receipts, Notifications, Team Updates).
Keep each item to one line. Be concise.

Emails:
{email_list}"""

    response = await llm_gateway.complete(
        messages=[{"role": "user", "content": prompt}],
        task_type="summarization",
        temperature=0.3,
    )

    digest = response["choices"][0]["message"]["content"]

    # Clear the queue
    await redis_client.delete(DIGEST_KEY)

    return f"📬 **Morning Email Digest** ({len(entries)} emails)\n\n{digest}"
