"""Owned fact-extraction — replaces Mem0's built-in extractor on the write path.

Why we own it (2026-06-25 diagnosis): Mem0 v2.0.6's ``add(infer=True)`` path
HARDWIRES its ``ADDITIVE_EXTRACTION_PROMPT`` — a maximal-recall prompt ("extract
every piece of memorable information", "when in doubt, extract", "extract from
BOTH user and assistant messages") that we cannot replace
(``custom_fact_extraction_prompt`` does not exist in 2.0.6; ``custom_instructions``
is only APPENDED as one section of that prompt and loses to it). Live measurement
on real turns: ~6 facts/turn, ~90% junk — one-off commands, Q&A, task outcomes,
and assistant-attributed rows ("Assistant created a test event") — exactly the
categories our scoping rules forbade.

The fix: extract facts OURSELVES with a TRUE system prompt (precision over recall;
the user and assistant turns are passed as SEPARATE roles so "assistant = context
only" is structurally enforceable — this is what kills the attributed-to-assistant
rows), then write each surviving fact to Mem0 with ``infer=False`` (Mem0 becomes a
pure vector store). The call routes through the LLM gateway (cost-tracked,
fallback-covered, Langfuse-traced — and the silent-drop-under-RPM failure becomes
observable in ``llm_usage_logs``) on a dedicated ``extractor`` slot (the paid
Gemini, off the agent's saturating Groq). A deterministic verb-anchored post-filter
backstops the LLM for the forbidden categories.
"""
from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from app.llm.gateway import llm_gateway
from app.utils.logging import get_logger

logger = get_logger(__name__)


EXTRACTION_SYSTEM_PROMPT = """You extract DURABLE long-term memories about a single user (the "User") for a personal AI assistant.

You are given ONE conversation turn as two messages: a `user` message (the User's own words) and an `assistant` message (the assistant's reply). The assistant message is CONTEXT ONLY — never store anything the assistant said, did, confirmed, created, deleted, or recommended as a fact.

Extract ONLY facts that are about the User as a person AND will still matter weeks from now:
- Stable preferences (likes/dislikes, communication style, food, tools, brands).
- Durable personal details (name, relationships, important recurring dates, home location, profession).
- Health & dietary facts (allergies, restrictions, fitness routines).
- Lasting goals and standing commitments (recurring plans, ongoing projects).

Do NOT extract (these are transient, or not a durable user fact):
- One-off task requests or commands ("send an email", "what's the distance to Orlando", "create a test event").
- The status or outcome of a task ("the email was sent", "both tools completed", "the issue was resolved").
- Anything the assistant said, did, confirmed, created, deleted, or recommended.
- Ephemeral state ("no events scheduled this weekend", "the calendar is empty").
- A question the User asked that reveals no durable fact about them.
- Conversational mechanics, acknowledgements, or pleasantries.

When uncertain whether a fact is durable, DO NOT extract it. Prefer precision over recall — extracting nothing is the correct answer for a turn with no durable user fact.

Write each fact as a self-contained third-person statement about the User (e.g. "User is allergic to shellfish", "User's wife is named Sarah").

Respond with a JSON object ONLY (no prose, no markdown fences):
{"facts": ["fact one", "fact two"]}
If there is nothing durable to store, respond with: {"facts": []}"""

# A trailing user turn that triggers JSON output without polluting the role
# separation above (the turn under analysis stays in its own user/assistant pair).
EXTRACT_DIRECTIVE = "Extract the durable User facts from the turn above. Respond with the JSON object only."


class ExtractedFacts(BaseModel):
    """Parse target for the extractor's JSON. An empty list is valid + common
    (a turn with no durable fact)."""

    facts: list[str] = Field(default_factory=list)


# Verb-anchored backstop. Drops any fact that slips past the LLM and matches a
# forbidden category: assistant-attributed, Q&A/approval mechanics, tool-action
# commands, task outcomes, or ephemeral calendar state. Deliberately HIGH-PRECISION
# — every pattern is anchored to mechanics/outcome phrasing that a real durable
# fact ("User is allergic to shellfish", "User wants to lose weight") never matches.
# The LLM prompt is the primary filter; this only catches leakage. Single source of
# truth — the test harness imports `is_forbidden_fact` as its forbidden-rate gauge.
_FORBIDDEN_PATTERNS = [
    r"^\s*assistant\b",                                 # assistant-attributed ("Assistant created…")
    r"\bthe assistant\b",                               # "…the assistant confirmed…"
    r"\buser (asked|inquired|approved)\b",              # Q&A / approval mechanics
    r"\bwants? to (send|create|delete|schedule|verify|check|test)\b",  # tool-action command
    r"\b(was|were|has been|have been) (sent|delivered|created|deleted|queued|archived|resolved|completed)\b",  # task outcome
    r"\b(no (scheduled )?events?|no events? (are|is) scheduled|has no (scheduled )?events?)\b",  # ephemeral calendar state
]
_FORBIDDEN_RE = re.compile("|".join(_FORBIDDEN_PATTERNS), re.IGNORECASE)


def is_forbidden_fact(fact: str) -> bool:
    """True if a fact matches a forbidden category (assistant-attributed, task
    mechanics/outcome, ephemeral state). Deterministic backstop + test classifier."""
    return bool(_FORBIDDEN_RE.search(fact))


def _parse_facts(content: str) -> list[str]:
    """Strip an optional markdown fence, parse JSON, validate. Raises on any
    failure (caller catches → returns [])."""
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        text = text.rsplit("```", 1)[0]
    data = json.loads(text)
    return ExtractedFacts(**data).facts


async def extract_facts(user_message: str, assistant_response: str) -> list[str]:
    """Extract durable User facts from one turn → a (possibly empty) list of
    self-contained fact strings, post-filtered for forbidden categories.

    Never raises: any LLM/parse/validation failure logs and returns [] — a turn
    that fails extraction stores NOTHING rather than garbage. The assistant reply
    is passed as a separate `assistant` role so the system prompt's "context only"
    rule is enforceable at the message level."""
    messages = [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
        {"role": "assistant", "content": assistant_response},
        {"role": "user", "content": EXTRACT_DIRECTIVE},
    ]
    try:
        response = await llm_gateway.complete(
            messages=messages,
            force_model="extractor",            # paid Gemini, off the agent's Groq
            temperature=0.0,
            response_format={"type": "json_object"},
            tool_name_context="memory_extraction",
        )
        content = response["choices"][0]["message"].get("content") or ""
        facts = _parse_facts(content)
    except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as exc:
        logger.warning(
            "memory_extraction_parse_failed", error=str(exc), error_type=type(exc).__name__
        )
        return []
    except Exception as exc:  # noqa: BLE001 — never break the turn on an extraction failure
        logger.error(
            "memory_extraction_llm_failed", error=str(exc), error_type=type(exc).__name__
        )
        return []

    kept: list[str] = []
    dropped: list[str] = []
    for raw in facts:
        fact = (raw or "").strip()
        if not fact:
            continue
        (dropped if is_forbidden_fact(fact) else kept).append(fact)
    if dropped:
        logger.info(
            "memory_extraction_post_filtered",
            dropped_count=len(dropped),
            dropped_preview=dropped[:3],
        )
    logger.info("memory_extraction_done", extracted=len(facts), kept=len(kept))
    return kept
