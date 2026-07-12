"""
AgentState — the dict that flows through every graph node.

Two design notes:
  - `messages` uses LangGraph's `add_messages` reducer, which appends new
    messages and replaces existing ones by message ID. Without this reducer,
    each node would clobber the message list.
  - The other fields use the default "replace" reducer, which is what we
    want for per-turn metadata (memory context, counters). Each node
    returns a partial-state dict and only the keys it touches get updated.

Adding a field here? Default reducer is replace. If you need accumulate-on-
update (a list that grows across node calls), wrap with `Annotated[..., reducer]`
the way `messages` does.
"""
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # --- conversation history (checkpointer-managed across turns) -----------
    messages: Annotated[list[BaseMessage], add_messages]

    # --- rolling conversation summary (compaction, 4.B.3) -------------------
    # When the verbatim history grows past the threshold, the oldest messages are
    # summarized into here and dropped from `messages`. agent_node injects this as
    # a context block so the thread survives without sending the full history.
    # Checkpointer-managed (persists across turns).
    running_summary: str
    # True ONLY on the turn compaction just fired — drives the live in-chat
    # "compacted" divider. Not surfaced on history reload (the divider is live).
    compacted_last_turn: bool

    # --- memory context (set by memory_load_node, read by agent_node) -------
    user_profile_always_on: dict
    user_profile_on_demand: list[dict]
    relevant_memories: list[dict]
    # Proactive-briefing check-in (5.4) — computed once in memory_load_node. directive =
    # the model guidance (injected by agent_node); proactive = the deterministic mode
    # (suppress / surface_single / surface_multiday) + offer = the code-owned OFFER line,
    # both read by the runner post-turn to CODE-render the brief/offer into the reply.
    briefing_directive: str
    briefing_proactive: str
    briefing_offer: str

    # --- per-turn metadata --------------------------------------------------
    thread_id: str
    platform: str            # "telegram", "whatsapp", "web"
    channel_user_id: str     # platform's user/chat ID
    user_message: str        # the original master message that started this turn
    turn_started_at: str     # ISO timestamp — also used as a turn_id for rate limit keys

    # --- tool-call accounting ------------------------------------------------
    tool_calls_this_turn: int
    # Step B (OPEN-1 idempotency floor) — reserved now so the state contract is settled
    # ONCE and Step B doesn't re-pour the schema. The turn-scoped set of action signatures
    # already queued this turn — `(tool, normalize(to))` for email_send, `(tool, start_iso)`
    # for calendar_create — so a re-queue of the SAME action returns the existing [QUEUED]
    # marker instead of a duplicate card (robust to subject/body regeneration). Step A does
    # NOT read or write this; it is declared here as the agreed shape only.
    queued_signatures: list[str]
    # A1 (natural loop) — the row PKs (str) of approval cards TOUCHED this turn (freshly created
    # OR reused via already-queued / content-dedup). The DETERMINISTIC read-back (queued_finish)
    # names these via describe_card, so the D1 guarantee survives the new termination on the weak
    # llama. Plain replace-reducer list, WRITTEN read-prior-accumulate
    # (`list(state.get("queued_this_turn") or []) + [id]`) exactly like queued_signatures, and RESET
    # []-per-turn in all 3 initial_state dicts — an accumulate reducer would defeat that reset.
    queued_this_turn: list[str]

    # --- card resolution (A2 s2: the referent is the conversation's jarvis linkage; the
    # old presented_approval_id/presented_via client coupling retired in s3) ---
    # Set by card_resolution_node when it RESOLVES a card (approve/reject/edit/skip/stale),
    # read by the runner post-graph to reconstruct the frontend events (decision_resolved /
    # approval_required for an edit re-queue / presented_nav for skip). {} when the message
    # was a question routed to the agent instead.
    # B1.0 CH-5 — a LIST: a multi-target consume resolves N cards and EVERY one must flip on
    # the dashboard (one decision_resolved per entry). Single resolutions are one-element lists.
    card_outcomes: list
    # `card_handled` True → the node fully resolved the card → route to persist (end the
    # turn with the node's outcome reply). False/absent → route to the agent (a question
    # about the card, or no card) with `card_context` injected so the agent answers about
    # the RIGHT card (D3) and can note it's still pending.
    card_handled: bool
    card_context: str
    # s4 — an edit directive was issued this turn; if no mint follows, the terminal node says
    # so honestly ("that change didn't apply") instead of implying success. Turn-reset ×3.
    edit_expected: bool
    # D29 — the directive's exact target + tool: the mint supersedes BY this id (never
    # key-matching, which a key-field edit defeats) and pins the re-emit SAME-TOOL. Reset ×3.
    edit_target_id: str
    edit_tool_name: str

    # --- final assistant text (set when agent emits a non-tool message) -----
    final_response: str

    # --- A2 s1b — the ONE terminal delta + briefing idempotency --------------
    # terminal_delta: the in-graph terminal text that was NEVER streamed as tokens (the
    # queued_finish approval message + the persist-attached briefing). ONE core-computed value
    # every channel consumes: voice speaks it post-stream when tokens already streamed (NV7);
    # non-streamed paths get it inside final_response anyway. Turn-reset ×3; emitters ACCUMULATE
    # (read-prior + append), never overwrite.
    terminal_delta: str
    # briefing_attached: persist's re-entrancy guard — the render + the mark_offered/HWM stamps
    # fire at most once per turn even if the node re-runs. Turn-reset ×3.
    briefing_attached: bool
