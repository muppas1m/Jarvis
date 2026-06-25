"""Natural-language resolution of a pending decision (A2 Piece 2).

Modality-agnostic: text (stream_turn / run_turn) and voice (Piece 3) feed the
SAME judgment. Given the pending action (tool + args + description) and the
master's reply, a fast-tier LLM classifies intent → approve / reject / edit /
skip / show_others / unrelated. No keyword matching — "yes send it", "looks good",
"actually make it shorter", "use her name Priya", "cancel that", "skip this one",
"what else is pending?" all resolve by understanding, and it generalizes to any
decision type (no per-tool code).

Safety bias: approving triggers a REAL, irreversible action, so the resolver is
conservative on approve — anything genuinely ambiguous (a question, a new topic,
unclear intent) degrades to ``unrelated`` (the caller re-prompts), NEVER an
auto-approve. reject / edit / skip / show_others are all SAFE (nothing sends).
``skip`` (defer, queue stays) and ``show_others`` (what else is pending) are
queue-navigation intents — they must be ABOUT this card / the approval queue, not
a general question, which stays ``unrelated`` so it falls through to a normal turn.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from app.llm.gateway import llm_gateway
from app.utils.logging import get_logger

logger = get_logger(__name__)

Intent = Literal["approve", "reject", "edit", "skip", "show_others", "unrelated"]
_VALID_INTENTS = ("approve", "reject", "edit", "skip", "show_others", "unrelated")


@dataclass(frozen=True)
class DecisionResolution:
    intent: Intent
    change: str = ""  # the requested edit, verbatim-ish, when intent == "edit"


_RESOLVER_PROMPT = """You are mediating a PENDING ACTION the assistant proposed and is waiting for the master to confirm BEFORE it runs. Classify the master's reply toward THIS action.

PENDING ACTION
  tool: {tool_name}
  details:
{details}

MASTER'S REPLY
  "{user_message}"

Choose exactly ONE intent:
- "approve": the master clearly wants it to proceed AS-IS — e.g. "yes", "send it", "go ahead", "looks good", "do it", "perfect", "ship it". Approving runs a REAL, irreversible action, so choose this ONLY when approval is unambiguous.
- "reject": the master clearly wants it cancelled / abandoned — e.g. "no", "cancel", "don't send", "forget it", "scrap it", "stop".
- "edit": the master wants THIS action CHANGED before it proceeds — e.g. "make it shorter", "use her name Priya", "change the recipient to X", "add that we'll be late", "more formal". Put the requested change in "change".
- "skip": the master wants to DEFER this specific pending action for now and move on, WITHOUT cancelling it — e.g. "skip", "skip this", "skip this one", "next", "next one", "not now", "later", "come back to this", "I'll deal with this one later". (Different from reject — skip leaves it pending; reject abandons it.)
- "show_others": the master wants to know what OTHER pending approvals are waiting — e.g. "what else is pending?", "show me the other pending emails", "what other approvals do I have?", "anything else waiting for me?". This is about the approval QUEUE specifically — NOT a general "show me my emails / calendar" request.
- "unrelated": the reply is about something else, a new question / topic (e.g. "what's on my calendar?", "show me my unread emails", "what's the weather?"), or is too ambiguous to be sure. WHEN IN DOUBT, choose this — never guess "approve" or "skip".

Respond with JSON only:
{{"intent": "approve|reject|edit|skip|show_others|unrelated", "change": "<the requested change, or empty unless intent is edit>"}}"""


def _details(tool_args: dict, description: str | None) -> str:
    lines = [f"  - {k}: {v}" for k, v in (tool_args or {}).items()]
    return "\n".join(lines) if lines else (f"  {description}" if description else "  (no parameters)")


async def resolve_decision(
    tool_name: str,
    tool_args: dict,
    description: str | None,
    user_message: str,
) -> DecisionResolution:
    """Classify the master's reply against the pending action. Conservative on
    approve; any failure degrades to ``unrelated`` (never an auto-approve)."""
    prompt = _RESOLVER_PROMPT.format(
        tool_name=tool_name,
        details=_details(tool_args, description),
        user_message=user_message.strip(),
    )
    try:
        response = await llm_gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            task_type="classification",  # fast tier (Groq llama-3.1-8b)
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        content = response["choices"][0]["message"].get("content") or ""
        data = json.loads(content)
        intent = data.get("intent")
        if intent not in _VALID_INTENTS:
            intent = "unrelated"
        change = (data.get("change") or "").strip() if intent == "edit" else ""
        # An "edit" with no concrete change isn't actionable → treat as ambiguous.
        if intent == "edit" and not change:
            intent = "unrelated"
        logger.info("decision_resolved", intent=intent, has_change=bool(change))
        return DecisionResolution(intent=intent, change=change)
    except Exception as exc:  # noqa: BLE001 — never auto-approve on a resolver failure
        logger.warning("decision_resolver_failed", error=f"{type(exc).__name__}: {exc}")
        return DecisionResolution(intent="unrelated")
