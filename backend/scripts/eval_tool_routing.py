"""Tool-routing eval — does the agent pick the RIGHT tool for a query?

Binds the full registered tool set to the real chat model (the production fast-path binds
ALL tools, so the LLM chooses by reading descriptions) and checks that each probe routes to
its expected tool, N samples each. Built for the approvals_pending ⟂ email_history_search
disambiguation (5f242a1), but add rows as routing regressions surface.

    docker compose exec backend python scripts/eval_tool_routing.py

NOTE: prints which model actually answered. If Groq llama-3.3-70b (the primary) is
rate-limited, the FallbackChatLLM serves gpt-4o-mini — re-run when llama has quota to verify
the PRIMARY. Makes a real LLM call per sample (small cost).
"""
import asyncio
import logging
from collections import Counter

import _smoke_isolation  # noqa: F401  — DB isolation parity with the other scripts (no prod writes)
from langchain_core.messages import HumanMessage, SystemMessage

from app.agent.tools import register_all_tools, tool_registry

logging.disable(logging.CRITICAL)  # quiet the litellm/fallback chatter; we only want results

_SYS = (
    "You are Jarvis, the master's personal assistant. When the master asks something a "
    "registered tool can answer, call the single most appropriate tool."
)

# (query, expected_tool). Controls (email_history_search) guard against over-correction.
PROBES = [
    ("what are the pending draft emails", "approvals_pending"),
    ("what's pending", "approvals_pending"),
    ("what did you draft", "approvals_pending"),
    ("show me the approvals", "approvals_pending"),
    ("anything waiting on me to approve", "approvals_pending"),
    ("what emails came in from Bob last week", "email_history_search"),
    ("which emails still need a reply", "email_history_search"),
    ("did the email from Priya get answered", "email_history_search"),
]
SAMPLES = 3


async def main() -> int:
    register_all_tools()
    from app.agent.nodes import _build_chat_model

    model = _build_chat_model([e.tool for e in tool_registry._entries.values()])

    async def route(q: str) -> str:
        r = await model.ainvoke([SystemMessage(content=_SYS), HumanMessage(content=q)])
        return r.tool_calls[0]["name"] if getattr(r, "tool_calls", None) else "(text)"

    failures = 0
    for q, expected in PROBES:
        got = Counter([await route(q) for _ in range(SAMPLES)])
        ok = all(name == expected for name in got.elements())
        if not ok:
            failures += 1
        print(f"{'OK  ' if ok else 'FAIL'} {q!r:46} expect={expected:22} got={dict(got)}")

    print(f"\n{'PASS' if failures == 0 else f'{failures} FAIL'} — {len(PROBES)} probes × {SAMPLES} samples")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
