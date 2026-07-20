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


def pytest_runtest_makereport(item, call):
    """Loss-proof capture for HARNESS failures (both tiers): the red's evidence lands in
    the artifact, not only the terminal."""
    if call.when == "call" and call.excinfo is not None:
        from tests.harness.capture import record
        record("HARNESS-FAIL", item.nodeid, 0, "FAIL", repr(call.excinfo.value)[:300])
