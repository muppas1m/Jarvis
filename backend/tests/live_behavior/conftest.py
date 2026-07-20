"""Live-behavior tier — real model, sampled. Runs with the suite at small HARNESS_N;
`make harness-sweep` elevates N. Evidence is loss-proof via tests.harness.capture."""
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
