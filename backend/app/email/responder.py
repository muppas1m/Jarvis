from app.llm.gateway import llm_gateway
from app.memory.manager import MemoryManager

memory = MemoryManager()

DRAFT_PROMPT = """You are drafting an email reply on behalf of your master ({master_name}).

Write a professional, concise reply. Match the tone of the original email.
If the email requires complex decision-making, scheduling, or sensitive communication, mark it as "complex".
If it's a straightforward reply (acknowledgment, simple yes/no, scheduling confirmation), mark it as "simple".

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

    profile = await memory.profile_mgr.get_full()
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
