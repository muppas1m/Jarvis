"""
Tool selector structural smoke.

select_relevant_tools(query, top_k) returns every `always_loaded=True` tool PLUS
the top_k rankables by cosine — and at the current scale (rankable tools <= top_k)
it FAST-PATHS to "all rankables", skipping the cosine search as pure latency (tool
order doesn't change whether the model calls a tool). These tests lock the
structural contract the agent depends on:

  - the always-loaded set is non-empty (memory_search is in it);
  - select_relevant_tools ALWAYS includes every always-loaded tool;
  - at current scale it returns always-loaded ∪ all-rankable, deduped;
  - empty/whitespace queries don't crash.

If always-loaded plumbing breaks, the master's "send an email" tools won't surface
to the LLM. Deliberate NON-GOAL: there is no cosine relevance threshold on
selection — the design is offer-generously / let-the-model-decide. Withholding a
tool the query actually needs (a false negative; tool-description-vs-query cosine
is often low even when the tool IS relevant) is worse than offering an unused one
the model ignores. Over-invocation on trivial inputs is addressed by always_loaded
scoping + the triviality-classifier route, NOT by thresholding selection (see
project_trivial_message_over_invocation).
"""
import pytest

from app.agent.tools import register_all_tools
from app.agent.tools.registry import tool_registry


@pytest.fixture(autouse=True)
async def ensure_tools_registered():
    """register_all_tools is idempotent (subsequent registers replace
    the entry by name). Calling here makes the test self-contained:
    works whether or not lifespan has already brought the registry up."""
    register_all_tools()
    yield


def _always_loaded_names() -> list[str]:
    return sorted(
        e.name for e in tool_registry._entries.values() if e.always_loaded
    )


def test_always_loaded_set_is_non_empty() -> None:
    """memory_search is the canonical always-loaded tool in Phase 1.
    If it's not always-loaded, dynamic selection has to surface it via
    embedding similarity — which is exactly the over-pull problem we
    DON'T want to fight in Phase 1 (see project_trivial_message_over_invocation).
    """
    names = _always_loaded_names()
    assert "memory_search" in names, (
        f"memory_search should be always_loaded in Phase 1; got always-loaded "
        f"set: {names}"
    )


@pytest.mark.asyncio
async def test_selector_surfaces_always_loaded_plus_rankables_at_current_scale() -> None:
    """The load-bearing contract: select_relevant_tools ALWAYS includes every
    always-loaded tool, and at the current scale (rankable tools <= top_k) it
    returns always-loaded ∪ all-rankable — the fast-path "offer generously, let
    the model decide" design (there is NO relevance threshold on selection).

    (Was a Phase-1 assertion that an unrelated query returns ONLY memory_search —
    obsolete once calendar / document / task tools onboarded as rankables; an
    unrelated query now correctly surfaces all rankables, since the model, not a
    cosine floor, decides what to call.)"""
    always = set(_always_loaded_names())
    if not always:
        pytest.skip("no always-loaded tools registered — nothing to assert")
    rankable = {e.name for e in tool_registry._entries.values() if not e.always_loaded}

    top_k = 15
    selected = [
        t.name for t in await tool_registry.select_relevant_tools(
            query="xyzzy unrelated query placeholder", top_k=top_k,
        )
    ]
    selected_set = set(selected)

    assert always.issubset(selected_set), f"always-loaded dropped: {sorted(always - selected_set)}"
    assert len(selected) == len(selected_set), f"duplicate tool names: {selected}"
    assert len(selected_set) <= len(always) + top_k
    if len(rankable) <= top_k:
        # Fast-path: relevance is irrelevant at this scale — everything is offered.
        assert selected_set == always | rankable, (
            f"fast-path contract broken: expected always ∪ rankable, "
            f"got {sorted(selected_set)} (missing {sorted((always | rankable) - selected_set)})"
        )


@pytest.mark.asyncio
async def test_selector_does_not_duplicate_always_loaded_in_results() -> None:
    """Defensive: if a future registration accidentally creates a tool
    that's BOTH always_loaded=True AND also matches the cosine query,
    the merge logic should dedup. Test this by counting names in the
    result — every name must appear exactly once."""
    selected = await tool_registry.select_relevant_tools(
        query="memory_search recall remember",   # would match memory_search
        top_k=5,
    )
    names = [t.name for t in selected]
    assert len(names) == len(set(names)), (
        f"Selector returned duplicate tool names: {names}. The merge step "
        f"in select_relevant_tools is supposed to dedup by name."
    )


@pytest.mark.asyncio
async def test_selector_does_not_raise_on_empty_query() -> None:
    """Empty/whitespace queries shouldn't crash — agent_node may pass
    them when the user message is purely punctuation or whitespace.
    Result can be anything as long as it's a list and the call returned."""
    result = await tool_registry.select_relevant_tools(query="", top_k=5)
    assert isinstance(result, list)
    # And the always-loaded set should still be in there.
    expected_names = set(_always_loaded_names())
    assert expected_names.issubset({t.name for t in result})
