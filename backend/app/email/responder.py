from app.llm.gateway import llm_gateway
from app.memory.manager import get_memory

DRAFT_PROMPT = """You are drafting an email reply on behalf of your master ({master_name}).

Write a professional, concise reply. Match the tone of the original email.

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

## Complexity classification
Mark as "complex" if ANY of the following:
- The reply requires factual information not in the email or profile (per
  the rule above — you're asking the sender for missing info).
- The reply involves a non-trivial decision, sensitive communication, or
  multi-step coordination.
- You are NOT confident a one-line acknowledgment is appropriate.

Otherwise mark as "simple" — true acknowledgments only ("thanks, will do",
"got it", "sounds good", a literal yes/no the email itself answers from
context).

Respond in this exact JSON format:
{{
    "complexity": "simple" or "complex",
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


async def generate_draft(subject: str, sender: str, body: str) -> dict:
    """Generate a draft reply and assess complexity."""
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
        result = json.loads(content)
        return {
            "complexity": result.get("complexity", "complex"),
            "response": result.get("response", ""),
        }
    except json.JSONDecodeError:
        return {"complexity": "complex", "response": content}
