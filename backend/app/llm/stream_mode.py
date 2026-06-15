"""Token-stream flag — turns on internal LLM streaming for the agent's chat
model so LangGraph's ``stream_mode="messages"`` emits true token-by-token
chunks (not one assembled message).

Default ``False``: ``run_turn`` (the non-streaming ``/api/chat`` + the Telegram
channel) leaves the agent's ``ChatLiteLLM`` with ``streaming=False`` — ``.ainvoke()``
returns the assembled message in one shot, exactly as before. Byte-for-byte
unchanged for every existing caller.

``stream_turn`` sets this ``True`` before driving ``graph().astream(...)``.
``_build_chat_model`` (nodes.py) reads it and builds the primary + fallback
``ChatLiteLLM`` with ``streaming=True``, so every ``on_llm_new_token`` callback
fires — and flows, through the ``FallbackChatLLM`` wrapper's passed-through
``config``, into LangGraph's token stream.

A contextvar (not an ``AgentState`` field) on purpose: it never lands in the
persisted checkpoint and never changes the graph's state shape. It propagates
through the async call chain (the ``asyncio`` context copy) the same way
``app.llm.eval_mode`` does. Mirrors that module deliberately.
"""
from contextvars import ContextVar

stream_tokens: ContextVar[bool] = ContextVar("jarvis_stream_tokens", default=False)

# Voice mode — set by the voice orchestrator (app.voice). When True, the agent's
# reasoning LLM routes to the FAST tier (settings.FAST_MODEL) for sub-second
# first-token (the §B two-speed cascade), escalating to the frontier model once
# tools have run. The brain (tools/Mem0/safety/approval) is unchanged — only the
# model speed is tuned for the live-speech layer. Same contextvar discipline as
# stream_tokens / eval_mode: never lands in the persisted checkpoint.
voice_mode: ContextVar[bool] = ContextVar("jarvis_voice_mode", default=False)
