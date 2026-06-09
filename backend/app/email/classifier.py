"""Multi-dimensional email triage (Turn 17.8).

The classifier emits five axes in one LLM call, not just a 3-way label:
classification (what bucket), urgency (when a response is expected), intent (what
the sender wants), confidence (how sure the model is), and suggested_action (the
recommended handling). Persisted into ``EmailLog.meta`` so the digest can order by
urgency and the history tool can filter on it.

**JSON robustness (project_open_weights_tool_schema_and_conversation_poisoning).**
Free-text JSON from a fast/open-weights model is fragile, so:
  - the call goes through the gateway (cost-tracked, fallback-covered) with
    ``response_format={"type": "json_object"}`` — JSON mode on Groq/OpenAI;
  - ``_parse_triage`` strips markdown fences before ``json.loads``;
  - ``EmailTriageResult`` types every field as a ``Literal`` enum, so an
    out-of-enum value from the model fails validation INTO the conservative
    fallback rather than persisting garbage;
  - any parse/validation failure degrades to ``_fallback_triage`` (3-way "fyi",
    ``confidence=0.0``) — never raises into the pipeline.

Note: ``EmailTriageResult`` is the classifier's internal parse target, NOT a tool
``args_schema``, so ``Literal`` enums are correct here — the flat-types/empty-string
rule from the open-weights note applies only to tool-calling schemas (e.g. the
``urgency`` filter arg in ``email_history``).
"""
from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.llm.gateway import llm_gateway
from app.utils.logging import get_logger

logger = get_logger(__name__)


Classification = Literal["spam", "fyi", "action_required"]
Urgency = Literal["immediate", "today", "this_week", "none"]
Intent = Literal["request", "question", "notification", "fyi", "spam"]
SuggestedAction = Literal["reply", "archive", "forward", "schedule", "none"]


class EmailTriageResult(BaseModel):
    """Validated five-axis triage. Out-of-enum model output → ValidationError →
    caller falls back, so garbage never reaches ``EmailLog.meta``."""

    classification: Classification
    urgency: Urgency
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    suggested_action: SuggestedAction


# Urgency sort ordinal — single source of truth for ordering. A plain TEXT sort
# on the urgency string is alphabetical ("immediate", "none", "this_week",
# "today") which is WRONG (puts "none" second, "today" last). `urgency_rank`
# gives the correct ordering and the same dict drives any SQL CASE if needed.
URGENCY_ORDINAL: dict[str, int] = {
    "immediate": 0,
    "today": 1,
    "this_week": 2,
    "none": 3,
}


def urgency_rank(urgency: str) -> int:
    """Sort key: immediate(0) < today(1) < this_week(2) < none(3). Unknown
    values sort last (treated as 'none'). Pure + deterministic — unit-tested."""
    return URGENCY_ORDINAL.get(urgency, 3)


# Inline display tag per urgency, shared by the digest + history surfaces so the
# urgency vocabulary stays consistent. "none" gets no tag (keeps routine items quiet).
URGENCY_TAG: dict[str, str] = {
    "immediate": "[IMMEDIATE]",
    "today": "[TODAY]",
    "this_week": "[THIS WEEK]",
}


TRIAGE_PROMPT = """You are an email triage classifier for a personal AI assistant.

Classify the email below across five axes and respond with a JSON object ONLY
(no prose, no markdown fences):

{{
  "classification": one of "spam" | "fyi" | "action_required",
  "urgency": one of "immediate" | "today" | "this_week" | "none",
  "intent": one of "request" | "question" | "notification" | "fyi" | "spam",
  "confidence": a number from 0.0 to 1.0 (how sure you are of the classification),
  "suggested_action": one of "reply" | "archive" | "forward" | "schedule" | "none"
}}

Guidance:
- "spam": promotional, marketing, newsletters, automated junk → usually urgency "none", action "archive".
- "fyi": informational, no response needed (receipts, confirmations, status updates).
- "action_required": a direct question, request, meeting ask, or personal message needing the master's response.
- urgency reflects WHEN a response is expected, independent of classification.
- confidence reflects how certain you are — use a low value when the email is ambiguous.

---
From: {sender}
Subject: {subject}
Body (first 500 chars):
{body}
"""


def _fallback_triage() -> EmailTriageResult:
    """Conservative default when the model output can't be parsed/validated:
    treat as informational (no destructive auto-action), confidence 0.0 so
    downstream consumers can tell a real classification from a parse failure."""
    return EmailTriageResult(
        classification="fyi",
        urgency="none",
        intent="fyi",
        confidence=0.0,
        suggested_action="none",
    )


def _parse_triage(content: str) -> EmailTriageResult:
    """Strip markdown fences, parse JSON, validate against the enums. Raises on
    any failure (caller catches → fallback)."""
    text = content.strip()
    if text.startswith("```"):
        # Drop a leading ```json / ``` fence and the trailing ``` fence.
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    data = json.loads(text)
    return EmailTriageResult(**data)


async def classify_email(subject: str, sender: str, body: str) -> EmailTriageResult:
    """Five-axis triage via the fast model. Never raises — parse/validation
    failures degrade to the conservative `_fallback_triage`."""
    prompt = TRIAGE_PROMPT.format(sender=sender, subject=subject, body=body[:500])

    try:
        response = await llm_gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            task_type="classification",  # fast model (Groq llama-3.1-8b)
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response["choices"][0]["message"].get("content") or ""
        return _parse_triage(content)
    except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as exc:
        logger.warning(
            "email_triage_parse_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            sender=sender,
            subject=subject[:80],
        )
        return _fallback_triage()
    except Exception as exc:
        # LLM call itself failed (network, cap, provider) — still degrade rather
        # than break the inbound pipeline.
        logger.error(
            "email_triage_llm_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            sender=sender,
        )
        return _fallback_triage()
