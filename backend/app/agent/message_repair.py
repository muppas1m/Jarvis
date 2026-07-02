"""Message-history repair — wire-shape normalization for tool calls (D22/D23 class).

An LLM request 400s on OpenAI's strict endpoint whenever the OUTBOUND payload
carries an assistant tool_call without its immediately-following tool responses.
Two distinct sources feed that payload (the D22 5th-capture measurement):

  1. The PARSED field — ``AIMessage.tool_calls``. A call that never produced a
     ``ToolMessage`` (the Jun-11 interrupt shape) is a classic orphan.
  2. The RAW provider mirror — ``additional_kwargs["tool_calls"]`` (+ the
     parse-failed ``invalid_tool_calls``). llama emitting a malformed call
     (``approvals_pending(arguments="null")``, id ``trpv0ek1t``) parses into
     ``invalid_tool_calls`` with ``tool_calls`` EMPTY — invisible to every
     ``.tool_calls`` audit — yet ChatLiteLLM's ``_convert_message_to_dict``
     RESURRECTS the raw mirror on the wire (``elif "tool_calls" in
     message.additional_kwargs``) → an unanswerable call → 400 on every
     subsequent turn → the thread bricks (web:master, 2026-07-02).

``repair_orphaned_tool_calls`` therefore normalizes BOTH sources on outbound
COPIES before every agent LLM call:
  - divergent residue (``invalid_tool_calls``; ak-mirror ids absent from the
    parsed list) → STRIPPED — the call never executed; synthesizing an answer
    would preserve the malformed call in every payload via the resurrection.
  - a truly-unanswered PARSED call → a synthetic placeholder ``ToolMessage``
    inserted immediately after its assistant message (kept behavior).
  - an answered-but-DISPLACED ``ToolMessage`` (something landed between the
    call and its answer) → moved back adjacent (OpenAI validates POSITION,
    not mere existence).
  - a DANGLING ``ToolMessage`` (no in-list assistant carries its id) → dropped
    (the mirror 400: role 'tool' must respond to a preceding 'tool_calls').

``strip_divergent_tool_call_residue`` is shared by the durable heal
(``memory_load_node`` — same-id replace persists the strip into the checkpoint)
and the committed-thread recovery tool (``scripts/repair_poisoned_thread.py``).
Healthy messages carry ak-mirrors of their REAL parsed calls — those mirrors
are preserved byte-for-byte; only divergent ids are stripped.

Pure functions (no I/O) → unit-testable in isolation.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

# Distinct, self-explaining content so a human reading the transcript (or a
# Langfuse trace) sees exactly why the ToolMessage is here and isn't real.
ORPHAN_PLACEHOLDER = (
    "[no result recorded — this tool call was interrupted or superseded "
    "before it produced a result]"
)


def _tool_call_id(tc: object) -> str | None:
    """tool_calls entries are dicts (``{'name', 'args', 'id'}``) on LangChain
    AIMessages; stay defensive against object-shaped variants from other SDKs."""
    if isinstance(tc, dict):
        return tc.get("id")
    return getattr(tc, "id", None)


def _parsed_ids(m: AIMessage) -> set[str]:
    return {i for tc in (getattr(m, "tool_calls", None) or []) if (i := _tool_call_id(tc))}


def strip_divergent_tool_call_residue(m: BaseMessage) -> AIMessage | None:
    """Sanitized same-id COPY of an AIMessage carrying malformed/divergent
    tool-call residue, or ``None`` when the message is clean (the common case).

    Strips:
      - ``invalid_tool_calls`` — parse-failed calls that never executed;
      - ``additional_kwargs["tool_calls"]`` entries whose id is NOT among the
        parsed ``.tool_calls`` ids (the raw mirror must not exceed the parsed
        list — anything beyond it is exactly what the ChatLiteLLM ``elif``
        would resurrect unanswerable onto the wire).

    PRESERVES the healthy ak-mirror of real parsed calls untouched. The copy
    keeps the message id, so an ``add_messages`` update REPLACES the poisoned
    message in place (position preserved) — the durable-heal contract.
    """
    if not isinstance(m, AIMessage):
        return None
    parsed = _parsed_ids(m)
    ak = getattr(m, "additional_kwargs", None) or {}
    ak_calls = ak.get("tool_calls") or []
    divergent = [c for c in ak_calls if _ak_id(c) not in parsed]
    if not (getattr(m, "invalid_tool_calls", None) or divergent):
        return None
    new_ak = dict(ak)
    kept = [c for c in ak_calls if _ak_id(c) in parsed]
    if kept:
        new_ak["tool_calls"] = kept
    else:
        new_ak.pop("tool_calls", None)
    return m.model_copy(update={"invalid_tool_calls": [], "additional_kwargs": new_ak})


def _ak_id(c: object) -> str | None:
    """id of a raw additional_kwargs tool_calls entry (provider-dict shaped)."""
    if isinstance(c, dict):
        return c.get("id")
    return getattr(c, "id", None)


def repair_orphaned_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return a message list whose WIRE form carries no unanswerable tool_call.

    Order-preserving and idempotent; the clean common case returns an
    equivalent list (same objects — no copies unless something needed fixing).
    Four normalizations, per the module docstring: strip divergent residue,
    re-adjoin displaced answers, synthesize placeholders for unanswered parsed
    calls, drop dangling ToolMessages.
    """
    # Pass 0 — strip divergent residue on copies.
    msgs: list[BaseMessage] = [strip_divergent_tool_call_residue(m) or m for m in messages]

    # Pass 1 — index: which ids are owned by an AIMessage; which ToolMessages answer them.
    owned: set[str] = set()
    for m in msgs:
        if isinstance(m, AIMessage):
            owned |= _parsed_ids(m)
    answers: dict[str, list[ToolMessage]] = {}
    for m in msgs:
        if isinstance(m, ToolMessage) and m.tool_call_id in owned:
            answers.setdefault(m.tool_call_id, []).append(m)

    # Pass 2 — rebuild: every owned answer sits immediately after its owner (in
    # tool_call order); unanswered owned ids get the synthetic placeholder;
    # dangling ToolMessages (not owned by any in-list AIMessage) are dropped.
    repaired: list[BaseMessage] = []
    for m in msgs:
        if isinstance(m, ToolMessage):
            continue  # owned → re-placed adjacent to its owner; dangling → dropped
        repaired.append(m)
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                tc_id = _tool_call_id(tc)
                if not tc_id:
                    continue
                if tc_id in answers:
                    repaired.extend(answers.pop(tc_id))
                else:
                    repaired.append(
                        ToolMessage(content=ORPHAN_PLACEHOLDER, tool_call_id=tc_id)
                    )
    return repaired
