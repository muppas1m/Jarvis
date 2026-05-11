"""
Tool selector structural smoke.

Phase 1 only registers one tool (memory_search) and it's `always_loaded=True`.
That means we CAN'T meaningfully test "the selector picks the right tool
from N candidates" — there are no candidates to choose between. But we
CAN test the structural contract that matters when Phase 2 onboards
gmail / calendar / web_research tools:

  - select_relevant_tools(query) returns AT LEAST every always-loaded tool.
  - When no rankable tools exist, the result is exactly the always-loaded
    set (not duplicated, not missing, not silently failing).
  - The always-loaded set is non-empty in Phase 1 (memory_search is in it).

If any of these break, Phase 2's gmail tools won't surface even when the
master's query screams "send an email" — because the dynamic-selection
path is what passes them to the LLM. The structural smoke locks down the
plumbing so the actual tool-relevance test can be added in Phase 2 once
there are real candidates to rank.
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
async def test_selector_returns_only_always_loaded_when_no_rankables() -> None:
    """With Phase 1's registry (only memory_search, always_loaded=True),
    select_relevant_tools should return exactly that one tool — the
    always-loaded set, no ranked additions, no duplicates.

    This is the structural contract Phase 2 relies on: when ranked
    candidates exist they merge AFTER always-loaded; when they don't,
    the result equals always-loaded."""
    expected_names = set(_always_loaded_names())
    if not expected_names:
        pytest.skip("no always-loaded tools registered — nothing to assert")

    # Issue a query that has nothing semantically to do with memory_search.
    # The point isn't relevance; it's that the selector path runs cleanly
    # and returns the always-loaded set.
    selected = await tool_registry.select_relevant_tools(
        query="xyzzy unrelated query placeholder",
        top_k=5,
    )
    selected_names = {t.name for t in selected}

    assert selected_names == expected_names, (
        f"Selector returned {sorted(selected_names)}, expected exactly "
        f"the always-loaded set {sorted(expected_names)}. Either the "
        f"always-loaded plumbing is broken, or rankable tools snuck in "
        f"and duplicated entries (which would also break this assertion)."
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
