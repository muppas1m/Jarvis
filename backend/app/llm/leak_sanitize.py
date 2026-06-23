"""
Detect + strip the Llama-native tool-call format leaking as assistant TEXT.

Groq's llama-3.3-70b (primary) intermittently emits a tool call as
``<function>name{args}</function>`` text in the response CONTENT instead of a
structured ``tool_calls`` array — and Groq's API ACCEPTS it (no error), so it's
NOT the ``tool_use_failed`` BadRequestError ``FallbackChatLLM`` already catches.
The text becomes the "answer", the tool never runs, and the syntax leaks to the
screen. It also self-perpetuates: once the leak is in a thread's history the
model anchors to its own past format and re-emits it (in-context poisoning). See
``project_open_weights_tool_schema_and_conversation_poisoning``.

Scope is the leak SHAPE only — the literal ``<function…>`` tag — so a plain
mention of the word "function" (e.g. the master asking "why did you message that
function thing") is NEVER touched. The ``\\b`` after ``function`` also means
``<functions>`` (plural) and ``<functionx`` don't match.
"""
import re

# Opening tag of the leak — `<function>` or `<function=name>`.
_LEAK_TAG = re.compile(r"<function\b[^>]*>", re.IGNORECASE)
# A closed `<function…>…</function>` block (non-greedy; DOTALL for multi-line args).
_LEAK_CLOSED = re.compile(r"<function\b[^>]*>.*?</function>", re.IGNORECASE | re.DOTALL)
# An unclosed tail — `<function…>` with no closer (a truncated/streamed leak).
_LEAK_UNCLOSED = re.compile(r"<function\b[^>]*>.*$", re.IGNORECASE | re.DOTALL)


def looks_like_function_leak(content: str | None) -> bool:
    """True if `content` carries a `<function…>` tool-call leak. Used to fall over
    to the fallback model when the primary returns this AS TEXT (no tool_calls)."""
    return bool(content) and bool(_LEAK_TAG.search(content))


def strip_function_leak(text: str | None) -> str:
    """Remove `<function…>…</function>` leak shapes from `text`, leaving the rest
    intact. Fast no-op unless the literal `<function` tag is present (so ordinary
    prose containing the word "function" is never modified)."""
    if not text or "<function" not in text.lower():
        return text or ""
    s = _LEAK_CLOSED.sub("", text)
    s = _LEAK_UNCLOSED.sub("", s)  # any unclosed tail the closed pass left behind
    return s.strip()
