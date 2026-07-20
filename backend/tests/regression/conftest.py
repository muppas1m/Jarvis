"""Regression tier — real graph, everything pinned. The graph fixture disposes+rebinds
the checkpointer per test (the async-rebind trap)."""
import pytest

from tests.harness import ensure_graph


@pytest.fixture
async def graph_runner():
    return await ensure_graph()


@pytest.fixture(autouse=True)
async def _briefing_state_guard():
    from tests.harness import preserved_briefing_state
    async with preserved_briefing_state():
        yield
