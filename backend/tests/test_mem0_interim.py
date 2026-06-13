"""P5c — Mem0 interim bloat controls: trivial-turn gating + dedup-on-write.

Slows the +265-per-session growth without dropping personal facts. Conservative
by design (when in doubt, persist); full consolidation/supersession is Turn 26.5.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.memory.manager import _is_trivial_turn
from app.memory.mem0_client import Mem0Client


# --------------------------------------------------------------------------- #
# trivial-turn gating                                                         #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("msg,trivial", [
    ("hi", True),
    ("Hello!", True),
    ("thanks", True),
    ("got it", True),
    ("ok", True),
    ("k", True),
    ("ok thanks", True),     # multi-word ack in the explicit set
    ("sounds good", True),
    ("", True),
    ("  ", True),
    # personal facts — NEVER trivial (spontaneous-save intent preserved)
    ("I'm allergic to peanuts", False),
    ("my dentist is Dr. Smith", False),
    ("I prefer morning meetings", False),
    # terse one-word fact (answering "what are you allergic to?") — must persist;
    # this is exactly why we dropped the length cutoff
    ("peanuts", False),
    ("Dr. Smith", False),
    # substantive non-facts — persisted (conservative over-persist is the safe side)
    ("Schedule a meeting Friday at 2pm", False),
    ("What is Project Zephyr?", False),
])
def test_is_trivial_turn(msg, trivial):
    assert _is_trivial_turn(msg) is trivial


# --------------------------------------------------------------------------- #
# dedup-on-write                                                              #
# --------------------------------------------------------------------------- #
def _make_client() -> Mem0Client:
    """Bypass __init__ (which builds the real AsyncMemory) — inject a mock."""
    c = Mem0Client.__new__(Mem0Client)
    c.client = AsyncMock()
    return c


# MEM0_DEDUP_ENABLED defaults to False (dormant until Turn 26.5 fixes search),
# so tests that exercise the dedup PATH must turn it on explicitly.
@pytest.mark.asyncio
async def test_dedup_skips_near_identical():
    c = _make_client()
    c.search = AsyncMock(return_value=[{"score": 0.95, "content": "User likes tea"}])
    with patch("app.config.settings.MEM0_DEDUP_ENABLED", True):
        res = await c.add("User: I like tea")
    assert res.get("skipped_duplicate") is True
    c.client.add.assert_not_called()  # never written


@pytest.mark.asyncio
async def test_dedup_writes_novel_fact():
    c = _make_client()
    c.search = AsyncMock(return_value=[{"score": 0.40}])  # below threshold
    with patch("app.config.settings.MEM0_DEDUP_ENABLED", True):
        await c.add("User: I just adopted a dog named Rex")
    c.client.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_dedup_writes_when_no_existing_memory():
    c = _make_client()
    c.search = AsyncMock(return_value=[])
    with patch("app.config.settings.MEM0_DEDUP_ENABLED", True):
        await c.add("User: first fact ever")
    c.client.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_dedup_fails_open_on_search_error():
    c = _make_client()
    c.search = AsyncMock(side_effect=RuntimeError("vector store down"))
    with patch("app.config.settings.MEM0_DEDUP_ENABLED", True):
        await c.add("User: a fact")
    c.client.add.assert_awaited_once()  # dedup error must not block the write


@pytest.mark.asyncio
async def test_dedup_disabled_by_default_skips_the_search():
    """Default-off: no dedup search runs (the P5c calibration finding — it can't
    fire today, so don't burn a dead search per write)."""
    c = _make_client()
    c.search = AsyncMock(return_value=[{"score": 0.99}])
    await c.add("User: anything")  # MEM0_DEDUP_ENABLED defaults False
    c.search.assert_not_called()
    c.client.add.assert_awaited_once()


@pytest.mark.asyncio
async def test_dedup_can_be_bypassed_per_call():
    c = _make_client()
    c.search = AsyncMock(return_value=[{"score": 0.99}])
    with patch("app.config.settings.MEM0_DEDUP_ENABLED", True):
        await c.add("User: forced write", dedup=False)
    c.client.add.assert_awaited_once()
    c.search.assert_not_called()  # dedup=False skips the check even when enabled
