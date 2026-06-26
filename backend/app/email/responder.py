from app.llm.gateway import llm_gateway
from app.memory.manager import get_memory

DRAFT_PROMPT = """You are drafting an email reply on behalf of your master ({master_name}).

Write a professional, concise reply. Match the tone of the original email. (Whether
a reply is worth drafting was already decided upstream — your job is only to write it.)

## Critical: do not fabricate facts
- Use ONLY information explicitly present in the email above, the master's
  profile section, or that you know with certainty. Do NOT invent dates,
  times, names, prices, locations, attendees, URLs, account numbers, or any
  other specific details.
- If the email asks a question you cannot answer from the available context
  (e.g. "what time is the meeting?" when no time is in the email or profile),
  draft a reply that asks the sender for the missing information rather than
  guessing — e.g. "Could you remind me what time we settled on?".
- Phrasings like "the meeting is at X", "let's meet at Y", "the price is Z",
  "I'll attend on <date>" are forbidden unless X / Y / Z / <date> appears
  verbatim in the email or profile.

Respond in this exact JSON format:
{{
    "response": "Your drafted email reply here"
}}

---
Original Email:
From: {sender}
Subject: {subject}
Body:
{body}

Master's communication style: {comm_style}
"""


async def generate_draft(subject: str, sender: str, body: str) -> str:
    """Generate a draft reply (the simple/complex decision is the classifier's job
    now — see EmailTriageResult.reply_effort). Returns the draft body string; on a
    parse failure, returns the raw model content (never empty-silently)."""
    import json

    profile = await get_memory().profile_mgr.get_full()
    always_on = profile.get("always_on", {})

    prompt = DRAFT_PROMPT.format(
        master_name=profile.get("name", "Master"),
        sender=sender,
        subject=subject,
        body=body[:2000],
        comm_style=always_on.get("communication_style", "Professional and concise"),
    )

    response = await llm_gateway.complete(
        messages=[{"role": "user", "content": prompt}],
        task_type="drafting",
        temperature=0.3,
    )

    content = response["choices"][0]["message"]["content"]
    try:
        return json.loads(content).get("response", "") or content
    except json.JSONDecodeError:
        return content


REVISE_PROMPT = """You are revising a draft email reply on behalf of your master ({master_name}).

You already drafted the reply below. The master reviewed it and asked for ONE
change. Apply their change and return the REVISED reply — keep everything else
intact; change only what they asked for.

Same hard rule as the original draft: do NOT fabricate facts. Use only what's in
the draft, the original email, or the master's profile. If the requested change
needs information you don't have, ask the sender for it rather than inventing it.

Respond in this exact JSON format:
{{
    "response": "Your revised email reply here"
}}

---
Original email — From: {sender}, Subject: {subject}

The draft you wrote:
{draft}

The master's requested change: {change}

Master's communication style: {comm_style}
"""


async def revise_draft(*, subject: str, sender: str, draft: str, change: str) -> str:
    """Re-draft an email reply applying the master's requested change, returning the
    revised reply body. The original ``draft`` + the ``change`` are the re-draft
    CONTEXT (they go in the prompt) — never the master's persisted words."""
    import json

    profile = await get_memory().profile_mgr.get_full()
    always_on = profile.get("always_on", {})

    prompt = REVISE_PROMPT.format(
        master_name=profile.get("name", "Master"),
        sender=sender,
        subject=subject,
        draft=draft,
        change=change,
        comm_style=always_on.get("communication_style", "Professional and concise"),
    )

    response = await llm_gateway.complete(
        messages=[{"role": "user", "content": prompt}],
        task_type="drafting",
        temperature=0.3,
    )

    content = response["choices"][0]["message"]["content"]
    try:
        return json.loads(content).get("response", "") or content
    except json.JSONDecodeError:
        return content
