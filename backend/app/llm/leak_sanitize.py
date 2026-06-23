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


def strip_function_leak(text: str | None, *, trim: bool = True) -> str:
    """Remove `<function…>…</function>` leak shapes from `text`, leaving the rest
    intact. Fast no-op unless the literal `<function` tag is present (so ordinary
    prose containing the word "function" is never modified). `trim=False` keeps
    leading/trailing whitespace — used by the streaming filter, which needs the
    cleaned text to grow monotonically (trimming would make it shrink)."""
    if not text or "<function" not in text.lower():
        return text or ""
    s = _LEAK_CLOSED.sub("", text)
    s = _LEAK_UNCLOSED.sub("", s)  # any unclosed tail the closed pass left behind
    return s.strip() if trim else s


_TAG = "<function"


def _held_tag_prefix_len(seen: str) -> int:
    """Length of the trailing run of `seen` that could still grow into `<function`
    — held back rather than rendered as a partial tag (so even a tag SPLIT across
    tokens never flashes). 0 if the tail can't be a tag prefix. O(len(_TAG))."""
    window = seen[-len(_TAG):].lower()
    for i in range(len(window)):
        if _TAG.startswith(window[i:]):
            return len(window) - i
    return 0


def make_stream_leak_filter():
    """A stateful, per-stream filter for the LIVE token stream (the secondary
    visual-flash fix): feed it each streamed token delta, get back only the text
    safe to render NOW. It drops a `<function…>` leak span as it streams — the
    primary streams its full leak first, then the re-issued clean answer (no
    `<function` tag) flows through. Monotonic (never un-renders), holds a forming
    tag back so not even a partial flashes, and is a near pass-through until a
    `<function` tag appears, so a normal turn is unaffected (O(1) per token)."""
    state = {"seen": "", "shown": 0, "dirty": False}

    def feed(text: str) -> str:
        state["seen"] += text
        seen = state["seen"]
        if not state["dirty"]:
            recent = seen[-(len(text) + len(_TAG)):].lower()
            if _TAG not in recent:
                # No full tag yet — render everything except a tag-prefix that may
                # still be forming at the very end (held until the next token).
                safe = len(seen) - _held_tag_prefix_len(seen)
                out = seen[state["shown"]:safe]
                state["shown"] = safe
                return out
            state["dirty"] = True
        clean = strip_function_leak(seen, trim=False)
        out = clean[state["shown"]:]
        state["shown"] = len(clean)
        return out  # only the newly-revealed CLEAN text (often "" mid-leak)

    return feed
