"""
Prompt-cache stability tests.

Anthropic / OpenAI / Groq all do prompt caching at the >=1024-token mark for
identical PREFIXES. A single byte change at the top of the prompt
invalidates the entire cache; a change at the bottom only invalidates the
suffix below it. So `prompts.py` is split into:

  STABLE PREFIX  = IDENTITY_BLOCK + SAFETY_DOCTRINE + always-on profile
                  lines. Rarely changes; this is what we want cached.
  VOLATILE SUFFIX = on-demand profile, recalled memories, current datetime.

These tests lock down two contracts:
  1. The STABLE PREFIX is byte-identical across two calls when always_on
     is unchanged. Changing only the volatile suffix keeps the prefix
     intact.
  2. Sorting always_on keys in different orders at the call site doesn't
     produce a different prefix — alphabetical sort happens inside
     build_system_prompt, so dict iteration order in caller code doesn't
     bust the cache.

If either contract breaks, every prompt cache hit becomes a miss and our
LLM bill goes up significantly. The test is the canary.
"""
from app.agent.prompts import (
    IDENTITY_BLOCK,
    SAFETY_DOCTRINE,
    build_capabilities,
    build_system_prompt,
)


_ALWAYS_ON = {
    "name": "Mahesh",
    "always_on": {
        "language": "English",
        "timezone": "America/New_York",
        "communication_style": "Direct, brief, bullet points",
    },
}


def _split_prefix_suffix(prompt: str) -> tuple[str, str]:
    """The STABLE PREFIX runs from the top through the always-on profile
    lines. The VOLATILE SUFFIX starts at <on_demand>. This split mirrors
    what the LLM provider's cache key sees."""
    marker = "<on_demand>"
    idx = prompt.find(marker)
    assert idx != -1, "prompt missing <on_demand> marker — VOLATILE_TEMPLATE changed"
    return prompt[:idx], prompt[idx:]


def test_identity_block_and_safety_doctrine_are_module_level_constants() -> None:
    """If either of these moves to a function or becomes dynamic, the cache
    benefits we get from them being in the STABLE PREFIX disappear."""
    assert isinstance(IDENTITY_BLOCK, str) and IDENTITY_BLOCK.strip()
    assert isinstance(SAFETY_DOCTRINE, str) and SAFETY_DOCTRINE.strip()


def test_stable_prefix_byte_identical_when_only_volatile_changes() -> None:
    """Build the same prompt twice with different volatile inputs and
    assert the prefix is byte-identical. This is what unlocks Anthropic's
    >=1024-token cached prefix."""
    p1 = build_system_prompt(
        always_on_profile=_ALWAYS_ON,
        on_demand_profile=[{"content": "loves blueberry pie"}],
        memories=[{"content": "yesterday booked a flight to NYC"}],
        platform="telegram",
        current_datetime="2026-05-10T12:00:00Z",
    )
    p2 = build_system_prompt(
        always_on_profile=_ALWAYS_ON,
        on_demand_profile=[{"content": "totally different on-demand fact"}],
        memories=[{"content": "totally different memory"}],
        platform="web",
        current_datetime="2026-05-11T18:42:00Z",
    )

    prefix1, _ = _split_prefix_suffix(p1)
    prefix2, _ = _split_prefix_suffix(p2)

    assert prefix1 == prefix2, (
        "STABLE PREFIX changed across calls that only differed in volatile fields. "
        "This breaks prompt caching — every turn becomes a cache miss. Likely "
        "cause: a non-stable field leaked into IDENTITY_BLOCK / SAFETY_DOCTRINE / "
        "the always-on rendering path."
    )


def test_always_on_dict_order_does_not_affect_prefix() -> None:
    """build_system_prompt sorts always_on keys alphabetically before
    rendering. Caller code that builds the dict in different orders
    (e.g. an API client vs the agent's MemoryManager) must produce the
    same prefix string."""
    profile_a = {
        "name": "Mahesh",
        "always_on": {
            "timezone": "America/New_York",
            "language": "English",
            "communication_style": "Direct, brief, bullet points",
        },
    }
    profile_b = {
        "name": "Mahesh",
        "always_on": {
            # Same content, different insertion order
            "communication_style": "Direct, brief, bullet points",
            "language": "English",
            "timezone": "America/New_York",
        },
    }

    common_kwargs = {
        "on_demand_profile": [],
        "memories": [],
        "platform": "telegram",
        "current_datetime": "2026-05-10T12:00:00Z",
    }
    p_a = build_system_prompt(always_on_profile=profile_a, **common_kwargs)
    p_b = build_system_prompt(always_on_profile=profile_b, **common_kwargs)

    assert p_a == p_b, (
        "Dict insertion order changed the rendered prompt. The alphabetical "
        "sort inside build_system_prompt is supposed to defend against this — "
        "if this assert fires, the sort got dropped."
    )


def test_changing_always_on_does_invalidate_prefix() -> None:
    """Sanity check the inverse: if always_on actually changes, the prefix
    SHOULD change. Otherwise the test above would pass for the wrong reason."""
    profile_a = dict(_ALWAYS_ON)
    profile_b = {
        "name": _ALWAYS_ON["name"],
        "always_on": {**_ALWAYS_ON["always_on"], "timezone": "Europe/London"},
    }
    common_kwargs = {
        "on_demand_profile": [],
        "memories": [],
        "platform": "telegram",
        "current_datetime": "2026-05-10T12:00:00Z",
    }
    p_a = build_system_prompt(always_on_profile=profile_a, **common_kwargs)
    p_b = build_system_prompt(always_on_profile=profile_b, **common_kwargs)
    prefix_a, _ = _split_prefix_suffix(p_a)
    prefix_b, _ = _split_prefix_suffix(p_b)
    assert prefix_a != prefix_b, (
        "Changing the timezone in always_on should change the prefix. If this "
        "asserts, the always-on rendering path is broken — it's not actually "
        "incorporating always_on into the prompt."
    )


def test_prefix_contains_identity_and_safety_blocks_verbatim() -> None:
    """Cheap structural check — the prefix should literally contain both
    constants. If someone later adds a function-rendered intro between
    them and the always_on lines, this catches it."""
    prompt = build_system_prompt(
        always_on_profile=_ALWAYS_ON,
        on_demand_profile=[],
        memories=[],
        platform="telegram",
        current_datetime="2026-05-10T12:00:00Z",
    )
    assert IDENTITY_BLOCK.strip() in prompt
    assert SAFETY_DOCTRINE.strip() in prompt
    # The capabilities block (now registry-DERIVED via build_capabilities, #1) is a stable
    # prefix member — deterministic (registration order is fixed) so it must appear verbatim
    # and sit inside the cached prefix (before the volatile suffix).
    capabilities = build_capabilities()
    assert capabilities.strip() in prompt
    prefix, _ = _split_prefix_suffix(prompt)
    assert capabilities.strip() in prefix, (
        "the capabilities block must be in the STABLE PREFIX (before <on_demand>), "
        "else it won't be cached and will re-bill every turn."
    )
