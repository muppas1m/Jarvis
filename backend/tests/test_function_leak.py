"""
The Llama-native tool-call leak: Groq's primary emits `<function>name{args}</function>`
as assistant TEXT (no tool_calls, no error), so the tool never runs + the syntax
leaks. Tests the three layers: re-issue on the fallback, sanitize, de-poison —
and that NORMAL paths + a plain mention of "function" are untouched.
"""
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda

import app.agent.runner as runner_mod
from app.agent.nodes import _depoison_for_llm
from app.llm.fallback_llm import FallbackChatLLM, _is_function_leak
from app.llm.leak_sanitize import (
    looks_like_function_leak,
    make_stream_leak_filter,
    strip_function_leak,
)

LEAK = '<function>calendar_read{"days_ahead": 7, "max_results": 20}</function>'
# the user message the master literally sent — must NEVER be touched
USER_ASKING = "why did you message that function thing"


# --- detector ---------------------------------------------------------------
def test_detector_flags_leak_only():
    assert looks_like_function_leak(LEAK)
    assert not looks_like_function_leak("You have 3 meetings tomorrow.")
    assert not looks_like_function_leak(USER_ASKING)
    assert not looks_like_function_leak("I'll call the function now.")
    assert not looks_like_function_leak("")


# --- sanitizer --------------------------------------------------------------
def test_sanitizer_strips_only_the_shape():
    assert strip_function_leak(LEAK) == ""
    mixed = strip_function_leak(f"Here's the result: {LEAK} all done.")
    assert "<function" not in mixed and "Here's the result" in mixed and "all done" in mixed
    # plain prose with the WORD function — untouched
    assert strip_function_leak(USER_ASKING) == USER_ASKING
    assert strip_function_leak("a perfectly clean answer") == "a perfectly clean answer"
    # unclosed/streamed leak tail
    assert strip_function_leak("ok <function>calendar_read{").startswith("ok")
    assert "<function" not in strip_function_leak("ok <function>calendar_read{")


# --- FallbackChatLLM layer 1: re-issue on leak, pass-through otherwise -------
def _llm(primary_msg, fallback_msg):
    return FallbackChatLLM(
        primary=RunnableLambda(lambda _x: primary_msg),
        fallback=RunnableLambda(lambda _x: fallback_msg),
    )


async def test_leak_reissues_on_fallback_and_tool_runs():
    leaked = AIMessage(content=LEAK)  # no tool_calls
    structured = AIMessage(
        content="", tool_calls=[{"name": "calendar_read", "args": {"days_ahead": 7}, "id": "c1"}]
    )
    result = await _llm(leaked, structured).ainvoke([HumanMessage(content="what's on my calendar?")])
    assert result is structured           # re-issued on the fallback
    assert result.tool_calls              # the tool WILL run now
    assert not _is_function_leak(result)  # no leak in the recovered result


async def test_clean_text_passes_through_no_reissue():
    clean = AIMessage(content="You have 3 meetings tomorrow.")
    sentinel = AIMessage(content="FALLBACK SHOULD NOT FIRE")
    result = await _llm(clean, sentinel).ainvoke([HumanMessage(content="hi")])
    assert result is clean  # primary's clean answer kept; no fall-over


async def test_structured_toolcall_passes_through_no_reissue():
    structured = AIMessage(content="", tool_calls=[{"name": "calendar_read", "args": {}, "id": "c1"}])
    sentinel = AIMessage(content="FALLBACK SHOULD NOT FIRE")
    result = await _llm(structured, sentinel).ainvoke([HumanMessage(content="calendar?")])
    assert result is structured  # has tool_calls → not a leak → no fall-over


# --- de-poison the history sent to the LLM ----------------------------------
def test_depoison_strips_assistant_leak_leaves_user_alone():
    history = [
        HumanMessage(content="what's on my calendar?"),
        AIMessage(content=LEAK),       # the poisoned assistant turn
        HumanMessage(content=USER_ASKING),
    ]
    out = _depoison_for_llm(history)
    assert out[0].content == "what's on my calendar?"   # human untouched
    assert "<function" not in out[1].content            # poison stripped from assistant
    assert out[2].content == USER_ASKING                # user's "function" msg untouched
    # original objects not mutated (copies)
    assert history[1].content == LEAK


# --- STREAMED paths: never SPEAK the leak (layer 1) -------------------------
async def test_speak_text_never_voices_the_leak(monkeypatch):
    seen = {}

    async def fake_synth(t):
        seen["tts"] = t
        return b"AUDIO"

    monkeypatch.setattr(runner_mod, "synthesize", fake_synth)

    # a pure leak chunk → nothing synthesized, no audio event (no caption)
    seen.clear()
    assert await runner_mod._speak_text(LEAK) is None
    assert "tts" not in seen  # synthesize was NOT called

    # a clean chunk → spoken, caption clean
    ev = await runner_mod._speak_text("You have 3 meetings tomorrow.")
    assert ev is not None and "<function" not in ev["content"]["text"]

    # leak + clean text → only the clean part voiced; caption == TTS source (lockstep)
    seen.clear()
    ev = await runner_mod._speak_text(f"{LEAK} You have 3 meetings.")
    assert ev is not None
    assert "<function" not in ev["content"]["text"]
    assert ev["content"]["text"] == seen["tts"]


# --- STREAMED paths: suppress the live visual flash (layer 2) ----------------
def test_stream_filter_suppresses_leak_then_streams_clean():
    f = make_stream_leak_filter()
    leak_out = "".join(f(t) for t in ["<function>cal", "endar_read{", '"x":7}', "</function>"])
    assert leak_out == ""  # the leak never renders
    clean_out = "".join(f(t) for t in ["You have ", "3 meetings", " tomorrow."])
    assert clean_out == "You have 3 meetings tomorrow."  # re-issued answer flows through


def test_stream_filter_passthrough_no_regression():
    f = make_stream_leak_filter()
    toks = ["You ", "have ", "3 ", "meetings ", "tomorrow."]
    assert "".join(f(t) for t in toks) == "You have 3 meetings tomorrow."  # unchanged


def test_stream_filter_split_tag_no_partial_flash():
    f = make_stream_leak_filter()
    parts = ["Sure! ", "<func", "tion>calendar_read{}", "</function>", " Done."]
    out = "".join(f(t) for t in parts)
    assert "<func" not in out  # not even a partial tag flashes
    assert "Sure!" in out and "Done." in out  # clean text around the leak survives
