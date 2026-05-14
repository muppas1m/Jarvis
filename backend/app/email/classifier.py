from app.llm.gateway import llm_gateway

CLASSIFICATION_PROMPT = """You are an email classifier for a personal AI assistant.

Classify the following email into exactly ONE category:
- "spam": Promotional, marketing, newsletters, automated notifications, junk
- "fyi": Informational only — no response needed (receipts, confirmations, status updates, team FYIs)
- "action_required": Requires a response or action from the master (direct questions, meeting requests, personal messages, urgent items)

Respond with ONLY the classification word, nothing else.

---
From: {sender}
Subject: {subject}
Body (first 500 chars):
{body}
"""


async def classify_email(subject: str, sender: str, body: str) -> str:
    """Classify an email using the fast model (Haiku)."""
    prompt = CLASSIFICATION_PROMPT.format(
        sender=sender,
        subject=subject,
        body=body[:500],
    )

    response = await llm_gateway.complete(
        messages=[{"role": "user", "content": prompt}],
        task_type="classification",  # Routes to Haiku
        temperature=0.0,
    )

    classification = response["choices"][0]["message"]["content"].strip().lower()

    if classification not in ("spam", "fyi", "action_required"):
        return "fyi"  # Default to fyi on unexpected output

    return classification
